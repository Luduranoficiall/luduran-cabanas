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
            self._explicar_recusa(telefone, resposta)
            return False
        return True

    # Erro da Meta para "passaram-se mais de 24h desde a última mensagem
    # daquele número". É a recusa mais provável no aviso de escalação, e a
    # mensagem crua da Meta não diz o que fazer.
    CODIGO_FORA_DA_JANELA = 131047

    def _explicar_recusa(self, telefone: str, resposta: httpx.Response) -> None:
        codigo = None
        try:
            codigo = (resposta.json().get("error") or {}).get("code")
        except ValueError:
            pass

        if codigo == self.CODIGO_FORA_DA_JANELA:
            logger.error(
                "Meta recusou o envio para %s: a janela de 24h está fechada. "
                "Texto livre só sai se aquele número tiver mandado mensagem "
                "para o sistema nas últimas 24h. Para avisar fora da janela é "
                "preciso um template aprovado — configure ESCALATION_TEMPLATE.",
                telefone,
            )
            return

        logger.error(
            "Meta recusou envio para %s (%s): %s",
            telefone,
            resposta.status_code,
            resposta.text,
        )

    async def enviar_template(
        self, telefone: str, nome: str, idioma: str, parametros: list[str]
    ) -> bool:
        """Envia um template aprovado.

        Diferente do texto livre, template entrega mesmo com a janela de 24h
        fechada — é o que faz o aviso de escalação chegar na secretária, que
        nunca conversa com o número do sistema.

        Os parâmetros preenchem os {{1}}, {{2}}... do corpo do template, na
        ordem.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefone,
            "type": "template",
            "template": {
                "name": nome,
                "language": {"code": idioma},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": p} for p in parametros
                        ],
                    }
                ],
            },
        }
        headers = {"Authorization": f"Bearer {self.cfg.whatsapp_token}"}

        try:
            http = await self._get_http()
            resposta = await http.post(self.base_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("Falha de rede ao enviar template para %s: %s", telefone, exc)
            return False

        if resposta.status_code >= 400:
            logger.error(
                "Meta recusou o template %s para %s (%s): %s",
                nome,
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
