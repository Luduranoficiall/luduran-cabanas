"""Memória com corte por tempo (2.1) e anti-loop (2.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.prompts import RESPOSTA_ANTILOOP
from app.storage import MemoryStorage
from app.webhook import processar_mensagem

TELEFONE = "5554999990001"


class FakeGemini:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, list]] = []

    def responder(self, mensagem: str, historico=None) -> str:
        self.chamadas.append((mensagem, list(historico or [])))
        return "resposta do modelo"


class FakeWhatsApp:
    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        self.enviadas.append((telefone, texto))
        return True

    async def marcar_como_lida(self, message_id: str) -> None:
        pass


@pytest.fixture
def cfg():
    return Settings(
        cabanas={"1": "https://airbnb.com.br/h/1992cabana1"},
        escalation_number="5511999998888",
        whatsapp_phone_number="+55 54 98448-7198",
    )


@pytest.fixture
def ambiente(cfg):
    return {
        "storage": MemoryStorage(),
        "gemini": FakeGemini(),
        "whatsapp": FakeWhatsApp(),
        "cfg": cfg,
    }


def msg(texto: str, mid: str, telefone: str = TELEFONE) -> dict:
    return {"id": mid, "from": telefone, "type": "text", "text": {"body": texto}}


def envelhecer(storage: MemoryStorage, mid: str, minutos: int) -> None:
    """Empurra um documento para trás no tempo."""
    delta = timedelta(minutes=minutos)
    doc = storage._docs[mid]
    doc["criado_em"] -= delta
    if doc.get("respondido_em"):
        doc["respondido_em"] -= delta


# --- 2.1 Memória --------------------------------------------------------


def test_padroes_do_roadmap():
    """10 mensagens ou 30 minutos, o que vier primeiro."""
    cfg = Settings()
    assert cfg.history_limit == 10
    assert cfg.history_janela_min == 30


@pytest.mark.asyncio
async def test_mensagem_atual_nao_vai_duplicada_para_o_modelo(ambiente):
    """Ela é gravada antes da consulta; sem excluí-la, o modelo via duas vezes."""
    await processar_mensagem(msg("Quanto custa?", "w1"), **ambiente)
    await processar_mensagem(msg("E tem wi-fi?", "w2"), **ambiente)

    mensagem, historico = ambiente["gemini"].chamadas[1]
    assert mensagem == "E tem wi-fi?"
    assert [t["text"] for t in historico] == ["Quanto custa?", "resposta do modelo"]


@pytest.mark.asyncio
async def test_conversa_recente_entra_no_contexto(ambiente):
    await processar_mensagem(msg("Quanto custa?", "w1"), **ambiente)
    envelhecer(ambiente["storage"], "w1", 5)  # 5 min atrás, dentro da janela

    await processar_mensagem(msg("E pra 4 pessoas?", "w2"), **ambiente)
    _, historico = ambiente["gemini"].chamadas[1]
    assert {"role": "user", "text": "Quanto custa?"} in historico


@pytest.mark.asyncio
async def test_conversa_velha_fica_de_fora(ambiente):
    """Passados 30 min, aquilo deixa de ser contexto e vira ruído."""
    await processar_mensagem(msg("Quanto custa?", "w1"), **ambiente)
    envelhecer(ambiente["storage"], "w1", 45)

    await processar_mensagem(msg("Vocês aceitam pet?", "w2"), **ambiente)
    _, historico = ambiente["gemini"].chamadas[1]
    assert historico == []


@pytest.mark.asyncio
async def test_janela_e_configuravel(ambiente, cfg):
    ambiente["cfg"] = Settings(
        cabanas=cfg.cabanas, history_janela_min=120, history_limit=10
    )
    await processar_mensagem(msg("Quanto custa?", "w1"), **ambiente)
    envelhecer(ambiente["storage"], "w1", 45)

    await processar_mensagem(msg("E pra 4?", "w2"), **ambiente)
    _, historico = ambiente["gemini"].chamadas[1]
    assert len(historico) == 2  # com 2h de janela, os 45 min continuam valendo


@pytest.mark.asyncio
async def test_limite_de_quantidade_tambem_vale(ambiente, cfg):
    """O corte é "N trocas OU M minutos", o que vier primeiro.

    `history_limit` conta **trocas**, não turnos: cada mensagem recebida vira
    um documento com a pergunta e a resposta, então 2 trocas viram 4 turnos
    para o modelo.
    """
    ambiente["cfg"] = Settings(cabanas=cfg.cabanas, history_limit=2, history_janela_min=30)
    for i in range(4):
        await processar_mensagem(msg(f"pergunta {i}", f"w{i}"), **ambiente)

    _, historico = ambiente["gemini"].chamadas[-1]
    perguntas = [t["text"] for t in historico if t["role"] == "user"]

    assert perguntas == ["pergunta 1", "pergunta 2"], "as 2 trocas mais recentes"
    assert "pergunta 0" not in perguntas, "a mais antiga ficou de fora"


@pytest.mark.asyncio
async def test_historico_de_outro_telefone_nao_vaza(ambiente):
    await processar_mensagem(msg("Sou o cliente A", "w1", "5511111111111"), **ambiente)
    await processar_mensagem(msg("Sou o cliente B", "w2", "5522222222222"), **ambiente)

    _, historico = ambiente["gemini"].chamadas[1]
    assert historico == []


# --- 2.4 Anti-loop ------------------------------------------------------


def test_padroes_do_antiloop():
    """15 mensagens em 10 minutos."""
    cfg = Settings()
    assert cfg.antiloop_mensagens == 15
    assert cfg.antiloop_janela_min == 10


async def _inundar(ambiente, quantidade: int, inicio: int = 0) -> None:
    for i in range(inicio, inicio + quantidade):
        await processar_mensagem(msg(f"oi {i}", f"flood{i}"), **ambiente)


@pytest.mark.asyncio
async def test_ate_o_limite_o_atendimento_segue_normal(ambiente):
    await _inundar(ambiente, 15)
    assert len(ambiente["gemini"].chamadas) == 15
    assert len(ambiente["whatsapp"].enviadas) == 15


@pytest.mark.asyncio
async def test_passando_do_limite_para_de_responder(ambiente):
    await _inundar(ambiente, 16)

    # A 16ª não vai para o modelo.
    assert len(ambiente["gemini"].chamadas) == 15

    para_o_cliente = [t for tel, t in ambiente["whatsapp"].enviadas if tel == TELEFONE]
    assert para_o_cliente[-1] == RESPOSTA_ANTILOOP


@pytest.mark.asyncio
async def test_avisa_uma_vez_so(ambiente):
    """Quem está inundando não precisa receber o mesmo aviso quinze vezes."""
    await _inundar(ambiente, 20)

    avisos = [t for _, t in ambiente["whatsapp"].enviadas if t == RESPOSTA_ANTILOOP]
    assert len(avisos) == 1


@pytest.mark.asyncio
async def test_mensagens_bloqueadas_nao_gastam_o_gemini(ambiente):
    """O ponto do anti-loop: enxurrada não vira enxurrada de chamada paga."""
    await _inundar(ambiente, 30)
    assert len(ambiente["gemini"].chamadas) == 15


@pytest.mark.asyncio
async def test_bloqueio_escala_e_fica_registrado(ambiente):
    await _inundar(ambiente, 16)

    doc = ambiente["storage"]._docs["flood15"]
    assert doc["escalado"] is True
    assert doc["bloqueado"] is True


@pytest.mark.asyncio
async def test_equipe_e_avisada_uma_vez(ambiente):
    await _inundar(ambiente, 20)

    avisos_equipe = [
        t for tel, t in ambiente["whatsapp"].enviadas if tel == "5511999998888"
    ]
    assert len(avisos_equipe) == 1
    assert "anti_loop" in avisos_equipe[0]


@pytest.mark.asyncio
async def test_mensagens_fora_da_janela_nao_contam(ambiente):
    """Quem mandou muita mensagem ontem não pode entrar bloqueado hoje."""
    await _inundar(ambiente, 15)
    for i in range(15):
        envelhecer(ambiente["storage"], f"flood{i}", 30)  # janela é de 10 min

    await processar_mensagem(msg("bom dia", "novo"), **ambiente)
    assert len(ambiente["gemini"].chamadas) == 16
    assert ambiente["storage"]._docs["novo"].get("bloqueado") is not True


@pytest.mark.asyncio
async def test_inundacao_de_um_telefone_nao_bloqueia_outro(ambiente):
    await _inundar(ambiente, 16)
    await processar_mensagem(msg("Quanto custa?", "outro", "5522222222222"), **ambiente)

    assert ambiente["gemini"].chamadas[-1][0] == "Quanto custa?"


@pytest.mark.asyncio
async def test_limite_zero_desliga_a_trava(ambiente, cfg):
    ambiente["cfg"] = Settings(cabanas=cfg.cabanas, antiloop_mensagens=0)
    await _inundar(ambiente, 20)
    assert len(ambiente["gemini"].chamadas) == 20


@pytest.mark.asyncio
async def test_antiloop_roda_antes_da_escalacao(ambiente):
    """Bloqueado é bloqueado: nem o caminho de escalação chama o modelo."""
    await _inundar(ambiente, 16)
    antes = len(ambiente["whatsapp"].enviadas)

    await processar_mensagem(msg("Faz desconto?", "desconto"), **ambiente)
    # Silêncio: já avisamos uma vez.
    assert len(ambiente["whatsapp"].enviadas) == antes
    assert ambiente["storage"]._docs["desconto"]["bloqueado"] is True
