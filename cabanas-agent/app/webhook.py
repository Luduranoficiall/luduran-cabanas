"""Webhook da Meta: verificação (GET) e recebimento de mensagens (POST)."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response

from .config import Settings, settings
from .gemini_client import GeminiClient, GeminiIndisponivel
from .intents import (
    INTENCAO_ESCALACAO,
    detectar_intencao,
    motivo_escalacao,
    sinais_de_reserva,
)
from .prompts import RESPOSTA_ANTILOOP, RESPOSTA_ESCALACAO, RESPOSTA_FALLBACK
from .storage import Storage
from .whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)
router = APIRouter()

# Enviada quando chega áudio, imagem ou figurinha. O agente só lê texto.
RESPOSTA_NAO_TEXTO = (
    "Oi! Por aqui eu consigo ler apenas mensagens de texto. 😊\n\n"
    "Pode me escrever o que você precisa saber sobre as cabanas?"
)


def assinatura_valida(corpo: bytes, cabecalho: str | None, app_secret: str) -> bool:
    """Confere o X-Hub-Signature-256 que a Meta manda em cada POST.

    Sem essa checagem, qualquer um que descubra a URL do Cloud Run consegue
    fazer o agente responder e sujar o histórico do painel.
    """
    if not app_secret:
        # Sem segredo configurado não há o que conferir. Fica registrado no log
        # porque isso não pode ir para produção assim.
        logger.warning("WHATSAPP_APP_SECRET não configurado — webhook sem verificação")
        return True
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


def extrair_mensagens(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Achata o payload da Meta em uma lista de mensagens.

    O formato é aninhado (entry → changes → value → messages) e todos os
    níveis são opcionais. Notificações de status de entrega chegam pelo mesmo
    webhook, sem a chave `messages`, e são ignoradas aqui.
    """
    mensagens: list[dict[str, Any]] = []
    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            valor = mudanca.get("value") or {}
            for mensagem in valor.get("messages") or []:
                mensagens.append(mensagem)
    return mensagens


def texto_da_mensagem(mensagem: dict[str, Any]) -> str | None:
    """Texto da mensagem, ou None se for de um tipo que não sabemos ler."""
    if mensagem.get("type") == "text":
        return (mensagem.get("text") or {}).get("body")
    return None


async def processar_mensagem(
    mensagem: dict[str, Any],
    *,
    storage: Storage,
    gemini: GeminiClient,
    whatsapp: WhatsAppClient,
    cfg: Settings | None = None,
) -> None:
    """Trata uma mensagem de ponta a ponta: classifica, responde e registra."""
    cfg = cfg or settings
    message_id = mensagem.get("id")
    telefone = mensagem.get("from")
    if not message_id or not telefone:
        logger.warning("Mensagem sem id ou remetente, ignorando: %s", mensagem)
        return

    texto = texto_da_mensagem(mensagem)

    if texto is None:
        # Tipo não suportado: responde, mas não gasta chamada de modelo.
        if await storage.reservar_mensagem(
            message_id,
            telefone,
            f"[{mensagem.get('type')}]",
            "nao_texto",
            nicho=cfg.nicho,
        ):
            await whatsapp.enviar_texto(telefone, RESPOSTA_NAO_TEXTO)
            await storage.registrar_resposta(
                message_id, RESPOSTA_NAO_TEXTO, escalado=False, link_enviado=False
            )
        return

    intencao = detectar_intencao(texto)
    sinais = sinais_de_reserva(texto)

    # A reserva é atômica: se voltar False, essa mensagem já foi tratada por
    # uma entrega anterior do mesmo webhook.
    if not await storage.reservar_mensagem(
        message_id,
        telefone,
        texto,
        intencao,
        nicho=cfg.nicho,
        lead_quente=bool(sinais),
        sinais_lead=sinais,
    ):
        return

    if sinais:
        logger.info("Lead quente: %s (sinais: %s)", telefone, ", ".join(sinais))

    await whatsapp.marcar_como_lida(message_id)

    # Anti-loop antes de qualquer coisa cara: uma enxurrada não pode virar
    # uma enxurrada de chamadas ao Gemini.
    if await _enxurrada(storage, telefone, message_id, cfg, whatsapp):
        return

    motivo = motivo_escalacao(texto)
    if motivo:
        resposta = RESPOSTA_ESCALACAO
        escalado = True
        logger.info("Escalando conversa com %s (motivo: %s)", telefone, motivo)
        await _avisar_equipe(whatsapp, cfg, telefone, texto, motivo)
    else:
        escalado = False
        historico = await storage.historico(
            telefone,
            cfg.history_limit,
            nicho=cfg.nicho,
            desde=datetime.now(timezone.utc)
            - timedelta(minutes=cfg.history_janela_min),
            # Esta mensagem já foi gravada acima; sem excluí-la, o modelo
            # receberia o mesmo texto duas vezes.
            excluir_id=message_id,
        )
        try:
            resposta = gemini.responder(texto, historico)
        except GeminiIndisponivel:
            # A pessoa está esperando: melhor a resposta fixa, que está correta,
            # do que deixar no vácuo.
            resposta = RESPOSTA_FALLBACK.format(
                diaria=cfg.diaria, link=_primeiro_link(cfg)
            )

    await whatsapp.enviar_texto(telefone, resposta)
    await storage.registrar_resposta(
        message_id,
        resposta,
        escalado=escalado,
        link_enviado="airbnb.com.br" in resposta,
    )


async def _enxurrada(
    storage: Storage,
    telefone: str,
    message_id: str,
    cfg: Settings,
    whatsapp: WhatsAppClient,
) -> bool:
    """Trava o atendimento quando o volume passa do razoável.

    Acima de `antiloop_mensagens` na janela, o agente para de responder e a
    conversa é escalada. Vale contra bot, contra teste malicioso e contra
    queimar cota do Gemini à toa.

    O aviso sai **uma vez só**: quem está inundando o número não precisa
    receber a mesma mensagem quinze vezes. As seguintes ficam registradas em
    silêncio, e o `bloqueado` no documento é o que marca que o aviso já foi.
    """
    if cfg.antiloop_mensagens <= 0:
        return False

    desde = datetime.now(timezone.utc) - timedelta(minutes=cfg.antiloop_janela_min)
    # Teto de leitura: passar do limite já basta, não interessa por quanto.
    recentes = await storage.recentes(
        telefone, nicho=cfg.nicho, desde=desde, teto=cfg.antiloop_mensagens * 2
    )
    if len(recentes) <= cfg.antiloop_mensagens:
        return False

    ja_avisado = any(d.get("bloqueado") for d in recentes)
    logger.warning(
        "Anti-loop: %s mandou %s mensagens em %s min — atendimento pausado%s",
        telefone,
        len(recentes),
        cfg.antiloop_janela_min,
        "" if ja_avisado else ", avisando e escalando",
    )

    resposta = "" if ja_avisado else RESPOSTA_ANTILOOP
    if not ja_avisado:
        await whatsapp.enviar_texto(telefone, resposta)
        await _avisar_equipe(whatsapp, cfg, telefone, "(volume alto)", "anti_loop")

    await storage.registrar_resposta(
        message_id,
        resposta,
        escalado=True,
        link_enviado=False,
        bloqueado=True,
    )
    return True


def _primeiro_link(cfg: Settings) -> str:
    if not cfg.cabanas:
        return "https://airbnb.com.br"
    return cfg.cabanas[sorted(cfg.cabanas)[0]]


async def _avisar_equipe(
    whatsapp: WhatsAppClient,
    cfg: Settings,
    telefone: str,
    texto: str,
    motivo: str,
) -> None:
    """Manda para a Camile o resumo da conversa que precisa de humano."""
    if not cfg.escalation_number:
        logger.warning("ESCALATION_NUMBER não configurado — escalação só no painel")
        return
    if cfg.escalacao_para_si_mesmo:
        # A Cloud API recusa mensagem de um número para ele mesmo. Tentar só
        # geraria erro no log; a escalação já está gravada e aparece no painel.
        logger.error(
            "ESCALATION_NUMBER é o próprio número do atendimento (%s) — "
            "o aviso não pode ser enviado por WhatsApp. Conversa com %s "
            "precisa de humano (motivo: %s). Veja /painel/escalacoes.",
            cfg.escalation_number,
            telefone,
            motivo,
        )
        return
    aviso = (
        f"🔔 Atendimento precisa de você ({motivo})\n\n"
        f"Cliente: +{telefone}\n"
        f'Mensagem: "{texto}"'
    )
    await whatsapp.enviar_texto(cfg.escalation_number, aviso)


@router.get("/webhook")
async def verificar(request: Request) -> Response:
    """Handshake que a Meta faz uma vez, ao cadastrar a URL do webhook."""
    params = request.query_params
    modo = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if modo == "subscribe" and token == settings.whatsapp_verify_token:
        # A Meta espera o challenge cru, como text/plain.
        return Response(content=challenge, media_type="text/plain")
    logger.warning("Verificação de webhook recusada (modo=%s)", modo)
    return Response(content="forbidden", status_code=403)


@router.post("/webhook")
async def receber(request: Request, tarefas: BackgroundTasks) -> Response:
    """Recebe as mensagens.

    Responde 200 na hora e processa em background: a Meta reenvia o webhook se
    não receber resposta em poucos segundos, e chamar Gemini + Firestore antes
    de responder colocaria o agente em risco de responder duas vezes.
    """
    corpo = await request.body()

    if not assinatura_valida(
        corpo, request.headers.get("X-Hub-Signature-256"), settings.whatsapp_app_secret
    ):
        logger.warning("Assinatura inválida no webhook")
        return Response(content="invalid signature", status_code=403)

    try:
        payload = await request.json()
    except ValueError:
        return Response(content="invalid json", status_code=400)

    estado = request.app.state
    for mensagem in extrair_mensagens(payload):
        tarefas.add_task(
            processar_mensagem,
            mensagem,
            storage=estado.storage,
            gemini=estado.gemini,
            whatsapp=estado.whatsapp,
        )

    return Response(content="EVENT_RECEIVED", status_code=200)
