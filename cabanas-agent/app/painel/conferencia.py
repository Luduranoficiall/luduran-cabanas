"""Conferência do fechamento: quais leads viraram reserva de fato.

Quem marca é a Camily, no painel. O que ela grava aqui é o que sustenta a
conversa dos 10% com o Adriano, então duas coisas importam mais que o resto:

1. **Dinheiro em centavos, inteiro.** Somar float dá diferença de centavo, e
   diferença de centavo num acerto de comissão vira discussão.
2. **Toda alteração fica registrada** — quem marcou, quando, e qual era o
   valor antes. O Adriano vai conferir caso a caso; sem histórico, a palavra de
   um contra a do outro.

A chave de uma conferência é (nicho, telefone, ano-mês): no fechamento, um lead
é uma pessoa dentro de um mês.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class Conferencia:
    confirmado: bool = False
    # None significa "confirmada, mas ninguém informou quanto foi". Não é zero:
    # zero seria uma reserva de graça, e isso mente no total.
    valor_centavos: int | None = None
    observacao: str = ""
    conferido_por: str = ""
    conferido_em: datetime | None = None

    @property
    def valor_texto(self) -> str:
        return formatar_reais(self.valor_centavos)


def chave(nicho: str, telefone: str, ano: int, mes: int) -> str:
    return f"{nicho}|{telefone}|{ano}-{mes:02d}"


def parse_reais(texto: str | None) -> int | None:
    """Converte "1.234,56", "1234.56" ou "150" em centavos.

    Devolve None para vazio — o painel precisa distinguir "não informado" de
    "zero".
    """
    if texto is None:
        return None
    limpo = texto.strip().replace("R$", "").replace(" ", "")
    if not limpo:
        return None

    # Formato brasileiro ("1.234,56"): ponto é milhar, vírgula é decimal.
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", limpo):
        raise ValueError(f"valor inválido: {texto!r}")

    centavos = round(float(limpo) * 100)
    if centavos < 0:
        raise ValueError("valor não pode ser negativo")
    return centavos


def formatar_reais(centavos: int | None) -> str:
    if centavos is None:
        return "—"
    inteiro, resto = divmod(centavos, 100)
    # O separador de milhar é trocado antes de a vírgula decimal entrar —
    # trocar na string inteira comeria a vírgula junto.
    milhar = f"{inteiro:,}".replace(",", ".")
    return f"R$ {milhar},{resto:02d}"


class RepoConferencia(Protocol):
    async def carregar(
        self, nicho: str, ano: int, mes: int
    ) -> dict[str, Conferencia]: ...

    async def gravar(
        self, nicho: str, telefone: str, ano: int, mes: int, conferencia: Conferencia
    ) -> None: ...


class RepoConferenciaMemoria:
    def __init__(self) -> None:
        self._dados: dict[str, Conferencia] = {}

    async def carregar(self, nicho: str, ano: int, mes: int) -> dict[str, Conferencia]:
        prefixo = f"{nicho}|"
        sufixo = f"|{ano}-{mes:02d}"
        return {
            k.split("|")[1]: v
            for k, v in self._dados.items()
            if k.startswith(prefixo) and k.endswith(sufixo)
        }

    async def gravar(
        self, nicho: str, telefone: str, ano: int, mes: int, conferencia: Conferencia
    ) -> None:
        self._dados[chave(nicho, telefone, ano, mes)] = conferencia


class RepoConferenciaFirestore:
    COLECAO = "painel_conferencias"

    def __init__(self, cfg, client=None) -> None:
        self.cfg = cfg
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self.cfg.gcp_project_id)
        return self._client

    async def carregar(self, nicho: str, ano: int, mes: int) -> dict[str, Conferencia]:
        from google.cloud import firestore

        consulta = (
            self._get_client()
            .collection(self.COLECAO)
            .where(filter=firestore.FieldFilter("nicho", "==", nicho))
            .where(filter=firestore.FieldFilter("competencia", "==", f"{ano}-{mes:02d}"))
        )
        saida: dict[str, Conferencia] = {}
        async for doc in consulta.stream():
            d = doc.to_dict() or {}
            saida[d.get("telefone", "")] = _do_dict(d)
        return saida

    async def gravar(
        self, nicho: str, telefone: str, ano: int, mes: int, conferencia: Conferencia
    ) -> None:
        await self._get_client().collection(self.COLECAO).document(
            chave(nicho, telefone, ano, mes)
        ).set(
            {
                "nicho": nicho,
                "telefone": telefone,
                "competencia": f"{ano}-{mes:02d}",
                "confirmado": conferencia.confirmado,
                "valor_centavos": conferencia.valor_centavos,
                "observacao": conferencia.observacao,
                "conferido_por": conferencia.conferido_por,
                "conferido_em": conferencia.conferido_em,
            }
        )


def _do_dict(d: dict[str, Any]) -> Conferencia:
    quando = d.get("conferido_em")
    if isinstance(quando, datetime) and quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return Conferencia(
        confirmado=bool(d.get("confirmado")),
        valor_centavos=d.get("valor_centavos"),
        observacao=d.get("observacao", "") or "",
        conferido_por=d.get("conferido_por", "") or "",
        conferido_em=quando if isinstance(quando, datetime) else None,
    )


@dataclass
class Totais:
    leads_quentes: int = 0
    confirmadas: int = 0
    confirmadas_sem_valor: int = 0
    valor_total_centavos: int = 0
    percentual: float = 10.0

    @property
    def comissao_centavos(self) -> int:
        # Arredonda uma vez, no fim, sobre a soma — arredondar por linha
        # acumularia diferença.
        return round(self.valor_total_centavos * self.percentual / 100)

    @property
    def valor_total_texto(self) -> str:
        return formatar_reais(self.valor_total_centavos)

    @property
    def comissao_texto(self) -> str:
        return formatar_reais(self.comissao_centavos)

    @property
    def total_confiavel(self) -> bool:
        """False quando há reserva confirmada sem valor informado.

        Nesse caso a comissão está subestimada, e a tela precisa dizer isso em
        vez de mostrar um número redondo que não fecha.
        """
        return self.confirmadas_sem_valor == 0


def calcular_totais(
    leads: list, conferencias: dict[str, Conferencia], percentual: float = 10.0
) -> Totais:
    totais = Totais(leads_quentes=len(leads), percentual=percentual)
    for lead in leads:
        conf = conferencias.get(lead.telefone)
        if conf is None or not conf.confirmado:
            continue
        totais.confirmadas += 1
        if conf.valor_centavos is None:
            totais.confirmadas_sem_valor += 1
        else:
            totais.valor_total_centavos += conf.valor_centavos
    return totais
