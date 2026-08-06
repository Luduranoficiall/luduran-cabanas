#!/usr/bin/env python3
"""Anonimiza conversas antigas, conforme o prazo de retenção da LGPD.

Roda em modo de conferência por padrão: mostra o que faria e **não grava
nada**. Só altera a base com `--aplicar`. Uma anonimização não tem volta, e o
script não vai fazer isso por acidente.

Uso:
    RETENCAO_DIAS=365 python cabanas-agent/scripts/anonimizar.py
    RETENCAO_DIAS=365 python cabanas-agent/scripts/anonimizar.py --aplicar

Sem `RETENCAO_DIAS` definido, não faz nada — o prazo é decisão de negócio, não
padrão de código.

> ⚠️ O prazo precisa ser **maior que o ciclo de fechamento**. O conteúdo das
> mensagens some na anonimização, e é ele que responde "por que este lead foi
> marcado como quente?" quando o Adriano confere caso a caso. As métricas
> continuam de pé (ver app/retencao.py), mas o texto não volta.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.retencao import campos_anonimizados, corte, elegiveis  # noqa: E402


async def main() -> int:
    dias = settings.retencao_dias
    if dias <= 0:
        print(
            "RETENCAO_DIAS não definido — nada a fazer.\n"
            "O prazo é decisão de negócio. Ver a seção de retenção em PAINEL.md.",
            file=sys.stderr,
        )
        return 1

    if not settings.retencao_sal:
        print(
            "RETENCAO_SAL não definido. Sem ele, o apelido do telefone vira\n"
            "um hash adivinhável por força bruta. Gere um e guarde no Secret\n"
            "Manager: openssl rand -hex 32",
            file=sys.stderr,
        )
        return 1

    aplicar = "--aplicar" in sys.argv

    from google.cloud import firestore

    cliente = firestore.AsyncClient(project=settings.gcp_project_id)
    colecao = cliente.collection(settings.firestore_collection)

    limite = corte(dias)
    print(f"Prazo: {dias} dias — anonimizando conversas anteriores a "
          f"{limite.strftime('%d/%m/%Y')}")
    print("Modo: APLICAR (grava)" if aplicar else "Modo: conferência (não grava)")
    print()

    consulta = colecao.where(
        filter=firestore.FieldFilter("criado_em", "<", limite)
    )
    docs = [(d.id, d.to_dict()) async for d in consulta.stream()]
    alvos = elegiveis([d for _, d in docs], dias)

    if not alvos:
        print("Nenhuma conversa passou do prazo. Nada a fazer.")
        return 0

    por_id = {id_: doc for id_, doc in docs}
    telefones = {d.get("telefone") for d in alvos}
    print(f"{len(alvos)} mensagem(ns) de {len(telefones)} telefone(s) elegíveis.")

    if not aplicar:
        exemplo = alvos[0]
        novo = campos_anonimizados(exemplo, settings.retencao_sal)
        print("\nExemplo do que aconteceria com a primeira:")
        print(f"  telefone : {exemplo.get('telefone')} → {novo['telefone']}")
        print(f"  texto    : {(exemplo.get('texto') or '')[:44]!r} → ''")
        print(f"  mantém   : nicho, intencao, lead_quente, sinais_lead, datas")
        print("\nPara gravar de verdade, rode de novo com --aplicar")
        return 0

    gravadas = 0
    for id_, doc in por_id.items():
        if doc not in alvos:
            continue
        await colecao.document(id_).update(
            campos_anonimizados(doc, settings.retencao_sal)
        )
        gravadas += 1

    print(f"{gravadas} mensagem(ns) anonimizada(s). Isso não tem volta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
