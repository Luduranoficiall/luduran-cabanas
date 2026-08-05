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
def cfg_cinco():
    """As cinco cabanas no ar — link da 3 confirmado pelo cliente."""
    return Settings(
        cabanas={
            str(n): f"https://airbnb.com.br/h/1992cabana{n}" for n in range(1, 6)
        }
    )


def test_pagina_gerada_traz_as_cabanas_da_config(cfg_cinco):
    html = gerar_site.gerar(cfg_cinco)
    for numero in ("1", "2", "3", "4", "5"):
        assert f"https://airbnb.com.br/h/1992cabana{numero}" in html
        assert f"Cabana {numero}" in html
    assert "5 cabanas para reservar" in html


def _secao_cabanas(html: str) -> str:
    """Só a seção gerada.

    As asserções sobre "o que está no ar" precisam olhar a seção, não a página
    inteira: a conversa de exemplo aprovada pelo cliente cita um link fixo, e
    ele não é gerado por aqui (ver test_link_da_demo_aprovada_agora_e_valido).
    """
    inicio = html.index('<section class="cabanas">')
    return html[inicio : html.index("</section>", inicio)]


def test_cabana_sem_link_nao_aparece_na_pagina():
    """Mesma trava do agente: nada de link chutado na mão do cliente."""
    cfg = Settings(cabanas={"1": "https://airbnb.com.br/h/1992cabana1"})
    secao = _secao_cabanas(gerar_site.gerar(cfg))
    assert "Cabana 2" not in secao
    assert "1992cabana2" not in secao


def test_link_da_demo_aprovada_agora_e_valido():
    """A conversa de exemplo cita a cabana 3, e o anúncio dela já existe.

    Enquanto o anúncio não existia, esse link levava a página quebrada. Com o
    link confirmado pelo cliente, a demo passou a bater com a operação. O teste
    fica para travar as duas pontas: se a cabana 3 sair do ar em CABANAS, a
    demo continua apontando para ela e alguém precisa decidir o que fazer.
    """
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "airbnb.com.br/h/1992cabana3" in template
    assert "3" in Settings().cabanas, (
        "a demo aprovada linka a cabana 3, mas ela não está no ar em CABANAS"
    )


def test_ligar_a_cabana_3_aparece_na_pagina(monkeypatch):
    monkeypatch.setenv("CABANAS", "1,2,3,4,5")
    monkeypatch.setenv("CABANA_URLS", "3=https://airbnb.com.br/h/link-novo-3")

    html = gerar_site.gerar(Settings())
    assert "https://airbnb.com.br/h/link-novo-3" in html
    assert "5 cabanas para reservar" in html


def test_a_demo_aprovada_continua_intacta(cfg_cinco):
    """A conversa e o comparativo que o cliente aprovou não podem sumir."""
    html = gerar_site.gerar(cfg_cinco)
    assert "Veja o atendimento automático das cabanas em ação" in html
    assert "respondido por IA" in html
    assert "R$300 de implementação" in html
    assert "~4 segundos" in html
    assert "reproduzir exemplo" in html


def test_geracao_e_deterministica(cfg_cinco):
    """Gerar duas vezes não pode sujar o diff do commit."""
    assert gerar_site.gerar(cfg_cinco) == gerar_site.gerar(cfg_cinco)


def test_marcador_nao_sobra_no_html(cfg_cinco):
    assert gerar_site.MARCADOR not in gerar_site.gerar(cfg_cinco)


def test_index_commitado_esta_atualizado(cfg_cinco):
    """Falha se alguém editar o template e esquecer de rodar o gerador."""
    atual = (RAIZ / "index.html").read_text(encoding="utf-8")
    assert atual == gerar_site.gerar(cfg_cinco), (
        "index.html está desatualizado — rode: "
        "python cabanas-agent/scripts/gerar_site.py"
    )


def test_link_abre_em_nova_aba_com_rel_seguro(cfg_cinco):
    html = gerar_site.gerar(cfg_cinco)
    assert 'target="_blank" rel="noopener"' in html


# As duas asserções abaixo apontam FOTOS para um diretório temporário de
# propósito. Se dependessem do que está commitado em assets/cabanas/, elas
# passariam a falhar sozinhas no dia em que as fotos reais entrassem.


def test_sem_foto_usa_bloco_neutro(cfg_cinco, tmp_path, monkeypatch):
    """Cabana sem foto não pode quebrar o grid."""
    monkeypatch.setattr(gerar_site, "FOTOS", tmp_path)
    html = gerar_site.gerar(cfg_cinco)
    assert "cabana-foto-vazia" in html
    assert "<img" not in _secao_cabanas(html)


def test_foto_de_capa_e_usada_quando_existe(cfg_cinco, tmp_path, monkeypatch):
    """Com a foto no lugar certo, o cartão passa a usar a imagem."""
    monkeypatch.setattr(gerar_site, "FOTOS", tmp_path)
    monkeypatch.setattr(gerar_site, "RAIZ", tmp_path.parent)

    pasta = tmp_path / "cabana3"
    pasta.mkdir()
    (pasta / "01-capa.jpg").write_bytes(b"fake")
    (pasta / "02-quarto.jpg").write_bytes(b"fake")

    secao = _secao_cabanas(gerar_site.gerar(cfg_cinco))
    # A capa é a primeira em ordem alfabética — daí o prefixo 01-.
    assert "01-capa.jpg" in secao
    assert "02-quarto.jpg" not in secao
    assert 'loading="lazy"' in secao


def test_extensao_maiuscula_tambem_e_aceita(cfg_cinco, tmp_path, monkeypatch):
    """Foto vinda de celular às vezes chega como .JPG."""
    monkeypatch.setattr(gerar_site, "FOTOS", tmp_path)
    monkeypatch.setattr(gerar_site, "RAIZ", tmp_path.parent)

    pasta = tmp_path / "cabana1"
    pasta.mkdir()
    (pasta / "01-capa.JPG").write_bytes(b"fake")

    assert "01-capa.JPG" in _secao_cabanas(gerar_site.gerar(cfg_cinco))


def test_template_tem_o_marcador():
    assert gerar_site.MARCADOR in TEMPLATE.read_text(encoding="utf-8")
