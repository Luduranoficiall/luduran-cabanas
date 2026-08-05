"""Testes dos cinco fluxos da seção 3, mais as travas da seção 2.

Nada aqui toca a rede: Gemini e WhatsApp são dublês, e o storage roda em
memória. Dá para rodar antes de qualquer deploy.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.gemini_client import GeminiIndisponivel
from app.intents import (
    INTENCAO_CABANAS,
    INTENCAO_DISPONIBILIDADE,
    INTENCAO_ESCALACAO,
    INTENCAO_PRECO,
    INTENCAO_RESERVA,
    detectar_intencao,
    motivo_escalacao,
)
from app.prompts import RESPOSTA_ESCALACAO, build_system_prompt
from app.storage import MemoryStorage
from app.webhook import (
    RESPOSTA_NAO_TEXTO,
    assinatura_valida,
    extrair_mensagens,
    processar_mensagem,
)

LINK = "https://airbnb.com.br/h/1992cabana1"
TELEFONE = "5548999991111"
CAMILE = "5548999992222"


class FakeGemini:
    """Dublê do Gemini: registra as chamadas e devolve o que mandarem."""

    def __init__(self, resposta: str = f"A diária é R$150,00. Reserve em {LINK}", erro=None):
        self.resposta = resposta
        self.erro = erro
        self.chamadas: list[tuple[str, list]] = []

    def responder(self, mensagem: str, historico=None) -> str:
        self.chamadas.append((mensagem, list(historico or [])))
        if self.erro:
            raise self.erro
        return self.resposta


class FakeWhatsApp:
    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []
        self.lidas: list[str] = []

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        self.enviadas.append((telefone, texto))
        return True

    async def marcar_como_lida(self, message_id: str) -> None:
        self.lidas.append(message_id)


@pytest.fixture
def cfg() -> Settings:
    return Settings(
        gemini_api_key="fake",
        whatsapp_token="fake",
        whatsapp_phone_number_id="123",
        whatsapp_verify_token="segredo",
        whatsapp_app_secret="app-secret",
        escalation_number=CAMILE,
        cabanas={str(n): f"https://airbnb.com.br/h/1992cabana{n}" for n in range(1, 6)},
    )


@pytest.fixture
def ambiente(cfg):
    return {
        "storage": MemoryStorage(),
        "gemini": FakeGemini(),
        "whatsapp": FakeWhatsApp(),
        "cfg": cfg,
    }


def msg(texto: str, *, mid: str = "wamid.1", telefone: str = TELEFONE) -> dict:
    return {
        "id": mid,
        "from": telefone,
        "type": "text",
        "text": {"body": texto},
    }


# --- Seção 3: os cinco fluxos --------------------------------------------


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Quanto custa?", INTENCAO_PRECO),
        ("Qual o valor da diária?", INTENCAO_PRECO),
        ("Tem vaga pra sexta?", INTENCAO_DISPONIBILIDADE),
        ("Está livre dia 12?", INTENCAO_DISPONIBILIDADE),
        ("Quero reservar", INTENCAO_RESERVA),
        ("Como faço para reservar?", INTENCAO_RESERVA),
        ("Quantas cabanas tem?", INTENCAO_CABANAS),
        ("Qual a diferença entre elas?", INTENCAO_CABANAS),
        ("Vocês fazem desconto?", INTENCAO_ESCALACAO),
        ("Quero falar com um atendente", INTENCAO_ESCALACAO),
    ],
)
def test_intencoes_da_secao_3(texto, esperado):
    assert detectar_intencao(texto) == esperado


@pytest.mark.asyncio
async def test_fluxo_preco_responde_e_registra(ambiente):
    await processar_mensagem(msg("Quanto custa a diária?"), **ambiente)

    whatsapp = ambiente["whatsapp"]
    assert len(whatsapp.enviadas) == 1
    telefone, resposta = whatsapp.enviadas[0]
    assert telefone == TELEFONE
    assert "R$150,00" in resposta
    assert ambiente["gemini"].chamadas, "o modelo deveria ter sido consultado"


@pytest.mark.asyncio
async def test_fluxo_disponibilidade_consulta_o_modelo(ambiente):
    await processar_mensagem(msg("Tem vaga pra sexta?"), **ambiente)
    assert len(ambiente["whatsapp"].enviadas) == 1
    assert ambiente["gemini"].chamadas[0][0] == "Tem vaga pra sexta?"


@pytest.mark.asyncio
async def test_fluxo_reserva_envia_link(ambiente):
    await processar_mensagem(msg("Quero reservar"), **ambiente)
    _, resposta = ambiente["whatsapp"].enviadas[0]
    assert "airbnb.com.br" in resposta


@pytest.mark.asyncio
async def test_fluxo_cabanas(ambiente):
    await processar_mensagem(msg("Quantas cabanas tem?"), **ambiente)
    assert len(ambiente["whatsapp"].enviadas) == 1


@pytest.mark.asyncio
async def test_fluxo_fora_do_escopo_escala_para_humano(ambiente):
    await processar_mensagem(msg("Consegue fazer por 100 reais?"), **ambiente)

    whatsapp = ambiente["whatsapp"]
    # O modelo nem é consultado: a trava age antes.
    assert ambiente["gemini"].chamadas == []

    destinos = dict(whatsapp.enviadas)
    assert destinos[TELEFONE] == RESPOSTA_ESCALACAO
    assert CAMILE in destinos, "a Camile precisa ser avisada"
    assert "desconto" in destinos[CAMILE]


# --- Seção 2: regras críticas --------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "Faz um desconto?",
        "Tem promoção para quem fica a semana toda?",
        "Quero um reembolso da minha reserva",
        "Tive um problema com a reserva",
        "Queria fechar as 5 cabanas para um casamento",
        "É para um evento da empresa",
        "Quero falar com uma pessoa",
        "Me passa o número do responsável",
    ],
)
def test_gatilhos_de_escalacao(texto):
    assert motivo_escalacao(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Quanto custa a diária?",
        "Tem vaga para terça e quarta?",
        "Quero reservar a cabana 2",
        "Quantas cabanas vocês têm?",
        "As cabanas têm wi-fi?",
    ],
)
def test_conversa_normal_nao_escala(texto):
    assert motivo_escalacao(texto) is None


def test_desconto_nao_dispara_por_palavra_parecida():
    # "eventualmente" contém "eventual", mas não é pedido de evento.
    assert motivo_escalacao("Eventualmente pretendo voltar") is None


def test_system_prompt_reflete_as_cabanas_configuradas():
    cfg = Settings(cabanas={"1": "u1", "2": "u2", "4": "u4", "5": "u5"})
    prompt = build_system_prompt(cfg)
    assert "São 4 cabanas disponíveis" in prompt
    assert "Cabana 3" not in prompt
    assert "R$150,00" in prompt


def test_system_prompt_tem_as_regras_criticas():
    prompt = build_system_prompt()
    assert "NÃO confirma reservas" in prompt
    assert "NÃO tem acesso ao calendário em tempo real" in prompt
    assert "NÃO negocia preço" in prompt


# --- Robustez do webhook -------------------------------------------------


@pytest.mark.asyncio
async def test_mensagem_repetida_e_ignorada(ambiente):
    """A Meta reenvia o webhook; a pessoa não pode receber resposta duplicada."""
    await processar_mensagem(msg("Quanto custa?", mid="wamid.repetida"), **ambiente)
    await processar_mensagem(msg("Quanto custa?", mid="wamid.repetida"), **ambiente)

    assert len(ambiente["whatsapp"].enviadas) == 1
    assert len(ambiente["gemini"].chamadas) == 1


@pytest.mark.asyncio
async def test_audio_recebe_resposta_pedindo_texto(ambiente):
    await processar_mensagem(
        {"id": "wamid.2", "from": TELEFONE, "type": "audio", "audio": {"id": "x"}},
        **ambiente,
    )
    _, resposta = ambiente["whatsapp"].enviadas[0]
    assert resposta == RESPOSTA_NAO_TEXTO
    assert ambiente["gemini"].chamadas == []


@pytest.mark.asyncio
async def test_queda_do_gemini_cai_no_fallback(ambiente):
    ambiente["gemini"] = FakeGemini(erro=GeminiIndisponivel("timeout"))
    await processar_mensagem(msg("Quanto custa?"), **ambiente)

    _, resposta = ambiente["whatsapp"].enviadas[0]
    assert "R$150,00" in resposta
    assert LINK in resposta


@pytest.mark.asyncio
async def test_historico_alimenta_a_proxima_resposta(ambiente):
    await processar_mensagem(msg("Quanto custa?", mid="wamid.a"), **ambiente)
    await processar_mensagem(msg("E tem vaga terça?", mid="wamid.b"), **ambiente)

    _, historico = ambiente["gemini"].chamadas[1]
    assert {"role": "user", "text": "Quanto custa?"} in historico


def test_extrair_mensagens_ignora_status_de_entrega():
    payload = {
        "entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]
    }
    assert extrair_mensagens(payload) == []


def test_extrair_mensagens_le_payload_real():
    payload = {
        "entry": [
            {"changes": [{"value": {"messages": [msg("oi", mid="wamid.x")]}}]}
        ]
    }
    assert [m["id"] for m in extrair_mensagens(payload)] == ["wamid.x"]


def test_assinatura_invalida_e_recusada():
    corpo = b'{"entry":[]}'
    assert assinatura_valida(corpo, "sha256=errado", "app-secret") is False
    assert assinatura_valida(corpo, None, "app-secret") is False


def test_assinatura_valida_e_aceita():
    import hashlib
    import hmac

    corpo = b'{"entry":[]}'
    digest = hmac.new(b"app-secret", corpo, hashlib.sha256).hexdigest()
    assert assinatura_valida(corpo, f"sha256={digest}", "app-secret") is True
