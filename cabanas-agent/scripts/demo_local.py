#!/usr/bin/env python3
"""Sobe o painel na sua máquina com dados de exemplo, sem tocar em nada real.

Serve para mostrar o painel ao cliente antes do sistema estar no ar: ele vê as
telas de verdade — o mesmo código que vai rodar em produção — só que lendo de
memória em vez do Firestore. Nada é gravado, nada sai da máquina, e nenhum
telefone real aparece.

    python scripts/demo_local.py
    # abre em http://localhost:8080/painel/login

    lucas@luduran.com    / demo1234   (admin, vê todos os nichos)
    camily@exemplo.com   / demo1234   (operadora, confere o fechamento)
    adriano@exemplo.com  / demo1234   (leitor, só enxerga)

As conversas são inventadas, mas com a cara do que a operação gera: perguntas
de preço, pedidos de data, um pedido de desconto que vira escalação.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Sem projeto GCP, o app usa storage em memória — é o que queremos aqui.
os.environ.setdefault("GCP_PROJECT_ID", "")
os.environ.setdefault("NICHOS_PAINEL", "cabanas")
os.environ.setdefault("COOKIE_SEGURO", "0")  # http://localhost, sem TLS
os.environ.setdefault("GEMINI_API_KEY", "demo")
os.environ.setdefault("WHATSAPP_TOKEN", "demo")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "demo")
os.environ.setdefault("WHATSAPP_APP_SECRET", "demo")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456789012345")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER", "+55 54 99910-3545")
os.environ.setdefault("ESCALATION_NUMBER", "5554984487198")

from app.main import app  # noqa: E402
from app.painel import auth  # noqa: E402
from app.painel.repositorio import FUSO_BR, mes_atual  # noqa: E402

SENHA = "demo1234"
ANO, MES = mes_atual()


def _quando(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(ANO, MES, dia, hora, minuto, tzinfo=FUSO_BR)


def _conversa(
    id_doc: str,
    telefone: str,
    dia: int,
    hora: int,
    texto: str,
    resposta: str,
    *,
    intencao: str = "preco",
    lead_quente: bool = False,
    sinais: tuple[str, ...] = (),
    link: bool = False,
    escalado: bool = False,
    segundos: int = 3,
) -> tuple[str, dict]:
    criado = _quando(dia, hora)
    return id_doc, {
        "nicho": "cabanas",
        "telefone": telefone,
        "texto": texto,
        "resposta": resposta,
        "intencao": intencao,
        "lead_quente": lead_quente,
        "sinais_lead": list(sinais),
        "link_enviado": link,
        "escalado": escalado,
        "criado_em": criado,
        "respondido_em": criado + timedelta(seconds=segundos),
    }


# Telefones de exemplo, na faixa 99999-000X: não são de ninguém.
ANA, BRUNO, CARLA, DIEGO, ELISA = (f"555499999000{n}" for n in range(1, 6))

CONVERSAS = dict(
    [
        _conversa("d1", ANA, 3, 9, "Oi, quanto custa a diária?",
                  "Olá! A diária é R$150,00. Dá uma olhada na cabana 1: ...",
                  link=True),
        _conversa("d2", ANA, 3, 9, "Tem vaga pro dia 14? Somos 4 pessoas",
                  "A disponibilidade real aparece no link do Airbnb...",
                  intencao="disponibilidade", lead_quente=True,
                  sinais=("data_especifica", "numero_pessoas"), link=True, segundos=4),
        _conversa("d3", BRUNO, 5, 20, "boa noite, aceita pet?",
                  "Boa noite! Sobre pet, a Camily te confirma...",
                  intencao="duvida", segundos=2),
        _conversa("d4", CARLA, 8, 14, "quero reservar pro fim de semana do dia 21",
                  "Que bom! A reserva é feita direto no Airbnb...",
                  intencao="reserva", lead_quente=True,
                  sinais=("pediu_reserva", "data_especifica"), link=True, segundos=3),
        _conversa("d5", DIEGO, 11, 10, "faz por 100 a diária?",
                  "Sobre valores e condições, quem fala é a nossa equipe. "
                  "Já avisei a Camily, ela te retorna por aqui.",
                  intencao="desconto", escalado=True, segundos=1),
        _conversa("d6", ELISA, 15, 16, "oi! cabana pra 2 pessoas no dia 28, tem?",
                  "Oi! Temos cabanas para casal...",
                  intencao="disponibilidade", lead_quente=True,
                  sinais=("data_especifica", "numero_pessoas"), link=True, segundos=5),
        _conversa("d7", ELISA, 15, 16, "e tem café da manhã?",
                  "Sobre o que está incluso, o anúncio do Airbnb detalha...",
                  intencao="duvida", segundos=3),
        _conversa("d8", BRUNO, 18, 11, "consigo pro feriadão? somos 6",
                  "A disponibilidade do feriado aparece no link...",
                  intencao="disponibilidade", lead_quente=True,
                  sinais=("data_especifica", "numero_pessoas"), link=True, segundos=4),
    ]
)

USUARIOS = {
    "lucas@luduran.com": auth.Usuario(
        "lucas@luduran.com", auth.gerar_hash(SENHA), auth.PAPEL_ADMIN
    ),
    "camily@exemplo.com": auth.Usuario(
        "camily@exemplo.com", auth.gerar_hash(SENHA), auth.PAPEL_OPERADOR,
        nichos=("cabanas",),
    ),
    "adriano@exemplo.com": auth.Usuario(
        "adriano@exemplo.com", auth.gerar_hash(SENHA), auth.PAPEL_LEITOR,
        nichos=("cabanas",),
    ),
}


# O app usa `lifespan=`, e nesse modo o Starlette ignora handlers de
# `on_event("startup")` — daí embrulhar o lifespan original em vez de
# registrar outro: os repositórios em memória só existem depois que ele roda.
_lifespan_original = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_com_dados(app_):
    async with _lifespan_original(app_):
        app_.state.storage._docs = dict(CONVERSAS)
        app_.state.repo_auth.usuarios = dict(USUARIOS)
        yield


app.router.lifespan_context = _lifespan_com_dados


def main() -> int:
    import uvicorn

    porta = int(os.environ.get("PORT", "8080"))
    print(f"""
  Painel de demonstração — dados de exemplo, nada real

    http://localhost:{porta}/painel/login

    lucas@luduran.com    / {SENHA}   admin, vê todos os nichos
    camily@exemplo.com   / {SENHA}   operadora, confere o fechamento
    adriano@exemplo.com  / {SENHA}   leitor, só enxerga

  {len(CONVERSAS)} conversas em {MES:02d}/{ANO}, 4 leads quentes, 1 escalação.
  Ctrl+C para parar.
""")
    uvicorn.run(app, host="0.0.0.0", port=porta, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
