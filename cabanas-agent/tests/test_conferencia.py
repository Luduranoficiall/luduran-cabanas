"""Testes da conferência do fechamento.

É a parte do sistema que vira dinheiro: a Camily marca o que virou reserva, o
painel calcula os 10%, e o Adriano confere caso a caso. Os testes cobrem, em
ordem de importância: a conta não pode estar errada, quem não deve editar não
edita, e toda alteração precisa ficar registrada.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.painel import auth as a
from app.painel.conferencia import (
    Conferencia,
    RepoConferenciaMemoria,
    calcular_totais,
    formatar_reais,
    parse_reais,
)
from app.painel.repositorio import FUSO_BR, Lead, agrupar_leads

SENHA_CAMILY = "senha-forte-da-camily"
SENHA_ADRIANO = "senha-forte-do-adriano"

TEL_A = "5554999990001"
TEL_B = "5554999990002"
TEL_C = "5554999990003"


# --- Dinheiro -------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("150", 15000),
        ("150,00", 15000),
        ("150.00", 15000),
        ("1.234,56", 123456),
        ("1234.56", 123456),
        ("R$ 450,00", 45000),
        ("  300  ", 30000),
        ("0,01", 1),
    ],
)
def test_parse_de_valores(texto, centavos):
    assert parse_reais(texto) == centavos


def test_valor_em_branco_e_diferente_de_zero():
    """Não informado não é reserva de graça — o total precisa saber a diferença."""
    assert parse_reais("") is None
    assert parse_reais(None) is None
    assert parse_reais("0") == 0


@pytest.mark.parametrize("texto", ["abc", "10,5,5", "1,234", "-50", "12.345.678"])
def test_valor_invalido_e_recusado(texto):
    with pytest.raises(ValueError):
        parse_reais(texto)


def test_formatacao_em_reais():
    assert formatar_reais(15000) == "R$ 150,00"
    assert formatar_reais(123456) == "R$ 1.234,56"
    assert formatar_reais(5) == "R$ 0,05"
    assert formatar_reais(None) == "—"


def test_centavos_nao_acumulam_erro_de_float():
    """Três diárias de R$150 têm que dar exatamente R$450, e 10% exatamente R$45."""
    leads = [Lead(telefone=str(i)) for i in range(3)]
    conferencias = {
        str(i): Conferencia(confirmado=True, valor_centavos=15000) for i in range(3)
    }
    totais = calcular_totais(leads, conferencias)
    assert totais.valor_total_centavos == 45000
    assert totais.comissao_centavos == 4500
    assert totais.comissao_texto == "R$ 45,00"


def test_comissao_arredonda_uma_vez_sobre_o_total():
    """Arredondar por linha acumularia diferença de centavo no fechamento."""
    leads = [Lead(telefone=str(i)) for i in range(3)]
    # 3 x R$ 33,33 = R$ 99,99 -> 10% = R$ 10,00 (9,999 arredondado uma vez).
    conferencias = {
        str(i): Conferencia(confirmado=True, valor_centavos=3333) for i in range(3)
    }
    totais = calcular_totais(leads, conferencias)
    assert totais.valor_total_centavos == 9999
    assert totais.comissao_centavos == 1000


# --- Totais ---------------------------------------------------------------


def test_so_confirmadas_entram_na_comissao():
    leads = [Lead(telefone=TEL_A), Lead(telefone=TEL_B), Lead(telefone=TEL_C)]
    conferencias = {
        TEL_A: Conferencia(confirmado=True, valor_centavos=30000),
        TEL_B: Conferencia(confirmado=False, valor_centavos=99999),
    }
    totais = calcular_totais(leads, conferencias)

    assert totais.leads_quentes == 3
    assert totais.confirmadas == 1
    assert totais.valor_total_centavos == 30000
    assert totais.comissao_centavos == 3000


def test_confirmada_sem_valor_marca_total_como_nao_confiavel():
    """Marcar sem informar valor não pode virar um total redondo e errado."""
    leads = [Lead(telefone=TEL_A), Lead(telefone=TEL_B)]
    conferencias = {
        TEL_A: Conferencia(confirmado=True, valor_centavos=30000),
        TEL_B: Conferencia(confirmado=True, valor_centavos=None),
    }
    totais = calcular_totais(leads, conferencias)

    assert totais.confirmadas == 2
    assert totais.confirmadas_sem_valor == 1
    assert totais.total_confiavel is False
    # A comissão sai só do que foi informado — subestimada, e a tela avisa.
    assert totais.comissao_centavos == 3000


def test_mes_sem_conferencia_tem_total_confiavel():
    totais = calcular_totais([Lead(telefone=TEL_A)], {})
    assert totais.confirmadas == 0
    assert totais.total_confiavel is True
    assert totais.comissao_texto == "R$ 0,00"


def test_percentual_e_configuravel():
    leads = [Lead(telefone=TEL_A)]
    conferencias = {TEL_A: Conferencia(confirmado=True, valor_centavos=100000)}
    assert calcular_totais(leads, conferencias, percentual=15).comissao_centavos == 15000


# --- Persistência ---------------------------------------------------------


@pytest.mark.asyncio
async def test_conferencia_persiste_e_e_isolada_por_mes_e_nicho():
    repo = RepoConferenciaMemoria()
    await repo.gravar("cabanas", TEL_A, 2026, 3, Conferencia(True, 30000))
    await repo.gravar("cabanas", TEL_A, 2026, 4, Conferencia(True, 40000))
    await repo.gravar("academia", TEL_A, 2026, 3, Conferencia(True, 50000))

    marco = await repo.carregar("cabanas", 2026, 3)
    assert marco[TEL_A].valor_centavos == 30000
    assert (await repo.carregar("cabanas", 2026, 4))[TEL_A].valor_centavos == 40000
    assert (await repo.carregar("academia", 2026, 3))[TEL_A].valor_centavos == 50000


# --- A pergunta na linha --------------------------------------------------


def _doc(telefone, texto, quando, *, sinais=("data_especifica",)):
    return {
        "nicho": "cabanas",
        "telefone": telefone,
        "texto": texto,
        "intencao": "disponibilidade",
        "lead_quente": True,
        "sinais_lead": list(sinais),
        "resposta": "ok",
        "escalado": False,
        "link_enviado": True,
        "criado_em": quando,
    }


def test_lead_mostra_o_que_a_pessoa_perguntou():
    docs = [
        _doc(TEL_A, "Somos 4, tem vaga dia 12?", datetime(2026, 3, 5, 9, tzinfo=FUSO_BR)),
        _doc(TEL_A, "E dia 13 também?", datetime(2026, 3, 5, 10, tzinfo=FUSO_BR)),
    ]
    lead = agrupar_leads(docs)[0]
    assert lead.pergunta == "Somos 4, tem vaga dia 12?"
    assert lead.perguntas == ["Somos 4, tem vaga dia 12?", "E dia 13 também?"]


def test_primeira_pergunta_independe_da_ordem_do_banco():
    """O Firestore não garante ordem; a linha precisa mostrar a primeira real."""
    cedo = _doc(TEL_A, "primeira", datetime(2026, 3, 5, 9, tzinfo=FUSO_BR))
    tarde = _doc(TEL_A, "segunda", datetime(2026, 3, 5, 18, tzinfo=FUSO_BR))
    assert agrupar_leads([tarde, cedo])[0].pergunta == "primeira"


def test_pergunta_longa_e_encurtada_na_tabela():
    lead = Lead(telefone=TEL_A, perguntas=["x" * 200])
    assert len(lead.pergunta_curta()) == 90
    assert lead.pergunta_curta().endswith("…")
    # O texto inteiro continua disponível para o CSV e o title do HTML.
    assert len(lead.pergunta) == 200


# --- Rotas ----------------------------------------------------------------


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("NICHOS_PAINEL", "cabanas,academia")
    monkeypatch.setenv("COOKIE_SEGURO", "0")
    monkeypatch.setenv("GCP_PROJECT_ID", "")

    import app.config as config_mod
    import app.main as main_mod
    import app.painel.rotas as rotas_mod

    novo = Settings()
    for modulo in (config_mod, main_mod, rotas_mod):
        monkeypatch.setattr(modulo, "settings", novo)

    with TestClient(app) as c:
        agora = datetime(2026, 3, 10, 14, tzinfo=FUSO_BR)
        c.app.state.storage._docs = {
            "m1": _doc(TEL_A, "Somos 4, tem vaga dia 12?", agora),
            "m2": _doc(TEL_B, "Quero reservar pro feriadão", agora + timedelta(hours=1)),
        }
        c.app.state.repo_auth.usuarios = {
            "camily@exemplo.com": a.Usuario(
                "camily@exemplo.com", a.gerar_hash(SENHA_CAMILY),
                a.PAPEL_OPERADOR, nichos=("cabanas",),
            ),
            "adriano@exemplo.com": a.Usuario(
                "adriano@exemplo.com", a.gerar_hash(SENHA_ADRIANO),
                a.PAPEL_LEITOR, nichos=("cabanas",),
            ),
        }
        yield c


def entrar(cliente, email, senha):
    return cliente.post("/painel/login", data={"email": email, "senha": senha})


def csrf_de(cliente):
    return a.csrf_token(cliente.cookies.get(a.COOKIE_SESSAO))


def conferir(cliente, **campos):
    dados = {"csrf": csrf_de(cliente), "nicho": "cabanas", "ano": 2026, "mes": 3}
    dados.update(campos)
    return cliente.post("/painel/conferencia", data=dados, follow_redirects=False)


def test_fechamento_mostra_pergunta_e_sinais(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3")

    assert r.status_code == 200
    assert "Somos 4, tem vaga dia 12?" in r.text
    assert "data_especifica" in r.text
    assert TEL_A in r.text


def test_camily_confirma_reserva_e_a_marcacao_persiste(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = conferir(
        cliente,
        telefone=[TEL_A, TEL_B],
        confirmado=[TEL_A],
        **{f"valor_{TEL_A}": "450,00", f"valor_{TEL_B}": ""},
    )
    assert r.status_code == 303

    # Recarregar a tela tem que trazer a marcação de volta.
    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text
    assert "checked" in pagina
    assert "450,00" in pagina
    assert "R$ 45,00" in pagina  # 10% de R$450


def test_totalizador_soma_o_mes(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(
        cliente,
        telefone=[TEL_A, TEL_B],
        confirmado=[TEL_A, TEL_B],
        **{f"valor_{TEL_A}": "300,00", f"valor_{TEL_B}": "150,00"},
    )
    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text
    assert "R$ 450,00" in pagina
    assert "R$ 45,00" in pagina


def test_confirmada_sem_valor_avisa_na_tela(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(
        cliente,
        telefone=[TEL_A],
        confirmado=[TEL_A],
        **{f"valor_{TEL_A}": ""},
    )
    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text
    assert "sem valor informado" in pagina
    assert "subestimada" in pagina


def test_valor_invalido_nao_grava_nada(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = conferir(
        cliente,
        telefone=[TEL_A],
        confirmado=[TEL_A],
        **{f"valor_{TEL_A}": "quatrocentos"},
    )
    assert r.status_code == 303
    assert "erro=valor_invalido" in r.headers["location"]

    # Seguindo o redirect, a tela mostra o aviso...
    assert "Valor inválido" in cliente.get(r.headers["location"]).text
    # ...e nada foi gravado: a linha continua desmarcada.
    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text
    assert "checked" not in pagina


def test_desmarcar_reserva_tambem_persiste(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": "300,00"})
    conferir(cliente, telefone=[TEL_A], confirmado=[], **{f"valor_{TEL_A}": "300,00"})

    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text
    assert "checked" not in pagina
    assert "R$ 0,00" in pagina


def test_adriano_nao_pode_conferir(cliente):
    """Quem audita o fechamento não edita o que audita."""
    entrar(cliente, "adriano@exemplo.com", SENHA_ADRIANO)
    r = conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A])
    assert r.status_code == 403


def test_adriano_ve_a_tela_sem_os_controles(cliente):
    entrar(cliente, "adriano@exemplo.com", SENHA_ADRIANO)
    pagina = cliente.get("/painel/fechamento?nicho=cabanas&ano=2026&mes=3").text

    assert pagina.count("disabled") >= 3
    assert "Salvar conferência" not in pagina
    assert "somente leitura" in pagina


def test_conferencia_exige_login(cliente):
    r = cliente.post(
        "/painel/conferencia",
        data={"nicho": "cabanas", "ano": 2026, "mes": 3},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_csrf_invalido_e_recusado(cliente):
    """A conferência mexe no valor da comissão; POST forjado não passa."""
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = cliente.post(
        "/painel/conferencia",
        data={"csrf": "forjado", "nicho": "cabanas", "ano": 2026, "mes": 3,
              "telefone": TEL_A, "confirmado": TEL_A},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_nao_da_para_conferir_nicho_alheio(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    r = cliente.post(
        "/painel/conferencia",
        data={"csrf": csrf_de(cliente), "nicho": "academia", "ano": 2026, "mes": 3,
              "telefone": TEL_A, "confirmado": TEL_A},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_alteracao_fica_na_auditoria_com_o_de_para(cliente):
    """O Adriano confere caso a caso: precisa dar para reconstruir a mudança."""
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": "300,00"})
    conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": "450,00"})

    registros = [
        e for e in cliente.app.state.repo_auth.auditoria if e["acao"] == "conferencia"
    ]
    assert len(registros) == 2
    assert registros[0]["quem"] == "camily@exemplo.com"
    assert "sem conferência -> confirmada R$ 300,00" in registros[0]["detalhe"]
    assert "confirmada R$ 300,00 -> confirmada R$ 450,00" in registros[1]["detalhe"]


def test_salvar_sem_mudar_nada_nao_polui_a_auditoria(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    dados = dict(telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": "300,00"})
    conferir(cliente, **dados)
    conferir(cliente, **dados)

    registros = [
        e for e in cliente.app.state.repo_auth.auditoria if e["acao"] == "conferencia"
    ]
    assert len(registros) == 1


def test_csv_traz_a_conferencia_e_o_fechamento(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(
        cliente,
        telefone=[TEL_A, TEL_B],
        confirmado=[TEL_A],
        **{f"valor_{TEL_A}": "450,00", f"valor_{TEL_B}": "",
           f"obs_{TEL_A}": "reserva 3 noites"},
    )

    r = cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3")
    assert r.status_code == 200
    texto = r.text.lstrip("﻿")
    linhas = texto.strip().splitlines()

    assert linhas[0].startswith(
        "telefone;primeiro_contato;ultimo_contato;pergunta;sinais"
    )
    linha_a = next(l for l in linhas if l.startswith(TEL_A))
    assert "Somos 4, tem vaga dia 12?" in linha_a
    assert "sim;450,00;reserva 3 noites" in linha_a
    assert "camily@exemplo.com" in linha_a

    linha_b = next(l for l in linhas if l.startswith(TEL_B))
    assert ";nao;;" in linha_b  # não confirmada, sem valor

    # Rodapé: a conta fecha dentro do arquivo, sem depender da planilha.
    assert "reservas_confirmadas;1" in texto
    assert "valor_confirmado;450,00" in texto
    assert "comissao_10pct;45,00" in texto


def test_csv_avisa_quando_o_total_esta_subestimado(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": ""})

    texto = cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3").text
    assert "ATENCAO" in texto
    assert "subestimada" in texto


def test_csv_usa_virgula_decimal_para_o_excel_somar(cliente):
    entrar(cliente, "camily@exemplo.com", SENHA_CAMILY)
    conferir(cliente, telefone=[TEL_A], confirmado=[TEL_A], **{f"valor_{TEL_A}": "1.234,56"})

    texto = cliente.get("/painel/fechamento.csv?nicho=cabanas&ano=2026&mes=3").text
    assert "1234,56" in texto
    assert "R$" not in texto  # com "R$" o Excel trata a coluna como texto
