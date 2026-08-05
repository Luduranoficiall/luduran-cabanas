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
    SINAL_DATA,
    SINAL_PESSOAS,
    SINAL_RESERVA,
    detectar_intencao,
    eh_lead_quente,
    motivo_escalacao,
    sinais_de_reserva,
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


# --- Configuração das cabanas -------------------------------------------
#
# O combinado com o cliente: ligar a cabana 3 tem que ser só configuração.
# Os testes abaixo travam esse contrato.


def test_as_cinco_cabanas_estao_no_ar(monkeypatch):
    """Link da cabana 3 confirmado pelo cliente: as cinco entram por padrão."""
    monkeypatch.delenv("CABANAS", raising=False)
    monkeypatch.delenv("CABANA_URLS", raising=False)
    cfg = Settings()

    assert sorted(cfg.cabanas) == ["1", "2", "3", "4", "5"]
    assert cfg.total_cabanas == 5
    assert cfg.cabanas["3"] == "https://airbnb.com.br/h/1992cabana3"
    assert cfg.cabanas_sem_link == []

    prompt = build_system_prompt(cfg)
    assert "São 5 cabanas disponíveis" in prompt
    assert "Cabana 3: https://airbnb.com.br/h/1992cabana3" in prompt


def test_desligar_uma_cabana_continua_sendo_so_configuracao(monkeypatch):
    """Se uma cabana sair de operação, tirar do ar não exige deploy de código."""
    monkeypatch.setenv("CABANAS", "1,2,4,5")
    monkeypatch.delenv("CABANA_URLS", raising=False)
    cfg = Settings()

    assert sorted(cfg.cabanas) == ["1", "2", "4", "5"]
    assert "Cabana 3" not in build_system_prompt(cfg)


def test_cabana_sem_link_fica_fora_em_vez_de_inventar_url(monkeypatch):
    """Uma cabana nova só entra depois que o link dela é cadastrado.

    A trava vale para qualquer cabana futura: sem link conhecido, o agente não
    deriva URL por padrão de nome — link chutado vira link quebrado na mão do
    cliente.
    """
    monkeypatch.setenv("CABANAS", "1,2,3,4,5,6")
    monkeypatch.delenv("CABANA_URLS", raising=False)
    cfg = Settings()

    assert "6" not in cfg.cabanas
    assert cfg.cabanas_sem_link == ["6"]
    assert "Cabana 6" not in build_system_prompt(cfg)


def test_cabana_urls_corrige_link_existente(monkeypatch):
    monkeypatch.setenv("CABANAS", "1,2")
    monkeypatch.setenv("CABANA_URLS", "2=https://airbnb.com.br/h/novo-link-2")
    cfg = Settings()
    assert cfg.cabanas["2"] == "https://airbnb.com.br/h/novo-link-2"
    assert cfg.cabanas["1"] == "https://airbnb.com.br/h/1992cabana1"


def test_gemini_client_monta_o_prompt_a_partir_da_config(monkeypatch):
    """O client não guarda link nenhum: ele lê o que estiver na configuração."""
    from app.gemini_client import GeminiClient

    monkeypatch.setenv("CABANAS", "1,3")
    monkeypatch.setenv("CABANA_URLS", "3=https://airbnb.com.br/h/link-novo-3")
    client = GeminiClient(Settings())

    assert "https://airbnb.com.br/h/link-novo-3" in client._system_prompt
    assert "Cabana 5" not in client._system_prompt


def test_links_de_cabana_so_existem_no_config():
    """Trava de arquitetura.

    Se um link de cabana aparecer em prompts.py ou gemini_client.py, trocar a
    configuração deixa de bastar — e o combinado com o cliente quebra sem
    ninguém perceber.
    """
    import pathlib
    import re

    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    padrao = re.compile(r"airbnb\.com\.br/h/")

    for arquivo in ("prompts.py", "gemini_client.py"):
        conteudo = (app_dir / arquivo).read_text(encoding="utf-8")
        assert not padrao.search(conteudo), (
            f"{arquivo} tem link de cabana embutido; ele deve vir de config.py"
        )


def test_system_prompt_tem_as_regras_criticas():
    prompt = build_system_prompt()
    assert "NÃO confirma reservas" in prompt
    assert "NÃO tem acesso ao calendário em tempo real" in prompt
    assert "NÃO negocia preço" in prompt


# --- 2.3 Captura de intenção de reserva (lead quente) --------------------


@pytest.mark.parametrize(
    "texto,sinal",
    [
        ("Tem vaga pro dia 12?", SINAL_DATA),
        ("Está livre sexta?", SINAL_DATA),
        ("Tem cabana para 12/03?", SINAL_DATA),
        ("Queria ir em dezembro", SINAL_DATA),
        ("Vamos no feriadão", SINAL_DATA),
        ("Somos 4", SINAL_PESSOAS),
        ("É para 6 pessoas", SINAL_PESSOAS),
        ("Vou com a família", SINAL_PESSOAS),
        ("Somos um casal", SINAL_PESSOAS),
        ("Quero reservar", SINAL_RESERVA),
        ("Como faço para reservar?", SINAL_RESERVA),
        ("Vou querer para o mês que vem", SINAL_RESERVA),
    ],
)
def test_sinais_de_lead_quente(texto, sinal):
    assert sinal in sinais_de_reserva(texto)
    assert eh_lead_quente(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Quanto custa a diária?",
        "Quantas cabanas vocês têm?",
        "As cabanas têm wi-fi?",
        "Qual a política de reserva?",
        "Onde fica?",
        "Oi, bom dia",
    ],
)
def test_curiosidade_nao_vira_lead_quente(texto):
    """A métrica sustenta a conversa dos 10%.

    Marcar lead quente demais infla justamente o número que justifica a nossa
    comissão. Na dúvida, não marca.
    """
    assert sinais_de_reserva(texto) == []
    assert not eh_lead_quente(texto)


def test_politica_de_reserva_nao_e_intencao_de_reserva():
    # "reserva" solto é dúvida; o que conta é o verbo com marcador de intenção.
    assert SINAL_RESERVA not in sinais_de_reserva("Qual a política de reserva?")
    assert SINAL_RESERVA in sinais_de_reserva("Quero reservar")


@pytest.mark.asyncio
async def test_lead_quente_vai_para_o_firestore(ambiente):
    await processar_mensagem(msg("Somos 4 pessoas, tem vaga dia 12?"), **ambiente)

    doc = ambiente["storage"]._docs["wamid.1"]
    assert doc["lead_quente"] is True
    assert sorted(doc["sinais_lead"]) == [SINAL_DATA, SINAL_PESSOAS]


@pytest.mark.asyncio
async def test_conversa_fria_fica_marcada_como_fria(ambiente):
    await processar_mensagem(msg("Quanto custa?"), **ambiente)

    doc = ambiente["storage"]._docs["wamid.1"]
    assert doc["lead_quente"] is False
    assert doc["sinais_lead"] == []


@pytest.mark.asyncio
async def test_escalacao_nao_apaga_o_lead_quente(ambiente):
    """Pedir desconto para 4 pessoas no dia 12 é escalação E lead quente.

    O painel do Adriano perderia esse lead se as duas coisas fossem exclusivas.
    """
    await processar_mensagem(msg("Faz desconto para 4 pessoas no dia 12?"), **ambiente)

    doc = ambiente["storage"]._docs["wamid.1"]
    assert doc["escalado"] is True
    assert doc["lead_quente"] is True


# --- 3.3 Multi-nicho ------------------------------------------------------


@pytest.mark.asyncio
async def test_nicho_e_gravado_em_toda_mensagem(ambiente):
    await processar_mensagem(msg("Quanto custa?"), **ambiente)
    assert ambiente["storage"]._docs["wamid.1"]["nicho"] == "cabanas"


@pytest.mark.asyncio
async def test_nicho_vem_da_configuracao(monkeypatch, ambiente):
    monkeypatch.setenv("NICHO", "academia")
    ambiente["cfg"] = Settings(cabanas=ambiente["cfg"].cabanas)

    await processar_mensagem(msg("Quanto custa?"), **ambiente)
    assert ambiente["storage"]._docs["wamid.1"]["nicho"] == "academia"


@pytest.mark.asyncio
async def test_historico_nao_vaza_entre_nichos(ambiente):
    """Mesma pessoa falando com duas operações não pode misturar contexto."""
    storage = ambiente["storage"]
    await storage.reservar_mensagem(
        "wamid.academia", TELEFONE, "Quanto custa a mensalidade?", "preco",
        nicho="academia",
    )
    await storage.registrar_resposta(
        "wamid.academia", "R$99", escalado=False, link_enviado=False
    )

    historico = await storage.historico(TELEFONE, 10, nicho="cabanas")
    assert historico == []

    historico_academia = await storage.historico(TELEFONE, 10, nicho="academia")
    assert len(historico_academia) == 2


def test_nicho_tem_default_para_nao_quebrar_dado_existente():
    cfg = Settings()
    assert cfg.nicho == "cabanas"


# --- 2.5 Fallback do Gemini ----------------------------------------------


def test_timeout_do_gemini_tem_teto_configurado():
    """Sem teto, uma chamada travada nunca devolve nem o fallback."""
    cfg = Settings()
    assert 0 < cfg.gemini_timeout_s <= 20


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
