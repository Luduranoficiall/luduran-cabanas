"""Rotas do painel.

Regra que vale para toda rota autenticada: o nicho pedido na querystring é
sempre conferido contra os nichos do usuário, no servidor. Trocar `?nicho=`
na URL não abre dado de outro cliente.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..config import settings
from . import auth as a
from .conferencia import Conferencia, calcular_totais, formatar_reais, parse_reais
from .repositorio import (
    FUSO_BR,
    agrupar_leads,
    calcular_metricas,
    fim_do_mes,
    inicio_do_mes,
    mes_atual,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/painel")

from pathlib import Path  # noqa: E402

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ip(request: Request) -> str:
    # No Cloud Run o IP real vem no X-Forwarded-For; o primeiro é o cliente.
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _usuario(request: Request):
    return await a.usuario_da_sessao(
        request.app.state.repo_auth, request.cookies.get(a.COOKIE_SESSAO)
    )


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/painel/login", status_code=303)


def _resolver_nicho(usuario, pedido: str | None) -> str | None:
    """Nicho efetivo da consulta, ou None se o usuário não puder vê-lo."""
    disponiveis = usuario.nichos_visiveis(list(settings.nichos_painel))
    if not disponiveis:
        return None
    if pedido is None:
        return disponiveis[0]
    if not usuario.pode_ver(pedido):
        return None
    return pedido


# --- Login ----------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def form_login(request: Request):
    if await _usuario(request):
        return RedirectResponse("/painel/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"erro": None})


@router.post("/login")
async def fazer_login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
):
    repo = request.app.state.repo_auth
    tentativas = request.app.state.tentativas_login
    ip = _ip(request)
    chave = f"{email.strip().lower()}|{ip}"

    if tentativas.bloqueado(chave):
        await a.auditar(repo, quem=email, acao="login_bloqueado", ip=ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"erro": "Muitas tentativas. Aguarde alguns minutos."},
            status_code=429,
        )

    usuario = await a.autenticar(repo, email, senha)
    if usuario is None:
        tentativas.registrar_falha(chave)
        await a.auditar(repo, quem=email, acao="login_falhou", ip=ip)
        # Mensagem única de propósito: dizer "usuário não existe" entregaria
        # quem tem conta a quem estiver testando e-mails.
        return templates.TemplateResponse(
            request,
            "login.html",
            {"erro": "E-mail ou senha inválidos."},
            status_code=401,
        )

    tentativas.limpar(chave)
    token = await a.abrir_sessao(repo, usuario)
    await a.auditar(repo, quem=usuario.email, acao="login", ip=ip)

    resposta = RedirectResponse("/painel/", status_code=303)
    resposta.set_cookie(
        a.COOKIE_SESSAO,
        token,
        httponly=True,
        secure=settings.cookie_seguro,
        samesite="lax",
        max_age=int(a.DURACAO_SESSAO.total_seconds()),
        path="/painel",
    )
    return resposta


@router.post("/logout")
async def logout(request: Request):
    await a.fechar_sessao(
        request.app.state.repo_auth, request.cookies.get(a.COOKIE_SESSAO)
    )
    resposta = RedirectResponse("/painel/login", status_code=303)
    resposta.delete_cookie(a.COOKIE_SESSAO, path="/painel")
    return resposta


# --- Painel ---------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    nicho: str | None = Query(None),
    ano: int | None = Query(None),
    mes: int | None = Query(None),
):
    usuario = await _usuario(request)
    if usuario is None:
        return _redirect_login()

    nicho_ok = _resolver_nicho(usuario, nicho)
    if nicho_ok is None:
        return Response("Sem acesso a este nicho.", status_code=403)

    ano_atual, mes_atual_ = mes_atual()
    ano, mes = ano or ano_atual, mes or mes_atual_
    inicio, fim = inicio_do_mes(ano, mes), fim_do_mes(ano, mes)

    docs = await request.app.state.repo_painel.docs_do_periodo(nicho_ok, inicio, fim)

    return templates.TemplateResponse(
        request,
        "painel.html",
        {
            "usuario": usuario,
            "nicho": nicho_ok,
            "nichos": usuario.nichos_visiveis(list(settings.nichos_painel)),
            "ano": ano,
            "mes": mes,
            "metricas": calcular_metricas(docs),
        },
    )


@router.get("/fechamento", response_class=HTMLResponse)
async def fechamento(
    request: Request,
    nicho: str | None = Query(None),
    ano: int | None = Query(None),
    mes: int | None = Query(None),
):
    usuario = await _usuario(request)
    if usuario is None:
        return _redirect_login()

    nicho_ok = _resolver_nicho(usuario, nicho)
    if nicho_ok is None:
        return Response("Sem acesso a este nicho.", status_code=403)

    ano_atual, mes_atual_ = mes_atual()
    ano, mes = ano or ano_atual, mes or mes_atual_
    docs = await request.app.state.repo_painel.docs_do_periodo(
        nicho_ok, inicio_do_mes(ano, mes), fim_do_mes(ano, mes)
    )
    leads = agrupar_leads(docs)
    conferencias = await request.app.state.repo_conferencia.carregar(nicho_ok, ano, mes)

    return templates.TemplateResponse(
        request,
        "fechamento.html",
        {
            "usuario": usuario,
            "nicho": nicho_ok,
            "nichos": usuario.nichos_visiveis(list(settings.nichos_painel)),
            "ano": ano,
            "mes": mes,
            "leads": leads,
            "conferencias": conferencias,
            "totais": calcular_totais(leads, conferencias, settings.comissao_percentual),
            "pode_conferir": usuario.pode_conferir(nicho_ok),
            "csrf": a.csrf_token(request.cookies.get(a.COOKIE_SESSAO, "")),
            "erro": request.query_params.get("erro"),
            "salvo": request.query_params.get("salvo"),
        },
    )


@router.post("/conferencia")
async def salvar_conferencia(request: Request):
    """Grava a conferência: quais leads viraram reserva de fato.

    Recebe a tabela inteira de uma vez — a Camily revisa o mês e salva no fim,
    em vez de um request por linha.
    """
    usuario = await _usuario(request)
    if usuario is None:
        return _redirect_login()

    form = await request.form()
    nicho_ok = _resolver_nicho(usuario, form.get("nicho"))
    if nicho_ok is None or not usuario.pode_conferir(nicho_ok):
        # O Adriano audita o fechamento; deixá-lo editar o que audita tiraria
        # o sentido da auditoria.
        return Response("Sem permissão para conferir.", status_code=403)

    if not a.csrf_valido(request.cookies.get(a.COOKIE_SESSAO), form.get("csrf")):
        return Response("Requisição inválida.", status_code=403)

    try:
        ano, mes = int(form.get("ano")), int(form.get("mes"))
    except (TypeError, ValueError):
        return Response("Competência inválida.", status_code=400)

    confirmados = set(form.getlist("confirmado"))
    agora = datetime.now(timezone.utc)
    anteriores = await request.app.state.repo_conferencia.carregar(nicho_ok, ano, mes)
    alteradas = 0

    for telefone in form.getlist("telefone"):
        try:
            valor = parse_reais(form.get(f"valor_{telefone}"))
        except ValueError:
            # Volta para a tela com o aviso, sem gravar nada pela metade.
            return RedirectResponse(
                f"/painel/fechamento?nicho={nicho_ok}&ano={ano}&mes={mes}"
                f"&erro=valor_invalido",
                status_code=303,
            )

        nova = Conferencia(
            confirmado=telefone in confirmados,
            valor_centavos=valor,
            observacao=(form.get(f"obs_{telefone}") or "").strip()[:200],
            conferido_por=usuario.email,
            conferido_em=agora,
        )
        antiga = anteriores.get(telefone)
        if antiga is not None and (
            antiga.confirmado,
            antiga.valor_centavos,
            antiga.observacao,
        ) == (nova.confirmado, nova.valor_centavos, nova.observacao):
            continue  # nada mudou: não suja a auditoria nem reescreve o autor

        await request.app.state.repo_conferencia.gravar(
            nicho_ok, telefone, ano, mes, nova
        )
        alteradas += 1
        # O Adriano vai conferir caso a caso: o de-para precisa estar gravado.
        await a.auditar(
            request.app.state.repo_auth,
            quem=usuario.email,
            acao="conferencia",
            detalhe=(
                f"{nicho_ok} {ano}-{mes:02d} {telefone}: "
                f"{_resumo(antiga)} -> {_resumo(nova)}"
            ),
            ip=_ip(request),
        )

    return RedirectResponse(
        f"/painel/fechamento?nicho={nicho_ok}&ano={ano}&mes={mes}&salvo={alteradas}",
        status_code=303,
    )


def _resumo(conf: Conferencia | None) -> str:
    if conf is None:
        return "sem conferência"
    marca = "confirmada" if conf.confirmado else "não confirmada"
    return f"{marca} {formatar_reais(conf.valor_centavos)}"


@router.get("/fechamento.csv")
async def fechamento_csv(
    request: Request,
    nicho: str | None = Query(None),
    ano: int | None = Query(None),
    mes: int | None = Query(None),
):
    usuario = await _usuario(request)
    if usuario is None:
        return _redirect_login()

    nicho_ok = _resolver_nicho(usuario, nicho)
    if nicho_ok is None:
        return Response("Sem acesso a este nicho.", status_code=403)

    ano_atual, mes_atual_ = mes_atual()
    ano, mes = ano or ano_atual, mes or mes_atual_
    docs = await request.app.state.repo_painel.docs_do_periodo(
        nicho_ok, inicio_do_mes(ano, mes), fim_do_mes(ano, mes)
    )
    leads = agrupar_leads(docs)
    conferencias = await request.app.state.repo_conferencia.carregar(nicho_ok, ano, mes)
    totais = calcular_totais(leads, conferencias, settings.comissao_percentual)

    # Exportar dado pessoal para fora do sistema é o evento que mais importa
    # na trilha da LGPD.
    await a.auditar(
        request.app.state.repo_auth,
        quem=usuario.email,
        acao="exportou_csv",
        detalhe=(
            f"{nicho_ok} {ano}-{mes:02d} ({len(leads)} leads, "
            f"{totais.confirmadas} confirmadas)"
        ),
        ip=_ip(request),
    )

    buffer = io.StringIO()
    # BOM para o Excel em português abrir acento corretamente.
    buffer.write("﻿")
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(
        [
            "telefone",
            "primeiro_contato",
            "ultimo_contato",
            "pergunta",
            "sinais",
            "mensagens",
            "link_enviado",
            "escalado",
            "reserva_confirmada",
            "valor_reserva",
            "observacao",
            "conferido_por",
            "conferido_em",
        ]
    )
    for lead in leads:
        conf = conferencias.get(lead.telefone)
        escritor.writerow(
            [
                lead.telefone,
                _data_br(lead.primeiro_contato),
                _data_br(lead.ultimo_contato),
                lead.pergunta,
                lead.sinais_texto,
                lead.mensagens,
                "sim" if lead.link_enviado else "nao",
                "sim" if lead.escalado else "nao",
                "sim" if conf and conf.confirmado else "nao",
                _valor_csv(conf),
                conf.observacao if conf else "",
                conf.conferido_por if conf else "",
                _data_br(conf.conferido_em) if conf else "",
            ]
        )

    # Rodapé com o fechamento. Vai no próprio arquivo para a conta não depender
    # de ninguém refazer a soma na planilha.
    escritor.writerow([])
    escritor.writerow(["leads_quentes", totais.leads_quentes])
    escritor.writerow(["reservas_confirmadas", totais.confirmadas])
    escritor.writerow(["valor_confirmado", _centavos_csv(totais.valor_total_centavos)])
    escritor.writerow(
        [f"comissao_{totais.percentual:g}pct", _centavos_csv(totais.comissao_centavos)]
    )
    if not totais.total_confiavel:
        escritor.writerow(
            [
                "ATENCAO",
                f"{totais.confirmadas_sem_valor} reserva(s) confirmada(s) sem valor "
                f"informado — a comissao acima esta subestimada",
            ]
        )

    nome = f"fechamento-{nicho_ok}-{ano}-{mes:02d}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/telefone/{telefone}", response_class=HTMLResponse)
async def historico_telefone(
    request: Request, telefone: str, nicho: str | None = Query(None)
):
    usuario = await _usuario(request)
    if usuario is None:
        return _redirect_login()

    nicho_ok = _resolver_nicho(usuario, nicho)
    if nicho_ok is None:
        return Response("Sem acesso a este nicho.", status_code=403)

    docs = await request.app.state.repo_painel.docs_do_telefone(nicho_ok, telefone)
    return templates.TemplateResponse(
        request,
        "telefone.html",
        {
            "usuario": usuario,
            "nicho": nicho_ok,
            "nichos": usuario.nichos_visiveis(list(settings.nichos_painel)),
            "telefone": telefone,
            "docs": docs,
        },
    )


def _data_br(valor: datetime | None) -> str:
    if valor is None:
        return ""
    return valor.astimezone(FUSO_BR).strftime("%d/%m/%Y %H:%M")


def _centavos_csv(centavos: int) -> str:
    """Número com vírgula decimal, sem "R$" — assim o Excel soma a coluna."""
    return f"{centavos // 100},{centavos % 100:02d}"


def _valor_csv(conf) -> str:
    if conf is None or conf.valor_centavos is None:
        return ""
    return _centavos_csv(conf.valor_centavos)


templates.env.filters["data_br"] = _data_br
