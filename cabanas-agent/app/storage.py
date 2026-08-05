"""Persistência das conversas no Firestore.

Cada mensagem recebida vira um documento cujo ID é o `message_id` da Meta.
Isso resolve duas coisas de uma vez:

1. É o histórico que vai alimentar o painel de fechamento mensal do Adriano.
2. Serve de trava contra duplicata. A Meta reenvia o webhook quando não recebe
   200 rápido; como `create()` falha se o documento já existe, a segunda
   entrega da mesma mensagem é descartada em vez de gerar resposta repetida.

Sobre o painel dos 10%: dá para registrar que o link foi enviado
(`link_enviado`), mas NÃO dá para saber se a pessoa clicou. O link é do
Airbnb, e o clique acontece fora do nosso sistema. Medir clique exigiria
servir um link próprio que redireciona para o Airbnb. O schema abaixo já
deixa espaço para isso (`clicou_em`), caso a gente decida montar o redirect
depois.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from .config import Settings, settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def reservar_mensagem(
        self,
        message_id: str,
        telefone: str,
        texto: str,
        intencao: str,
        *,
        nicho: str = "cabanas",
        lead_quente: bool = False,
        sinais_lead: list[str] | None = None,
    ) -> bool: ...

    async def registrar_resposta(
        self, message_id: str, resposta: str, escalado: bool, link_enviado: bool
    ) -> None: ...

    async def historico(
        self, telefone: str, limite: int, *, nicho: str = "cabanas"
    ) -> list[dict[str, str]]: ...


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStorage:
    """Implementação em memória, para testes e para rodar local sem GCP.

    Não persiste entre reinícios — não usar em produção.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def reservar_mensagem(
        self,
        message_id: str,
        telefone: str,
        texto: str,
        intencao: str,
        *,
        nicho: str = "cabanas",
        lead_quente: bool = False,
        sinais_lead: list[str] | None = None,
    ) -> bool:
        async with self._lock:
            if message_id in self._docs:
                return False
            self._docs[message_id] = {
                "nicho": nicho,
                "telefone": telefone,
                "texto": texto,
                "intencao": intencao,
                "lead_quente": lead_quente,
                "sinais_lead": sinais_lead or [],
                "resposta": None,
                "escalado": False,
                "link_enviado": False,
                "clicou_em": None,
                "criado_em": _agora(),
            }
            return True

    async def registrar_resposta(
        self, message_id: str, resposta: str, escalado: bool, link_enviado: bool
    ) -> None:
        async with self._lock:
            doc = self._docs.get(message_id)
            if doc is not None:
                doc.update(
                    resposta=resposta,
                    escalado=escalado,
                    link_enviado=link_enviado,
                    respondido_em=_agora(),
                )

    async def historico(
        self, telefone: str, limite: int, *, nicho: str = "cabanas"
    ) -> list[dict[str, str]]:
        async with self._lock:
            docs = [
                d
                for d in self._docs.values()
                if d["telefone"] == telefone and d.get("nicho", "cabanas") == nicho
            ]
        docs.sort(key=lambda d: d["criado_em"])
        recentes = docs[-limite:] if limite else docs
        return _para_turnos(recentes)


class FirestoreStorage:
    def __init__(self, cfg: Settings | None = None, client=None) -> None:
        self.cfg = cfg or settings
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore  # import tardio

            self._client = firestore.AsyncClient(project=self.cfg.gcp_project_id)
        return self._client

    def _col(self):
        return self._get_client().collection(self.cfg.firestore_collection)

    async def reservar_mensagem(
        self,
        message_id: str,
        telefone: str,
        texto: str,
        intencao: str,
        *,
        nicho: str = "cabanas",
        lead_quente: bool = False,
        sinais_lead: list[str] | None = None,
    ) -> bool:
        from google.api_core import exceptions as gexc
        from google.cloud import firestore

        try:
            await self._col().document(message_id).create(
                {
                    "nicho": nicho,
                    "telefone": telefone,
                    "texto": texto,
                    "intencao": intencao,
                    "lead_quente": lead_quente,
                    "sinais_lead": sinais_lead or [],
                    "resposta": None,
                    "escalado": False,
                    "link_enviado": False,
                    "clicou_em": None,
                    "criado_em": firestore.SERVER_TIMESTAMP,
                }
            )
            return True
        except gexc.AlreadyExists:
            logger.info("Mensagem %s já processada, ignorando reentrega", message_id)
            return False

    async def registrar_resposta(
        self, message_id: str, resposta: str, escalado: bool, link_enviado: bool
    ) -> None:
        from google.cloud import firestore

        await self._col().document(message_id).update(
            {
                "resposta": resposta,
                "escalado": escalado,
                "link_enviado": link_enviado,
                "respondido_em": firestore.SERVER_TIMESTAMP,
            }
        )

    async def historico(
        self, telefone: str, limite: int, *, nicho: str = "cabanas"
    ) -> list[dict[str, str]]:
        """Últimas trocas com esse telefone neste nicho, mais antigas primeiro.

        O filtro por nicho evita que, quando a academia e o alojamento
        entrarem, uma pessoa que fala com as duas operações veja o contexto de
        uma vazando na outra.

        Precisa do índice composto (nicho ASC, telefone ASC, criado_em DESC) —
        ver firestore.indexes.json.
        """
        from google.cloud import firestore

        consulta = (
            self._col()
            .where(filter=firestore.FieldFilter("nicho", "==", nicho))
            .where(filter=firestore.FieldFilter("telefone", "==", telefone))
            .order_by("criado_em", direction=firestore.Query.DESCENDING)
            .limit(limite)
        )
        docs = [doc.to_dict() async for doc in consulta.stream()]
        docs.reverse()  # a consulta vem do mais novo para o mais antigo
        return _para_turnos(docs)


def _para_turnos(docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Converte documentos do Firestore no formato de histórico do Gemini."""
    turnos: list[dict[str, str]] = []
    for doc in docs:
        if doc.get("texto"):
            turnos.append({"role": "user", "text": doc["texto"]})
        if doc.get("resposta"):
            turnos.append({"role": "model", "text": doc["resposta"]})
    return turnos


def build_storage(cfg: Settings | None = None) -> Storage:
    """Firestore em produção; memória quando não há projeto GCP configurado."""
    cfg = cfg or settings
    if cfg.gcp_project_id:
        return FirestoreStorage(cfg)
    logger.warning("GCP_PROJECT_ID vazio — usando storage em memória (não persiste)")
    return MemoryStorage()
