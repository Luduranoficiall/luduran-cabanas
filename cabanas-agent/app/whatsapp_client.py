"""Envio de mensagens pela WhatsApp Cloud API (Meta Graph API)."""

from __future__ import annotations

import logging

import httpx

from .config import Settings, settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self, cfg: Settings | None = None, http: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg or settings
        self._http = http
        self._proprio = http is None

    @property
    def base_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.cfg.graph_api_version}"
            f"/{self.cfg.whatsapp_phone_number_id}/messages"
        )

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._proprio:
            await self._http.aclose()
            self._http = None

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        """Envia uma mensagem de texto. Retorna True se a Meta aceitou."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefone,
            "type": "text",
            # preview_url=True faz o WhatsApp montar o card do Airbnb no link,
            # que é o que faz a pessoa clicar.
            "text": {"preview_url": True, "body": texto},
        }
        headers = {"Authorization": f"Bearer {self.cfg.whatsapp_token}"}

        try:
            http = await self._get_http()
            resposta = await http.post(self.base_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("Falha de rede ao enviar para %s: %s", telefone, exc)
            return False

        if resposta.status_code >= 400:
            # O corpo do erro da Meta é a única forma de saber se é token
            # expirado, janela de 24h fechada ou número inválido.
            logger.error(
                "Meta recusou envio para %s (%s): %s",
                telefone,
                resposta.status_code,
                resposta.text,
            )
            return False
        return True

    async def marcar_como_lida(self, message_id: str) -> None:
        """Marca a mensagem como lida (os dois tiques azuis).

        É cosmético, então falha aqui nunca interrompe o atendimento.
        """
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        headers = {"Authorization": f"Bearer {self.cfg.whatsapp_token}"}
        try:
            http = await self._get_http()
            await http.post(self.base_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.debug("Não deu para marcar %s como lida: %s", message_id, exc)
