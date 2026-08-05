"""Testes do gerador da página (item 1.1 do roadmap).

O que precisa continuar verdadeiro:
- a página aprovada pelo cliente não muda, só ganha a seção nova;
- a seção sai da mesma configuração do agente, então site e atendimento não
  divergem;
- cabana sem link cadastrado não aparece — mesma trava do agente.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.config import Settings

RAIZ = Path(__file__).resolve().parent.parent.parent
TEMPLATE = RAIZ / "site" / "index.template.html"


def _carregar_gerador():
    caminho = RAIZ / "cabanas-agent" / "scripts" / "gerar_site.py"
    spec = importlib.util.spec_from_file_location("gerar_site", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["gerar_site"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


gerar_site = _carregar_gerador()


@pytest.fixture
def cfg_quatro():
    return Settings(
        cabanas={
            "1": "https://airbnb.com.br/h/1992cabana1",
            "2": "https://airbnb.com.br/h/1992cabana2",
            "4": "https://airbnb.com.br/h/1992cabana4",
            "5": "https://airbnb.com.br/h/1992cabana5",
        }
    )


def test_pagina_gerada_traz_as_cabanas_da_config(cfg_quatro):
    html = gerar_site.gerar(cfg_quatro)
    for numero in ("1", "2", "4", "5"):
        assert f"https://airbnb.com.br/h/1992cabana{numero}" in html
        assert f"Cabana {numero}" in html
    assert "4 cabanas para reservar" in html


def _secao_cabanas(html: str) -> str:
    """Só a seção gerada.

    As asserções sobre "o que está no ar" precisam olhar a seção, não a página
    inteira: a conversa de exemplo aprovada pelo cliente cita um link fixo, e
    ele não é gerado por aqui (ver test_demo_aprovada_cita_a_cabana_3).
    """
    inicio = html.index('<section class="cabanas">')
    return html[inicio : html.index("</section>", inicio)]


def test_cabana_sem_link_nao_aparece_na_pagina(cfg_quatro):
    """Mesma trava do agente: nada de link chutado na mão do cliente."""
    secao = _secao_cabanas(gerar_site.gerar(cfg_quatro))
    assert "Cabana 3" not in secao
    assert "1992cabana3" not in secao


def test_demo_aprovada_cita_a_cabana_3():
    """Documenta uma inconsistência que precisa de decisão do cliente.

    A conversa de exemplo, aprovada como está, manda
    airbnb.com.br/h/1992cabana3 — anúncio que ainda não existe. Quem clicar ali
    na demo cai em página quebrada.

    Não mexi na demo por conta própria: é conteúdo aprovado. Este teste existe
    para o dia em que a decisão for tomada — quando o link da cabana 3 for
    criado, ele passa a valer e nada muda; se a demo for trocada para outra
    cabana, este teste falha e lembra de atualizar a nota.
    """
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "airbnb.com.br/h/1992cabana3" in template


def test_ligar_a_cabana_3_aparece_na_pagina(monkeypatch):
    monkeypatch.setenv("CABANAS", "1,2,3,4,5")
    monkeypatch.setenv("CABANA_URLS", "3=https://airbnb.com.br/h/link-novo-3")

    html = gerar_site.gerar(Settings())
    assert "https://airbnb.com.br/h/link-novo-3" in html
    assert "5 cabanas para reservar" in html


def test_a_demo_aprovada_continua_intacta(cfg_quatro):
    """A conversa e o comparativo que o cliente aprovou não podem sumir."""
    html = gerar_site.gerar(cfg_quatro)
    assert "Veja o atendimento automático das cabanas em ação" in html
    assert "respondido por IA" in html
    assert "R$300 de implementação" in html
    assert "~4 segundos" in html
    assert "reproduzir exemplo" in html


def test_geracao_e_deterministica(cfg_quatro):
    """Gerar duas vezes não pode sujar o diff do commit."""
    assert gerar_site.gerar(cfg_quatro) == gerar_site.gerar(cfg_quatro)


def test_marcador_nao_sobra_no_html(cfg_quatro):
    assert gerar_site.MARCADOR not in gerar_site.gerar(cfg_quatro)


def test_index_commitado_esta_atualizado(cfg_quatro):
    """Falha se alguém editar o template e esquecer de rodar o gerador."""
    atual = (RAIZ / "index.html").read_text(encoding="utf-8")
    assert atual == gerar_site.gerar(cfg_quatro), (
        "index.html está desatualizado — rode: "
        "python cabanas-agent/scripts/gerar_site.py"
    )


def test_link_abre_em_nova_aba_com_rel_seguro(cfg_quatro):
    html = gerar_site.gerar(cfg_quatro)
    assert 'target="_blank" rel="noopener"' in html


def test_sem_foto_usa_bloco_neutro(cfg_quatro):
    """As fotos ainda não chegaram; o grid não pode quebrar por isso."""
    html = gerar_site.gerar(cfg_quatro)
    assert "cabana-foto-vazia" in html


def test_template_tem_o_marcador():
    assert gerar_site.MARCADOR in TEMPLATE.read_text(encoding="utf-8")
