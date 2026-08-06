"""Retenção e anonimização (LGPD).

A regra vem do DeskcommCRM, que o cliente já opera: anonimizar em vez de
apagar. O que estes testes protegem é o equilíbrio entre as duas coisas que
não podem cair juntas — o dado pessoal precisa sair, e o número do fechamento
precisa continuar de pé.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.painel.repositorio import agrupar_leads, calcular_metricas
from app.retencao import (
    PREFIXO_ANONIMO,
    apelido,
    campos_anonimizados,
    corte,
    elegiveis,
    ja_anonimizado,
)

SAL = "sal-de-teste-nao-usar-em-producao"
AGORA = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


def doc(telefone="5554999990001", dias_atras=0, **extra):
    d = {
        "nicho": "cabanas",
        "telefone": telefone,
        "texto": "Somos 4 pessoas, tem vaga dia 12?",
        "resposta": "Temos sim! A diária é R$150,00",
        "intencao": "disponibilidade",
        "lead_quente": True,
        "sinais_lead": ["data_especifica", "numero_pessoas"],
        "escalado": False,
        "link_enviado": True,
        "criado_em": AGORA - timedelta(days=dias_atras),
    }
    d.update(extra)
    return d


# --- Apelido --------------------------------------------------------------


def test_apelido_e_estavel():
    """O mesmo telefone tem que dar sempre o mesmo apelido.

    É isso que mantém "pessoas atendidas" contando gente, e não linhas.
    """
    assert apelido("5554999990001", SAL) == apelido("5554999990001", SAL)


def test_telefones_diferentes_dao_apelidos_diferentes():
    assert apelido("5554999990001", SAL) != apelido("5554999990002", SAL)


def test_sal_diferente_muda_o_apelido():
    """Sem sal, o hash de um celular brasileiro cai por força bruta."""
    assert apelido("5554999990001", "sal-a") != apelido("5554999990001", "sal-b")


def test_apelido_nao_contem_o_telefone():
    a = apelido("5554999990001", SAL)
    assert "5554999990001" not in a
    assert "99999" not in a
    assert a.startswith(PREFIXO_ANONIMO)


# --- O que sai e o que fica ----------------------------------------------


def test_dado_pessoal_sai():
    original = doc()
    novo = {**original, **campos_anonimizados(original, SAL, AGORA)}

    assert novo["telefone"].startswith(PREFIXO_ANONIMO)
    assert "5554999990001" not in str(novo)
    assert novo["texto"] == ""
    assert novo["resposta"] == ""
    assert novo["anonimizado_em"] == AGORA


def test_base_do_fechamento_fica():
    """Anonimizar não pode derrubar o número que sustenta os 10%."""
    original = doc()
    novo = {**original, **campos_anonimizados(original, SAL, AGORA)}

    assert novo["nicho"] == "cabanas"
    assert novo["intencao"] == "disponibilidade"
    assert novo["lead_quente"] is True
    assert novo["sinais_lead"] == ["data_especifica", "numero_pessoas"]
    assert novo["link_enviado"] is True
    assert novo["criado_em"] == original["criado_em"]


def test_metricas_do_mes_sobrevivem_a_anonimizacao():
    """O caso que importa: o painel continua dando o mesmo número."""
    docs = [
        doc(telefone="5554999990001"),
        doc(telefone="5554999990001", texto="e dia 13?"),
        doc(telefone="5554999990002", lead_quente=False, sinais_lead=[]),
    ]
    antes = calcular_metricas(docs)

    anonimos = [{**d, **campos_anonimizados(d, SAL, AGORA)} for d in docs]
    depois = calcular_metricas(anonimos)

    assert (antes.pessoas, antes.leads_quentes) == (2, 1)
    assert (depois.pessoas, depois.leads_quentes) == (antes.pessoas, antes.leads_quentes)
    assert depois.links_enviados == antes.links_enviados


def test_leads_continuam_agrupando_por_pessoa():
    docs = [doc(telefone="5554999990001"), doc(telefone="5554999990001")]
    anonimos = [{**d, **campos_anonimizados(d, SAL, AGORA)} for d in docs]

    leads = agrupar_leads(anonimos)
    assert len(leads) == 1
    assert leads[0].mensagens == 2
    assert leads[0].sinais == {"data_especifica", "numero_pessoas"}


def test_o_que_se_perde_e_o_texto():
    """Documenta a troca: o "por quê" do lead vira só os sinais.

    Por isso o prazo de retenção tem que ser maior que o ciclo de fechamento.
    """
    anonimo = {**doc(), **campos_anonimizados(doc(), SAL, AGORA)}
    leads = agrupar_leads([anonimo])
    assert leads[0].pergunta == "—"
    assert leads[0].sinais_texto == "data_especifica, numero_pessoas"


# --- Quem entra no corte --------------------------------------------------


def test_so_o_que_passou_do_prazo():
    docs = [doc(dias_atras=400), doc(dias_atras=100), doc(dias_atras=1)]
    alvos = elegiveis(docs, dias=365, agora=AGORA)

    assert len(alvos) == 1
    assert alvos[0]["criado_em"] == AGORA - timedelta(days=400)


def test_prazo_zero_nao_anonimiza_nada():
    """Desligado é desligado — nada de apagar dado por padrão."""
    assert elegiveis([doc(dias_atras=9999)], dias=0, agora=AGORA) == []


def test_nao_reanonimiza_o_que_ja_foi():
    ja = {**doc(dias_atras=400), **campos_anonimizados(doc(), SAL, AGORA)}
    assert elegiveis([ja], dias=365, agora=AGORA) == []


def test_reconhece_anonimizado_pelo_apelido():
    """Mesmo sem a marca de data, o prefixo denuncia."""
    assert ja_anonimizado({"telefone": f"{PREFIXO_ANONIMO}abc123"}) is True
    assert ja_anonimizado({"telefone": "5554999990001"}) is False


def test_documento_sem_data_e_ignorado():
    assert elegiveis([{"telefone": "x", "criado_em": None}], 365, AGORA) == []


def test_data_sem_fuso_nao_quebra():
    sem_fuso = doc()
    sem_fuso["criado_em"] = datetime(2025, 1, 1, 12)
    assert len(elegiveis([sem_fuso], dias=365, agora=AGORA)) == 1


def test_corte_e_o_prazo_para_tras():
    assert corte(365, AGORA) == AGORA - timedelta(days=365)


# --- Configuração ---------------------------------------------------------


def test_retencao_vem_desligada(monkeypatch):
    """Prazo é decisão de negócio; um padrão errado apaga dado sozinho."""
    monkeypatch.delenv("RETENCAO_DIAS", raising=False)
    assert Settings().retencao_dias == 0


def test_retencao_e_configuravel(monkeypatch):
    monkeypatch.setenv("RETENCAO_DIAS", "365")
    monkeypatch.setenv("RETENCAO_SAL", SAL)
    cfg = Settings()
    assert cfg.retencao_dias == 365
    assert cfg.retencao_sal == SAL
