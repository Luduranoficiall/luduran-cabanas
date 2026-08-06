"""Aviso de escalação com número dedicado.

O cliente resolveu o conflito de número: o sistema nasce num chip novo, e a
secretária (5554984487198) fica no WhatsApp normal só recebendo os avisos.
Isso mata o problema de "mensagem para si mesmo", mas **não** mata a janela de
24h: a secretária nunca conversa com o número do sistema, então a janela dela
está sempre fechada e texto livre é recusado. Template é o único caminho.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.storage import MemoryStorage
from app.webhook import processar_mensagem
from app.whatsapp_client import WhatsAppClient

SISTEMA = "+55 54 99999-0000"  # chip novo, exclusivo da Cloud API
SECRETARIA = "5554984487198"
CLIENTE = "5554999991111"


class FakeGemini:
    def responder(self, mensagem, historico=None):
        return "resposta"


class FakeWhatsApp:
    def __init__(self, texto_falha: bool = False) -> None:
        self.textos: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, str, list[str]]] = []
        self.texto_falha = texto_falha

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        self.textos.append((telefone, texto))
        return not self.texto_falha

    async def enviar_template(self, telefone, nome, idioma, parametros) -> bool:
        self.templates.append((telefone, nome, idioma, list(parametros)))
        return True

    async def marcar_como_lida(self, message_id: str) -> None:
        pass


def msg(texto: str, mid: str = "wamid.1") -> dict:
    return {"id": mid, "from": CLIENTE, "type": "text", "text": {"body": texto}}


@pytest.fixture
def cfg():
    return Settings(
        whatsapp_phone_number=SISTEMA,
        escalation_number=SECRETARIA,
        cabanas={"1": "https://airbnb.com.br/h/1992cabana1"},
    )


# --- O conflito de número acabou ----------------------------------------


def test_numero_dedicado_nao_dispara_a_trava_de_si_mesmo(cfg):
    """Sistema e escalação em números distintos: a trava não se aplica."""
    assert cfg.escalacao_para_si_mesmo is False


def test_a_trava_continua_valendo_se_alguem_reconfigurar_errado():
    """Não removi a checagem: ela protege contra o erro voltar."""
    errado = Settings(
        whatsapp_phone_number=SISTEMA, escalation_number="5554999990000"
    )
    assert errado.escalacao_para_si_mesmo is True


@pytest.mark.asyncio
async def test_secretaria_recebe_o_aviso(cfg):
    whatsapp = FakeWhatsApp()
    await processar_mensagem(
        msg("Faz desconto?"),
        storage=MemoryStorage(),
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=cfg,
    )
    destinos = [t for t, _ in whatsapp.textos]
    assert SECRETARIA in destinos
    assert CLIENTE in destinos


# --- Template: o que entrega fora da janela de 24h ----------------------


@pytest.mark.asyncio
async def test_sem_template_configurado_usa_texto_livre(cfg):
    """Só funciona se a janela estiver aberta — o padrão, até o template sair."""
    whatsapp = FakeWhatsApp()
    await processar_mensagem(
        msg("Faz desconto?"),
        storage=MemoryStorage(),
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=cfg,
    )
    assert whatsapp.templates == []
    assert any(t == SECRETARIA for t, _ in whatsapp.textos)


@pytest.mark.asyncio
async def test_com_template_o_aviso_sai_como_template(cfg):
    com_template = Settings(
        whatsapp_phone_number=SISTEMA,
        escalation_number=SECRETARIA,
        cabanas=cfg.cabanas,
        escalation_template="escalacao_cabanas",
        escalation_template_idioma="pt_BR",
    )
    whatsapp = FakeWhatsApp()
    await processar_mensagem(
        msg("Quero falar com uma pessoa"),
        storage=MemoryStorage(),
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=com_template,
    )

    assert len(whatsapp.templates) == 1
    destino, nome, idioma, parametros = whatsapp.templates[0]
    assert destino == SECRETARIA
    assert nome == "escalacao_cabanas"
    assert idioma == "pt_BR"
    # {{1}} motivo, {{2}} telefone, {{3}} mensagem
    assert parametros[0] == "pediu_humano"
    assert parametros[1] == f"+{CLIENTE}"
    assert "falar com uma pessoa" in parametros[2]

    # O cliente continua recebendo a resposta normal.
    assert any(t == CLIENTE for t, _ in whatsapp.textos)


@pytest.mark.asyncio
async def test_mensagem_longa_e_cortada_no_parametro(cfg):
    """Parâmetro de template tem limite; mensagem enorme não pode derrubar."""
    com_template = Settings(
        whatsapp_phone_number=SISTEMA,
        escalation_number=SECRETARIA,
        cabanas=cfg.cabanas,
        escalation_template="escalacao_cabanas",
    )
    whatsapp = FakeWhatsApp()
    await processar_mensagem(
        msg("Faz desconto? " + "x" * 500),
        storage=MemoryStorage(),
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=com_template,
    )
    assert len(whatsapp.templates[0][3][2]) == 200


@pytest.mark.asyncio
async def test_escalacao_fica_registrada_mesmo_se_o_aviso_falhar(cfg):
    """Se o aviso não sai, o lead não pode se perder junto."""
    storage, whatsapp = MemoryStorage(), FakeWhatsApp(texto_falha=True)
    await processar_mensagem(
        msg("Faz desconto?"),
        storage=storage,
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=cfg,
    )
    assert storage._docs["wamid.1"]["escalado"] is True


# --- Diagnóstico do erro 131047 -----------------------------------------


def _resposta(status: int, corpo: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status, json=corpo, request=httpx.Request("POST", "http://x")
    )


def test_erro_de_janela_fechada_vira_log_acionavel(caplog):
    """A mensagem crua da Meta não diz o que fazer; o log precisa dizer."""
    cliente = WhatsAppClient(Settings())
    with caplog.at_level("ERROR"):
        cliente._explicar_recusa(
            SECRETARIA,
            _resposta(400, {"error": {"code": 131047, "message": "Re-engagement"}}),
        )
    assert "janela de 24h está fechada" in caplog.text
    assert "ESCALATION_TEMPLATE" in caplog.text


def test_outros_erros_mantem_o_corpo_da_meta(caplog):
    cliente = WhatsAppClient(Settings())
    with caplog.at_level("ERROR"):
        cliente._explicar_recusa(
            SECRETARIA, _resposta(401, {"error": {"code": 190, "message": "expirado"}})
        )
    assert "expirado" in caplog.text


def test_corpo_nao_json_nao_derruba_o_diagnostico(caplog):
    cliente = WhatsAppClient(Settings())
    resposta = httpx.Response(
        status_code=502, text="<html>bad gateway</html>",
        request=httpx.Request("POST", "http://x"),
    )
    with caplog.at_level("ERROR"):
        cliente._explicar_recusa(SECRETARIA, resposta)
    assert "502" in caplog.text
