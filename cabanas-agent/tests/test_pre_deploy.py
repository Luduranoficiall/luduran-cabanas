"""Conferência pré-deploy.

O valor deste script é pegar credencial errada em segundos, em vez de um ciclo
de deploy inteiro. Os testes cobrem a parte que decide — os testes de rede não
têm como rodar aqui, e nem deveriam.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.config import Settings

RAIZ = Path(__file__).resolve().parent.parent


def _carregar():
    caminho = RAIZ / "scripts" / "pre_deploy.py"
    spec = importlib.util.spec_from_file_location("pre_deploy", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["pre_deploy"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


pre_deploy = _carregar()

SISTEMA = "+55 54 99910-3545"
ID_META = "123456789012345"


def cfg(**extra):
    base = dict(
        gemini_api_key="x",
        whatsapp_token="x",
        whatsapp_verify_token="x",
        whatsapp_phone_number_id=ID_META,
        whatsapp_phone_number=SISTEMA,
        escalation_number="5554984487198",
        cabanas={str(n): f"https://airbnb.com.br/h/1992cabana{n}" for n in range(1, 6)},
        cabanas_sem_link=[],
    )
    base.update(extra)
    return Settings(**base)


# --- O erro que mais custa tempo -----------------------------------------


def test_telefone_no_lugar_do_id_e_pego(capsys):
    """O engano clássico: colar o número em WHATSAPP_PHONE_NUMBER_ID."""
    assert pre_deploy.checar_numeros(cfg(whatsapp_phone_number_id="5554999103545")) is False
    assert "TELEFONE no lugar do ID" in capsys.readouterr().out


def test_id_nao_numerico_e_pego(capsys):
    assert pre_deploy.checar_numeros(cfg(whatsapp_phone_number_id="abc")) is False
    assert "não é numérico" in capsys.readouterr().out


def test_id_correto_passa(capsys):
    assert pre_deploy.checar_numeros(cfg()) is True
    assert ID_META in capsys.readouterr().out


# --- Escalação ------------------------------------------------------------


def test_escalacao_para_si_mesmo_barra(capsys):
    conf = cfg(escalation_number="5554999103545")  # = número do sistema
    assert pre_deploy.checar_numeros(conf) is False
    assert "mesmo número do sistema" in capsys.readouterr().out


def test_sem_template_avisa_mas_nao_barra(capsys):
    """Dá para subir sem o template; o aviso é que não chega."""
    assert pre_deploy.checar_numeros(cfg(escalation_template="")) is True
    saida = capsys.readouterr().out
    assert "131047" in saida
    assert "Não bloqueia o deploy" in saida


def test_com_template_nao_avisa(capsys):
    assert pre_deploy.checar_numeros(cfg(escalation_template="escalacao_cabanas")) is True
    assert "131047" not in capsys.readouterr().out


# --- Configuração ---------------------------------------------------------


def test_variaveis_faltando_sao_listadas(capsys):
    assert pre_deploy.checar_config(cfg(gemini_api_key="", whatsapp_token="")) is False
    saida = capsys.readouterr().out
    assert "GEMINI_API_KEY" in saida
    assert "WHATSAPP_TOKEN" in saida


def test_config_completa_passa():
    assert pre_deploy.checar_config(cfg()) is True


def test_cabana_sem_link_barra_o_deploy(capsys):
    assert pre_deploy.checar_cabanas(cfg(cabanas_sem_link=["6"])) is False
    assert "sem link cadastrado" in capsys.readouterr().out


def test_cinco_cabanas_passam(capsys):
    assert pre_deploy.checar_cabanas(cfg()) is True
    assert "5 no ar" in capsys.readouterr().out


# --- Saída ----------------------------------------------------------------


@pytest.mark.parametrize("quebrado", ["gemini_api_key", "whatsapp_token"])
def test_sem_credencial_nao_tenta_rede(monkeypatch, capsys, quebrado):
    """Sem credencial, bater na rede só geraria erro confuso."""
    monkeypatch.setattr(pre_deploy, "Settings", lambda: cfg(**{quebrado: ""}))
    assert pre_deploy.main() == 1
    assert "Pulei os testes de rede" in capsys.readouterr().out
