"""Consultas do painel: métricas, leads quentes e histórico por telefone.

A agregação acontece em Python, sobre os documentos do período. Para o volume
desta operação (centenas de mensagens por mês) isso é mais simples e mais
barato que agregação no Firestore. Se algum nicho passar de alguns milhares de
mensagens por mês, vale trocar por contadores incrementais.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol

# O Brasil acabou com o horário de verão em 2019, então um offset fixo é
# correto e evita depender do tzdata dentro da imagem.
FUSO_BR = timezone(timedelta(hours=-3))


def inicio_do_mes(ano: int, mes: int) -> datetime:
    return datetime(ano, mes, 1, tzinfo=FUSO_BR)


def fim_do_mes(ano: int, mes: int) -> datetime:
    if mes == 12:
        return datetime(ano + 1, 1, 1, tzinfo=FUSO_BR)
    return datetime(ano, mes + 1, 1, tzinfo=FUSO_BR)


def mes_atual() -> tuple[int, int]:
    agora = datetime.now(FUSO_BR)
    return agora.year, agora.month


@dataclass
class Metricas:
    mensagens: int = 0
    pessoas: int = 0
    leads_quentes: int = 0
    links_enviados: int = 0
    escalacoes: int = 0
    tempo_medio_resposta_s: float | None = None

    @property
    def tempo_medio_texto(self) -> str:
        if self.tempo_medio_resposta_s is None:
            return "—"
        return f"{self.tempo_medio_resposta_s:.1f}s"


@dataclass
class Lead:
    telefone: str
    mensagens: int = 0
    primeiro_contato: datetime | None = None
    ultimo_contato: datetime | None = None
    sinais: set[str] = field(default_factory=set)
    link_enviado: bool = False
    escalado: bool = False

    @property
    def sinais_texto(self) -> str:
        return ", ".join(sorted(self.sinais)) or "—"


def _como_datetime(valor: Any) -> datetime | None:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return None


def calcular_metricas(docs: Iterable[dict[str, Any]]) -> Metricas:
    m = Metricas()
    telefones: set[str] = set()
    telefones_quentes: set[str] = set()
    duracoes: list[float] = []

    for doc in docs:
        m.mensagens += 1
        telefone = doc.get("telefone", "")
        if telefone:
            telefones.add(telefone)
        if doc.get("lead_quente"):
            # Conta pessoa, não mensagem: quem mandou cinco mensagens quentes
            # continua sendo um lead só.
            telefones_quentes.add(telefone)
        if doc.get("link_enviado"):
            m.links_enviados += 1
        if doc.get("escalado"):
            m.escalacoes += 1

        criado = _como_datetime(doc.get("criado_em"))
        respondido = _como_datetime(doc.get("respondido_em"))
        if criado and respondido and respondido >= criado:
            duracoes.append((respondido - criado).total_seconds())

    m.pessoas = len(telefones)
    m.leads_quentes = len(telefones_quentes)
    if duracoes:
        m.tempo_medio_resposta_s = sum(duracoes) / len(duracoes)
    return m


def agrupar_leads(docs: Iterable[dict[str, Any]]) -> list[Lead]:
    """Agrupa por telefone quem teve pelo menos uma mensagem marcada quente."""
    por_telefone: dict[str, Lead] = {}

    for doc in docs:
        if not doc.get("lead_quente"):
            continue
        telefone = doc.get("telefone", "")
        lead = por_telefone.setdefault(telefone, Lead(telefone=telefone))
        lead.mensagens += 1
        lead.sinais.update(doc.get("sinais_lead") or [])
        lead.link_enviado = lead.link_enviado or bool(doc.get("link_enviado"))
        lead.escalado = lead.escalado or bool(doc.get("escalado"))

        criado = _como_datetime(doc.get("criado_em"))
        if criado:
            if lead.primeiro_contato is None or criado < lead.primeiro_contato:
                lead.primeiro_contato = criado
            if lead.ultimo_contato is None or criado > lead.ultimo_contato:
                lead.ultimo_contato = criado

    return sorted(
        por_telefone.values(),
        key=lambda l: l.ultimo_contato or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


class RepoPainel(Protocol):
    async def docs_do_periodo(
        self, nicho: str, inicio: datetime, fim: datetime
    ) -> list[dict[str, Any]]: ...

    async def docs_do_telefone(
        self, nicho: str, telefone: str, limite: int = 200
    ) -> list[dict[str, Any]]: ...

    async def nichos_existentes(self) -> list[str]: ...


class RepoPainelMemoria:
    """Lê do MemoryStorage do agente. Usado em teste e local."""

    def __init__(self, storage) -> None:
        self.storage = storage

    def _todos(self) -> list[dict[str, Any]]:
        return list(self.storage._docs.values())

    async def docs_do_periodo(
        self, nicho: str, inicio: datetime, fim: datetime
    ) -> list[dict[str, Any]]:
        saida = []
        for doc in self._todos():
            if doc.get("nicho") != nicho:
                continue
            criado = _como_datetime(doc.get("criado_em"))
            if criado and inicio <= criado < fim:
                saida.append(doc)
        return saida

    async def docs_do_telefone(
        self, nicho: str, telefone: str, limite: int = 200
    ) -> list[dict[str, Any]]:
        docs = [
            d
            for d in self._todos()
            if d.get("nicho") == nicho and d.get("telefone") == telefone
        ]
        docs.sort(key=lambda d: _como_datetime(d.get("criado_em")) or datetime.min.replace(tzinfo=timezone.utc))
        return docs[-limite:]

    async def nichos_existentes(self) -> list[str]:
        return sorted({d.get("nicho", "") for d in self._todos() if d.get("nicho")})


class RepoPainelFirestore:
    def __init__(self, cfg, client=None) -> None:
        self.cfg = cfg
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self.cfg.gcp_project_id)
        return self._client

    def _col(self):
        return self._get_client().collection(self.cfg.firestore_collection)

    async def docs_do_periodo(
        self, nicho: str, inicio: datetime, fim: datetime
    ) -> list[dict[str, Any]]:
        from google.cloud import firestore

        consulta = (
            self._col()
            .where(filter=firestore.FieldFilter("nicho", "==", nicho))
            .where(filter=firestore.FieldFilter("criado_em", ">=", inicio))
            .where(filter=firestore.FieldFilter("criado_em", "<", fim))
        )
        return [doc.to_dict() async for doc in consulta.stream()]

    async def docs_do_telefone(
        self, nicho: str, telefone: str, limite: int = 200
    ) -> list[dict[str, Any]]:
        from google.cloud import firestore

        consulta = (
            self._col()
            .where(filter=firestore.FieldFilter("nicho", "==", nicho))
            .where(filter=firestore.FieldFilter("telefone", "==", telefone))
            .order_by("criado_em", direction=firestore.Query.DESCENDING)
            .limit(limite)
        )
        docs = [doc.to_dict() async for doc in consulta.stream()]
        docs.reverse()
        return docs

    async def nichos_existentes(self) -> list[str]:
        """Nichos conhecidos.

        Descobrir por varredura sairia caro, então a lista vem da
        configuração. Quando o segundo nicho subir, ele entra em NICHOS_PAINEL.
        """
        return sorted(self.cfg.nichos_painel)
