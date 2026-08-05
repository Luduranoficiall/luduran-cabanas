"""FastAPI + rotas. Ponto de entrada no Cloud Run."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .gemini_client import GeminiClient
from .storage import build_storage
from .webhook import router as webhook_router
from .whatsapp_client import WhatsAppClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    faltando = settings.faltando()
    if faltando:
        # Não derruba o processo: o Cloud Run precisa do /health respondendo
        # para considerar a revisão saudável. Mas fica gritando no log.
        logger.error("Variáveis de ambiente faltando: %s", ", ".join(faltando))

    if settings.cabanas_sem_link:
        # Aconteceu de listar uma cabana em CABANAS sem cadastrar a URL dela.
        # Ela fica fora do ar de propósito: link inventado vira link quebrado
        # na mão do cliente.
        logger.error(
            "Cabanas ativas sem link cadastrado, ficaram de fora: %s. "
            "Cadastre em CABANA_URLS (ex.: CABANA_URLS=3=https://...)",
            ", ".join(settings.cabanas_sem_link),
        )

    app.state.storage = build_storage(settings)
    app.state.gemini = GeminiClient(settings)
    app.state.whatsapp = WhatsAppClient(settings)
    logger.info(
        "Agente no ar — %s cabanas (%s), modelo %s",
        settings.total_cabanas,
        ", ".join(sorted(settings.cabanas)),
        settings.gemini_model,
    )
    try:
        yield
    finally:
        await app.state.whatsapp.aclose()


app = FastAPI(title="Agente Cabanas", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, object]:
    """Health check do Cloud Run.

    Reporta o que falta de configuração, mas sempre com 200: uma revisão que
    responde e avisa do problema é mais fácil de diagnosticar do que uma que
    nem sobe.
    """
    return {
        "status": "ok",
        "cabanas": sorted(settings.cabanas),
        "cabanas_sem_link": settings.cabanas_sem_link,
        "numero_atendimento": settings.whatsapp_phone_number,
        "modelo": settings.gemini_model,
        "config_faltando": settings.faltando(),
    }
