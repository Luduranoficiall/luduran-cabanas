"""Rotas do painel.

Regra que vale para toda rota autenticada: o nicho pedido na querystring é
sempre conferido contra os nichos do usuário, no servidor. Trocar `?nicho=`
na URL não abre dado de outro cliente.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..config import settings
from . import auth as a
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

    return templates.TemplateResponse(
        request,
        "fechamento.html",
        {
            "usuario": usuario,
            "nicho": nicho_ok,
            "nichos": usuario.nichos_visiveis(list(settings.nichos_painel)),
            "ano": ano,
            "mes": mes,
            "leads": agrupar_leads(docs),
        },
    )


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

    # Exportar dado pessoal para fora do sistema é o evento que mais importa
    # na trilha da LGPD.
    await a.auditar(
        request.app.state.repo_auth,
        quem=usuario.email,
        acao="exportou_csv",
        detalhe=f"{nicho_ok} {ano}-{mes:02d} ({len(leads)} leads)",
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
            "mensagens",
            "sinais",
            "link_enviado",
            "escalado",
        ]
    )
    for lead in leads:
        escritor.writerow(
            [
                lead.telefone,
                _data_br(lead.primeiro_contato),
                _data_br(lead.ultimo_contato),
                lead.mensagens,
                lead.sinais_texto,
                "sim" if lead.link_enviado else "nao",
                "sim" if lead.escalado else "nao",
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


templates.env.filters["data_br"] = _data_br
