"""Testes do painel: autenticação, isolamento por nicho, métricas e CSV.

O foco está no que, se quebrar, vaza dado pessoal de cliente final: quem
entra, o que cada papel enxerga, e se dá para furar o filtro pela URL.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.painel import auth as a
from app.painel.repositorio import (
    FUSO_BR,
    RepoPainelMemoria,
    agrupar_leads,
    calcular_metricas,
    fim_do_mes,
    inicio_do_mes,
)
from app.storage import MemoryStorage

SENHA_LUCAS = "senha-forte-do-lucas"
SENHA_ADRIANO = "senha-forte-adriano"

TEL_A = "5554999990001"
TEL_B = "5554999990002"


def _doc(
    *,
    telefone=TEL_A,
    nicho="cabanas",
    quando=None,
    lead_quente=False,
    sinais=(),
    link=False,
    escalado=False,
    resposta_em_s=None,
    texto="oi",
):
    criado = quando or datetime(2026, 3, 10, 14, 0, tzinfo=FUSO_BR)
    doc = {
        "nicho": nicho,
        "telefone": telefone,
        "texto": texto,
        "intencao": "preco",
        "lead_quente": lead_quente,
        "sinais_lead": list(sinais),
        "resposta": "resposta",
        "escalado": escalado,
        "link_enviado": link,
        "criado_em": criado,
    }
    if resposta_em_s is not None:
        doc["respondido_em"] = criado + timedelta(seconds=resposta_em_s)
    return doc


# --- Senhas e sessões -----------------------------------------------------


def test_senha_nao_fica_reversivel():
    h = a.gerar_hash("uma-senha-qualquer")
    assert "uma-senha-qualquer" not in h
    assert h.startswith("scrypt$")
    assert a.conferir_senha("uma-senha-qualquer", h)
    assert not a.conferir_senha("outra-senha", h)


def test_hashes_iguais_geram_saidas_diferentes():
    """Sal por usuário: senha igual não pode gerar hash igual."""
    assert a.gerar_hash("mesma-senha") != a.gerar_hash("mesma-senha")


def test_hash_corrompido_nao_derruba_login():
    assert a.conferir_senha("x", "lixo") is False
    assert a.conferir_senha("x", "") is False


@pytest.mark.asyncio
async def test_sessao_guarda_hash_do_token_e_nao_o_token():
    """Vazamento da base não pode entregar sessão utilizável."""
    repo = a.RepoAuthMemoria(
        usuarios={"lucas@luduran.com": a.Usuario("lucas@luduran.com", a.gerar_hash(SENHA_LUCAS), a.PAPEL_ADMIN)}
    )
    usuario = await a.autenticar(repo, "lucas@luduran.com", SENHA_LUCAS)
    token = await a.abrir_sessao(repo, usuario)

    assert token not in repo.sessoes
    assert a.hash_token(token) in repo.sessoes


@pytest.mark.asyncio
async def test_sessao_expirada_nao_autentica():
    repo = a.RepoAuthMemoria(
        usuarios={"x@x.com": a.Usuario("x@x.com", a.gerar_hash(SENHA_LUCAS))}
    )
    token = "token-vencido"
    await repo.salvar_sessao(
        a.hash_token(token), "x@x.com", datetime.now(a.timezone.utc) - timedelta(minutes=1)
    )
    assert await a.usuario_da_sessao(repo, token) is None


@pytest.mark.asyncio
async def test_usuario_desativado_perde_acesso():
    repo = a.RepoAuthMemoria(
        usuarios={"x@x.com": a.Usuario("x@x.com", a.gerar_hash(SENHA_LUCAS), ativo=False)}
    )
    assert await a.autenticar(repo, "x@x.com", SENHA_LUCAS) is None


@pytest.mark.asyncio
async def test_email_inexistente_nao_autentica():
    repo = a.RepoAuthMemoria()
    assert await a.autenticar(repo, "ninguem@x.com", "seja-la-o-que-for") is None


def test_bloqueio_apos_tentativas_seguidas():
    controle = a.ControleTentativas(limite=3, janela_s=900)
    chave = "alguem@x.com|1.2.3.4"
    assert not controle.bloqueado(chave)
    for _ in range(3):
        controle.registrar_falha(chave)
    assert controle.bloqueado(chave)
    controle.limpar(chave)
    assert not controle.bloqueado(chave)


# --- Papéis e nichos ------------------------------------------------------


def test_admin_ve_todos_os_nichos():
    lucas = a.Usuario("lucas@luduran.com", "x", a.PAPEL_ADMIN)
    assert lucas.pode_ver("cabanas")
    assert lucas.pode_ver("academia")
    assert lucas.nichos_visiveis(["cabanas", "academia"]) == ["academia", "cabanas"]


def test_leitor_so_ve_o_nicho_dele():
    adriano = a.Usuario("adriano@x.com", "x", a.PAPEL_LEITOR, nichos=("cabanas",))
    assert adriano.pode_ver("cabanas")
    assert not adriano.pode_ver("academia")
    assert adriano.nichos_visiveis(["cabanas", "academia"]) == ["cabanas"]


# --- Métricas -------------------------------------------------------------


def test_metricas_contam_pessoa_e_nao_mensagem():
    docs = [
        _doc(telefone=TEL_A, lead_quente=True, sinais=["data_especifica"]),
        _doc(telefone=TEL_A, lead_quente=True, sinais=["numero_pessoas"]),
        _doc(telefone=TEL_B),
    ]
    m = calcular_metricas(docs)
    assert m.mensagens == 3
    assert m.pessoas == 2
    # Quem mandou duas mensagens quentes continua sendo um lead só.
    assert m.leads_quentes == 1


def test_metricas_de_link_escalacao_e_tempo():
    docs = [
        _doc(link=True, resposta_em_s=2),
        _doc(escalado=True, resposta_em_s=4),
        _doc(),
    ]
    m = calcular_metricas(docs)
    assert m.links_enviados == 1
    assert m.escalacoes == 1
    assert m.tempo_medio_resposta_s == 3.0
    assert m.tempo_medio_texto == "3.0s"


def test_tempo_medio_sem_dado_nao_inventa_numero():
    m = calcular_metricas([_doc()])
    assert m.tempo_medio_resposta_s is None
    assert m.tempo_medio_texto == "—"


def test_metricas_de_periodo_vazio():
    m = calcular_metricas([])
    assert (m.mensagens, m.pessoas, m.leads_quentes) == (0, 0, 0)


def test_agrupar_leads_junta_sinais_do_mesmo_telefone():
    docs = [
        _doc(telefone=TEL_A, lead_quente=True, sinais=["data_especifica"],
             quando=datetime(2026, 3, 5, 9, 0, tzinfo=FUSO_BR)),
        _doc(telefone=TEL_A, lead_quente=True, sinais=["numero_pessoas"], link=True,
             quando=datetime(2026, 3, 6, 9, 0, tzinfo=FUSO_BR)),
        _doc(telefone=TEL_B, lead_quente=False),
    ]
    leads = agrupar_leads(docs)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.telefone == TEL_A
    assert lead.mensagens == 2
    assert lead.sinais == {"data_especifica", "numero_pessoas"}
    assert lead.link_enviado is True
    assert lead.primeiro_contato.day == 5
    assert lead.ultimo_contato.day == 6


def test_limites_do_mes_usam_fuso_do_brasil():
    """Sem isso, março começaria às 21h de fevereiro para o cliente."""
    inicio = inicio_do_mes(2026, 3)
    assert (inicio.day, inicio.hour) == (1, 0)
    assert inicio.utcoffset() == timedelta(hours=-3)
    assert fim_do_mes(2026, 12) == inicio_do_mes(2027, 1)


@pytest.mark.asyncio
async def test_repositorio_filtra_periodo_e_nicho():
    storage = MemoryStorage()
    storage._docs = {
        "1": _doc(quando=datetime(2026, 3, 10, tzinfo=FUSO_BR)),
        "2": _doc(quando=datetime(2026, 4, 1, tzinfo=FUSO_BR)),
        "3": _doc(quando=datetime(2026, 3, 11, tzinfo=FUSO_BR), nicho="academia"),
    }
    repo = RepoPainelMemoria(storage)
    docs = await repo.docs_do_periodo("cabanas", inicio_do_mes(2026, 3), fim_do_mes(2026, 3))
    assert len(docs) == 1


# --- Rotas ----------------------------------------------------------------


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("NICHOS_PAINEL", "cabanas,academia")
    monkeypatch.setenv("COOKIE_SEGURO", "0")
    monkeypatch.setenv("GCP_PROJECT_ID", "")  # força storage em memória

    # `from .config import settings` cria um binding próprio em cada módulo,
    # então trocar só em app.config não alcança quem já importou.
    import app.config as config_mod
    import app.main as main_mod
    import app.painel.rotas as rotas_mod

    novo = Settings()
    for modulo in (config_mod, main_mod, rotas_mod):
        monkeypatch.setattr(modulo, "settings", novo)

    with TestClient(app) as c:
        storage = c.app.state.storage
        storage._docs = {
            "m1": _doc(telefone=TEL_A, lead_quente=True, sinais=["data_especifica"], link=True),
            "m2": _doc(telefone=TEL_B),
            "m3": _doc(telefone=TEL_B, nicho="academia", lead_quente=True, sinais=["pediu_reserva"]),
        }
        c.app.state.repo_auth.usuarios = {
            "lucas@luduran.com": a.Usuario(
                "lucas@luduran.com", a.gerar_hash(SENHA_LUCAS), a.PAPEL_ADMIN
            ),
            "adriano@exemplo.com": a.Usuario(
                "adriano@exemplo.com", a.gerar_hash(SENHA_ADRIANO),
                a.PAPEL_LEITOR, nichos=("cabanas",),
            ),
        }
        yield c


def entrar(cliente, email, senha):
    return cliente.post(
        "/painel/login", data={"email": email, "senha": senha}, follow_redirects=False
    )


def test_painel_exige_login(cliente):
    r = cliente.get("/painel/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/painel/login"


def test_csv_exige_login(cliente):
    r = cliente.get("/painel/fechamento.csv", follow_redirects=False)
    assert r.status_code == 303


def test_login_errado_e_recusado(cliente):
    r = entrar(cliente, "lucas@luduran.com", "senha-errada")
    assert r.status_code == 401
    assert a.COOKIE_SESSAO not in r.cookies


def test_login_nao_revela_quem_tem_conta(cliente):
    """As duas respostas têm que ser indistinguíveis."""
    inexistente = entrar(cliente, "ninguem@exemplo.com", "seja-la-o-que-for")
    existente = entrar(cliente, "lucas@luduran.com", "senha-errada")
    assert inexistente.status_code == existente.status_code == 401
    assert inexistente.text == existente.text


def test_login_correto_abre_sessao_com_cookie_protegido(cliente):
    r = entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")
    assert "Path=/painel" in cookie


def test_painel_abre_depois_do_login(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get("/painel/")
    assert r.status_code == 200
    assert "Pessoas atendidas" in r.text


def test_logout_derruba_a_sessao(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    assert cliente.get("/painel/").status_code == 200

    cliente.post("/painel/logout", follow_redirects=False)
    assert cliente.get("/painel/", follow_redirects=False).status_code == 303


def test_leitor_nao_alcanca_outro_nicho_pela_url(cliente):
    """A tentativa mais óbvia de furar o isolamento: trocar ?nicho= na barra."""
    entrar(cliente, "adriano@exemplo.com", SENHA_ADRIANO)

    assert cliente.get("/painel/?nicho=cabanas").status_code == 200
    assert cliente.get("/painel/?nicho=academia").status_code == 403
    assert cliente.get("/painel/fechamento?nicho=academia").status_code == 403
    assert cliente.get("/painel/fechamento.csv?nicho=academia").status_code == 403
    assert cliente.get(f"/painel/telefone/{TEL_B}?nicho=academia").status_code == 403


def test_admin_alcanca_os_dois_nichos(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    assert cliente.get("/painel/?nicho=cabanas").status_code == 200
    assert cliente.get("/painel/?nicho=academia").status_code == 200


def test_leitor_cai_no_nicho_dele_quando_nao_pede_nenhum(cliente):
    entrar(cliente, "adriano@exemplo.com", SENHA_ADRIANO)
    r = cliente.get("/painel/")
    assert r.status_code == 200
    assert "cabanas" in r.text


def test_fechamento_lista_o_lead_quente(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3")
    assert r.status_code == 200
    assert TEL_A in r.text
    # Telefone sem lead quente não entra na lista do fechamento.
    assert TEL_B not in r.text


def test_csv_sai_com_cabecalho_e_dados(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3")

    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "fechamento-cabanas-2026-03.csv" in r.headers["content-disposition"]

    linhas = r.text.lstrip("﻿").strip().splitlines()
    assert linhas[0].startswith("telefone;primeiro_contato")
    assert TEL_A in linhas[1]
    assert "data_especifica" in linhas[1]


def test_exportacao_de_csv_fica_na_auditoria(cliente):
    """A LGPD pede saber quem tirou dado pessoal do sistema, e quando."""
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3")

    exportacoes = [
        e for e in cliente.app.state.repo_auth.auditoria if e["acao"] == "exportou_csv"
    ]
    assert len(exportacoes) == 1
    assert exportacoes[0]["quem"] == "lucas@luduran.com"
    assert "cabanas 2026-03" in exportacoes[0]["detalhe"]


def test_login_e_falha_ficam_na_auditoria(cliente):
    entrar(cliente, "lucas@luduran.com", "senha-errada")
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)

    acoes = [e["acao"] for e in cliente.app.state.repo_auth.auditoria]
    assert "login_falhou" in acoes
    assert "login" in acoes


def test_historico_por_telefone(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get(f"/painel/telefone/{TEL_A}?nicho=cabanas")
    assert r.status_code == 200
    assert TEL_A in r.text


def test_painel_fica_fora_de_buscador(cliente):
    entrar(cliente, "lucas@luduran.com", SENHA_LUCAS)
    r = cliente.get("/painel/")
    assert "noindex" in r.text


# --- criação de usuário ---------------------------------------------------


def _criar_usuario_mod():
    import importlib.util
    from pathlib import Path

    caminho = Path(__file__).resolve().parent.parent / "scripts" / "criar_usuario.py"
    spec = importlib.util.spec_from_file_location("criar_usuario", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_senha_pode_vir_do_ambiente(monkeypatch):
    """Colar um bloco de comandos mata o prompt interativo.

    A pergunta do getpass consome a linha seguinte do bloco colado, ou morre
    com KeyboardInterrupt — foi o que travou a instalação em produção. Com a
    variável, o mesmo bloco roda inteiro sem parar.
    """
    mod = _criar_usuario_mod()
    monkeypatch.setenv("SENHA_PAINEL", "uma-senha-bem-longa")
    assert mod.pedir_senha() == "uma-senha-bem-longa"


def test_senha_curta_no_ambiente_e_recusada(monkeypatch):
    mod = _criar_usuario_mod()
    monkeypatch.setenv("SENHA_PAINEL", "curta")
    with pytest.raises(SystemExit) as e:
        mod.pedir_senha()
    assert "mínimo" in str(e.value)


def test_sem_variavel_ainda_pergunta(monkeypatch):
    """Quem roda à mão continua sendo perguntado, com confirmação."""
    mod = _criar_usuario_mod()
    monkeypatch.delenv("SENHA_PAINEL", raising=False)
    respostas = iter(["uma-senha-bem-longa", "uma-senha-bem-longa"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda _: next(respostas))
    assert mod.pedir_senha() == "uma-senha-bem-longa"


# --- demonstração aberta --------------------------------------------------


def test_raiz_abre_a_demo_sem_login(cliente):
    """O cliente precisa aprovar o sistema antes de existir credencial da Meta.

    Exigir login para isso trava a aprovação — e é justamente o que ele pediu
    para não ter. A página não lê nem grava nada, então não expõe telefone de
    ninguém.
    """
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "o atendente" in r.text.lower()
    assert a.COOKIE_SESSAO not in r.cookies


def test_demo_tem_endereco_proprio(cliente):
    """/demo continua valendo depois que a raiz virar o painel."""
    assert cliente.get("/demo").status_code == 200


def test_painel_continua_exigindo_login_com_a_demo_aberta(cliente):
    """Abrir a demo não pode afrouxar o painel, que guarda dado pessoal."""
    assert cliente.get("/painel/", follow_redirects=False).status_code == 303
    assert cliente.get("/painel/fechamento.csv", follow_redirects=False).status_code == 303


def test_demo_pode_ser_desligada(cliente, monkeypatch):
    """Depois do lançamento, a raiz volta a ser a porta do painel."""
    import dataclasses

    import app.main as main_mod

    # Settings é congelado de propósito: configuração não muda em tempo de
    # execução. Para o teste, troca-se o objeto inteiro.
    monkeypatch.setattr(
        main_mod, "settings", dataclasses.replace(main_mod.settings, demo_publica=False)
    )
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/painel/"
