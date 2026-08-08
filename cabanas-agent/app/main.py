"""FastAPI + rotas. Ponto de entrada no Cloud Run."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import settings
from .gemini_client import GeminiClient
from .painel.auth import ControleTentativas, RepoAuthFirestore, RepoAuthMemoria
from .painel.conferencia import RepoConferenciaFirestore, RepoConferenciaMemoria
from .painel.repositorio import RepoPainelFirestore, RepoPainelMemoria
from .painel.rotas import router as painel_router
from .storage import MemoryStorage, build_storage
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

    if settings.escalacao_para_si_mesmo:
        logger.error(
            "ESCALATION_NUMBER (%s) é o mesmo número do atendimento. A Cloud "
            "API não entrega mensagem de um número para ele mesmo: o aviso de "
            "escalação NÃO será enviado. As escalações continuam registradas e "
            "aparecem em /painel/escalacoes.",
            settings.escalation_number,
        )

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

    # Painel. Sem projeto GCP o agente já roda em memória; o painel acompanha,
    # lendo do mesmo storage, para dar para levantar tudo local.
    if isinstance(app.state.storage, MemoryStorage):
        app.state.repo_painel = RepoPainelMemoria(app.state.storage)
        app.state.repo_auth = RepoAuthMemoria()
        app.state.repo_conferencia = RepoConferenciaMemoria()
    else:
        app.state.repo_painel = RepoPainelFirestore(settings)
        app.state.repo_auth = RepoAuthFirestore(settings)
        app.state.repo_conferencia = RepoConferenciaFirestore(settings)
    app.state.tentativas_login = ControleTentativas()

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
app.include_router(painel_router)


DEMO = Path(__file__).parent / "static" / "demo.html"


@app.get("/", response_class=HTMLResponse)
async def raiz() -> HTMLResponse:
    """Demonstração aberta, sem senha.

    O cliente aprova o sistema antes de existir credencial da Meta, e pedir
    login para isso emperra a aprovação. A página é autossuficiente e usa
    conversas inventadas — não lê nem grava nada no Firestore, então não há
    dado pessoal exposto.
    """
    if not settings.demo_publica:
        return RedirectResponse("/painel/", status_code=303)
    return HTMLResponse(DEMO.read_text(encoding="utf-8"))


@app.get("/demo", response_class=HTMLResponse)
async def demo() -> HTMLResponse:
    """Mesmo conteúdo de "/", num endereço que continua valendo depois que a
    raiz passar a levar ao painel."""
    return HTMLResponse(DEMO.read_text(encoding="utf-8"))


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
        "aviso_escalacao_por_whatsapp": (
            "quebrado: mesmo número do atendimento"
            if settings.escalacao_para_si_mesmo
            else "ok"
        ),
        "modelo": settings.gemini_model,
        "config_faltando": settings.faltando(),
    }
