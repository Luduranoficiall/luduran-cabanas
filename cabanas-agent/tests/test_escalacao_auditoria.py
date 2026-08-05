"""Escalação que não chega por WhatsApp, e a trilha de auditoria.

O caminho de escalação tem uma falha estrutural: o número de escalação
combinado é o mesmo número do atendimento, e a Cloud API não entrega mensagem
de um número para ele mesmo. Estes testes travam as duas pontas — o agente não
tenta um envio que a Meta vai recusar, e o painel mostra quem está esperando.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, so_digitos
from app.main import app
from app.painel import auth as a
from app.painel.repositorio import FUSO_BR
from app.storage import MemoryStorage
from app.webhook import processar_mensagem

NUMERO_CLUBE = "+55 54 98448-7198"
NUMERO_DIGITOS = "5554984487198"
CLIENTE = "5554999990001"

SENHA_LUCAS = "senha-forte-do-lucas"
SENHA_CAMILY = "senha-forte-da-camily"


class FakeWhatsApp:
    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        self.enviadas.append((telefone, texto))
        return True

    async def marcar_como_lida(self, message_id: str) -> None:
        pass


class FakeGemini:
    def responder(self, mensagem, historico=None):
        return "resposta"


def msg(texto: str, mid: str = "wamid.1") -> dict:
    return {"id": mid, "from": CLIENTE, "type": "text", "text": {"body": texto}}


# --- Normalização de telefone --------------------------------------------


def test_so_digitos_normaliza_formatos():
    assert so_digitos(NUMERO_CLUBE) == NUMERO_DIGITOS
    assert so_digitos("5554984487198") == NUMERO_DIGITOS
    assert so_digitos("+55 (54) 98448-7198") == NUMERO_DIGITOS


def test_detecta_escalacao_para_o_proprio_numero():
    """Combinado do cliente: atendimento e escalação no mesmo número."""
    cfg = Settings(
        whatsapp_phone_number=NUMERO_CLUBE, escalation_number=NUMERO_DIGITOS
    )
    assert cfg.escalacao_para_si_mesmo is True


def test_numeros_diferentes_nao_disparam_o_alerta():
    cfg = Settings(
        whatsapp_phone_number=NUMERO_CLUBE, escalation_number="5511999998888"
    )
    assert cfg.escalacao_para_si_mesmo is False


def test_sem_numero_configurado_nao_disparam_o_alerta():
    assert Settings(whatsapp_phone_number="", escalation_number="").escalacao_para_si_mesmo is False


# --- Comportamento do agente ---------------------------------------------


@pytest.mark.asyncio
async def test_nao_tenta_avisar_quando_o_destino_e_o_proprio_numero():
    """Tentar só geraria erro na Meta; a escalação fica registrada mesmo assim."""
    cfg = Settings(
        whatsapp_phone_number=NUMERO_CLUBE,
        escalation_number=NUMERO_DIGITOS,
        cabanas={"1": "https://airbnb.com.br/h/1992cabana1"},
    )
    storage, whatsapp = MemoryStorage(), FakeWhatsApp()
    await processar_mensagem(
        msg("Faz desconto?"),
        storage=storage,
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=cfg,
    )

    destinos = [t for t, _ in whatsapp.enviadas]
    assert destinos == [CLIENTE], "só o cliente recebe; o aviso interno não é tentado"
    # O que importa: a escalação não se perde.
    assert storage._docs["wamid.1"]["escalado"] is True


@pytest.mark.asyncio
async def test_avisa_normalmente_quando_o_numero_e_diferente():
    cfg = Settings(
        whatsapp_phone_number=NUMERO_CLUBE,
        escalation_number="5511999998888",
        cabanas={"1": "https://airbnb.com.br/h/1992cabana1"},
    )
    whatsapp = FakeWhatsApp()
    await processar_mensagem(
        msg("Faz desconto?"),
        storage=MemoryStorage(),
        gemini=FakeGemini(),
        whatsapp=whatsapp,
        cfg=cfg,
    )
    assert "5511999998888" in [t for t, _ in whatsapp.enviadas]


# --- Telas ----------------------------------------------------------------


def _doc(telefone, texto, quando, *, escalado=False, quente=False):
    return {
        "nicho": "cabanas",
        "telefone": telefone,
        "texto": texto,
        "intencao": "escalacao" if escalado else "preco",
        "lead_quente": quente,
        "sinais_lead": ["numero_pessoas"] if quente else [],
        "resposta": "ok",
        "escalado": escalado,
        "link_enviado": True,
        "criado_em": quando,
    }


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("NICHOS_PAINEL", "cabanas")
    monkeypatch.setenv("COOKIE_SEGURO", "0")
    monkeypatch.setenv("GCP_PROJECT_ID", "")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER", NUMERO_CLUBE)
    monkeypatch.setenv("ESCALATION_NUMBER", NUMERO_DIGITOS)

    import app.config as config_mod
    import app.main as main_mod
    import app.painel.rotas as rotas_mod

    novo = Settings()
    for modulo in (config_mod, main_mod, rotas_mod):
        monkeypatch.setattr(modulo, "settings", novo)

    with TestClient(app) as c:
        agora = datetime(2026, 3, 10, 14, tzinfo=FUSO_BR)
        c.app.state.storage._docs = {
            "e1": _doc(CLIENTE, "Faz desconto para 6 pessoas?", agora,
                       escalado=True, quente=True),
            "n1": _doc("5554999990002", "Quanto custa?", agora + timedelta(hours=1)),
        }
        c.app.state.repo_auth.usuarios = {
            "lucas@luduran.com": a.Usuario(
                "lucas@luduran.com", a.gerar_hash(SENHA_LUCAS), a.PAPEL_ADMIN
            ),
            "camily@exemplo.com": a.Usuario(
                "camily@exemplo.com", a.gerar_hash(SENHA_CAMILY),
                a.PAPEL_OPERADOR, nichos=("cabanas",),
            ),
        }
        yield c


def entrar(cliente, email, senha):
    return cliente.post("/painel/login", data={"email": email, "senha": senha})


def test_health_denuncia_a_escalacao_quebrada(cliente):
    d = cliente.get("/health").json()
    assert d["aviso_escalacao_por_whatsapp"] == "quebrado: mesmo número do atendimento"


def test_tela_de_escalacoes_lista_quem_espera(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = cliente.get("/painel/escalacoes?nicho=cabanas&ano=2026&mes=3")

    assert r.status_code == 200
    assert "Faz desconto para 6 pessoas?" in r.text
    # Conversa que não escalou não polui a lista.
    assert "Quanto custa?" not in r.text


def test_tela_de_escalacoes_avisa_que_o_whatsapp_nao_entrega(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = cliente.get("/painel/escalacoes?nicho=cabanas&ano=2026&mes=3")
    assert "não está sendo enviado" in r.text
    assert "mesmo número do atendimento" in r.text


def test_escalacoes_exige_login(cliente):
    r = cliente.get("/painel/escalacoes", follow_redirects=False)
    assert r.status_code == 303


def test_auditoria_e_so_para_admin(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    assert cliente.get("/painel/auditoria").status_code == 403


def test_admin_ve_a_trilha_de_auditoria(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get("/painel/auditoria")

    assert r.status_code == 200
    assert "lucas@luduran.com" in r.text
    assert "Trilha de auditoria" in r.text


def test_auditoria_mostra_o_evento_mais_novo_primeiro(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3")

    eventos = await_lista(cliente)
    assert eventos[0]["acao"] == "exportou_csv"
    assert eventos[-1]["acao"] == "login"


def await_lista(cliente):
    import asyncio

    return asyncio.run(cliente.app.state.repo_auth.listar_auditoria(50))


def test_link_de_auditoria_so_aparece_para_admin(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    assert "/painel/auditoria" not in cliente.get("/painel/").text

    cliente.post("/painel/logout")
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    assert "/painel/auditoria" in cliente.get("/painel/").text
