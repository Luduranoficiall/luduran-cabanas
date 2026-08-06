#!/usr/bin/env python3
"""Confere as credenciais ANTES do deploy.

Cada credencial errada custa um ciclo de deploy inteiro para descobrir, e o
erro raramente diz o que está errado — a Meta responde 400 tanto para token
expirado quanto para Phone number ID trocado pelo telefone. Este script bate
em cada serviço de verdade e diz, em segundos, qual está errada.

Uso:
    cd cabanas-agent
    set -a && source .env && set +a
    python scripts/pre_deploy.py

Sai com 0 se estiver tudo pronto para o passo 10 do DEPLOY.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, so_digitos  # noqa: E402

OK, FALHA, AVISO = "  ok ", " ERRO", " avis"


def linha(marca: str, titulo: str, detalhe: str = "") -> None:
    print(f"[{marca}] {titulo}")
    if detalhe:
        for parte in detalhe.splitlines():
            print(f"         {parte}")


def checar_config(cfg: Settings) -> bool:
    faltando = cfg.faltando()
    if faltando:
        linha(FALHA, "Variáveis obrigatórias", "faltando: " + ", ".join(faltando))
        return False
    linha(OK, "Variáveis obrigatórias")
    return True


def checar_numeros(cfg: Settings) -> bool:
    tudo_bem = True

    if not cfg.whatsapp_phone_number_id.isdigit():
        linha(
            FALHA,
            "WHATSAPP_PHONE_NUMBER_ID",
            f"{cfg.whatsapp_phone_number_id!r} não é numérico.\n"
            "É o ID da Meta (~15 dígitos), não o telefone. Ver passo 5c.",
        )
        tudo_bem = False
    elif so_digitos(cfg.whatsapp_phone_number) == cfg.whatsapp_phone_number_id:
        linha(
            FALHA,
            "WHATSAPP_PHONE_NUMBER_ID",
            "está com o TELEFONE no lugar do ID. Todo envio falharia com 400.",
        )
        tudo_bem = False
    else:
        linha(OK, "WHATSAPP_PHONE_NUMBER_ID", f"{cfg.whatsapp_phone_number_id}")

    if cfg.escalacao_para_si_mesmo:
        linha(
            FALHA,
            "ESCALATION_NUMBER",
            "é o mesmo número do sistema. A Cloud API recusa mensagem de um\n"
            "número para ele mesmo — o aviso nunca chegaria.",
        )
        tudo_bem = False
    elif not cfg.escalation_number:
        linha(AVISO, "ESCALATION_NUMBER", "vazio — escalação só aparece no painel.")
    else:
        linha(OK, "ESCALATION_NUMBER", f"+{cfg.escalation_number}")

    if not cfg.escalation_template:
        linha(
            AVISO,
            "ESCALATION_TEMPLATE",
            "vazio. O aviso à secretária será recusado (erro 131047), porque a\n"
            "janela de 24h dela está fechada. Não bloqueia o deploy — a fonte\n"
            "passa a ser /painel/escalacoes. Ver passo 6.",
        )
    else:
        linha(OK, "ESCALATION_TEMPLATE", cfg.escalation_template)

    return tudo_bem


def checar_cabanas(cfg: Settings) -> bool:
    if cfg.cabanas_sem_link:
        linha(
            FALHA,
            "Cabanas",
            f"sem link cadastrado, ficariam fora: {', '.join(cfg.cabanas_sem_link)}",
        )
        return False
    linha(OK, "Cabanas", f"{cfg.total_cabanas} no ar: {', '.join(sorted(cfg.cabanas))}")
    return True


def checar_gemini(cfg: Settings) -> bool:
    try:
        from app.gemini_client import GeminiClient

        resposta = GeminiClient(cfg).responder("responda apenas: ok")
    except Exception as exc:  # noqa: BLE001 — qualquer falha aqui é informativa
        linha(FALHA, "Gemini", f"{type(exc).__name__}: {exc}")
        return False
    linha(OK, "Gemini", f"{cfg.gemini_model} respondeu: {resposta[:40]!r}")
    return True


def checar_meta(cfg: Settings) -> bool:
    """Lê o próprio número na Graph API — valida token e ID de uma vez."""
    import httpx

    url = (
        f"https://graph.facebook.com/{cfg.graph_api_version}/"
        f"{cfg.whatsapp_phone_number_id}"
    )
    try:
        resposta = httpx.get(
            url,
            params={"fields": "display_phone_number,verified_name,quality_rating"},
            headers={"Authorization": f"Bearer {cfg.whatsapp_token}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        linha(FALHA, "Meta Cloud API", f"rede: {exc}")
        return False

    if resposta.status_code >= 400:
        erro = {}
        try:
            erro = resposta.json().get("error", {})
        except ValueError:
            pass
        dica = {
            190: "token inválido ou expirado — usou o temporário de 24h?",
            100: "Phone number ID errado, ou o token não tem acesso a ele.",
        }.get(erro.get("code"), erro.get("message", resposta.text[:120]))
        linha(FALHA, "Meta Cloud API", f"{resposta.status_code}: {dica}")
        return False

    dados = resposta.json()
    numero = dados.get("display_phone_number", "?")
    linha(
        OK,
        "Meta Cloud API",
        f"{numero} · {dados.get('verified_name', '?')} · "
        f"qualidade {dados.get('quality_rating', '?')}",
    )

    if so_digitos(numero) != so_digitos(cfg.whatsapp_phone_number):
        linha(
            AVISO,
            "Número do sistema",
            f"a Meta diz {numero}, mas WHATSAPP_PHONE_NUMBER é "
            f"{cfg.whatsapp_phone_number}. Confira qual está certo.",
        )
    return True


def checar_firestore(cfg: Settings) -> bool:
    try:
        from google.cloud import firestore

        cliente = firestore.Client(project=cfg.gcp_project_id)
        # Uma leitura barata que confirma banco criado + permissão.
        next(iter(cliente.collection(cfg.firestore_collection).limit(1).stream()), None)
    except Exception as exc:  # noqa: BLE001
        linha(
            FALHA,
            "Firestore",
            f"{type(exc).__name__}: {exc}\n"
            "Banco criado? (passo 2) Conta de serviço com datastore.user? (passo 8)",
        )
        return False
    linha(OK, "Firestore", f"{cfg.gcp_project_id}/{cfg.firestore_collection}")
    return True


def main() -> int:
    cfg = Settings()
    print("Conferência pré-deploy — Agente Cabanas\n")

    resultados = [
        checar_config(cfg),
        checar_numeros(cfg),
        checar_cabanas(cfg),
    ]

    if resultados[0]:  # sem credenciais não adianta bater nos serviços
        resultados += [checar_gemini(cfg), checar_meta(cfg), checar_firestore(cfg)]
    else:
        print("\nPulei os testes de rede — preencha as variáveis primeiro.")

    print()
    if all(resultados):
        print("Tudo pronto. Pode rodar o passo 10 do DEPLOY.md.")
        return 0
    print("Corrija os itens marcados com ERRO antes do deploy.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
