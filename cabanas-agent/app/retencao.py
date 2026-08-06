"""Retenção e anonimização das conversas (LGPD).

Segue a mesma regra que o DeskcommCRM já usa na operação do cliente:
**anonimização preferida sobre delete físico**. Apagar o documento levaria
junto a base do fechamento — e é justamente o número dos 10% que o Adriano
confere caso a caso.

O truque que faz os dois lados conviverem: o que é dado pessoal (telefone e o
texto da conversa) sai, e o que sustenta a métrica (nicho, intenção, lead
quente, sinais, datas, conferência) fica. O telefone vira um apelido derivado
por hash, sempre o mesmo para o mesmo número, então "pessoas atendidas" e
"leads quentes" continuam contando gente certo depois da anonimização.

Consequência prática: dá para ter retenção curta do conteúdo sem perder o
histórico de fechamento.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

# Prefixo do apelido, para ficar óbvio no painel que aquilo já foi anonimizado.
PREFIXO_ANONIMO = "anon-"


def apelido(telefone: str, sal: str) -> str:
    """Apelido estável para um telefone.

    O sal impede que alguém com a base em mãos teste os telefones um a um até
    achar o hash — sem ele, o espaço de números de celular do Brasil é pequeno
    o bastante para varrer.
    """
    digest = hashlib.sha256(f"{sal}|{telefone}".encode()).hexdigest()
    return f"{PREFIXO_ANONIMO}{digest[:12]}"


def ja_anonimizado(doc: dict[str, Any]) -> bool:
    return bool(doc.get("anonimizado_em")) or str(
        doc.get("telefone", "")
    ).startswith(PREFIXO_ANONIMO)


def campos_anonimizados(
    doc: dict[str, Any], sal: str, agora: datetime | None = None
) -> dict[str, Any]:
    """O que gravar por cima do documento para anonimizá-lo.

    Sai: telefone e o conteúdo das mensagens.
    Fica: nicho, intenção, lead quente, sinais, datas e tudo que o fechamento
    usa — nada disso identifica ninguém sozinho.
    """
    return {
        "telefone": apelido(str(doc.get("telefone", "")), sal),
        "texto": "",
        "resposta": "",
        "anonimizado_em": agora or datetime.now(timezone.utc),
    }


def corte(dias: int, agora: datetime | None = None) -> datetime:
    """Documentos criados antes desta data entram na anonimização."""
    return (agora or datetime.now(timezone.utc)) - timedelta(days=dias)


def elegiveis(
    docs: list[dict[str, Any]], dias: int, agora: datetime | None = None
) -> list[dict[str, Any]]:
    """Quais documentos já passaram do prazo e ainda não foram anonimizados."""
    if dias <= 0:
        return []
    limite = corte(dias, agora)
    saida = []
    for doc in docs:
        criado = doc.get("criado_em")
        if not isinstance(criado, datetime):
            continue
        if criado.tzinfo is None:
            criado = criado.replace(tzinfo=timezone.utc)
        if criado < limite and not ja_anonimizado(doc):
            saida.append(doc)
    return saida
