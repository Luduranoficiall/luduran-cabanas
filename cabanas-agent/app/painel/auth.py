"""Autenticação e autorização do painel.

O painel expõe telefone de cliente final — dado pessoal sob a LGPD. Por isso
login de verdade, não link secreto:

- senha com scrypt e sal por usuário (nunca em texto puro, nunca reversível);
- sessão do lado do servidor, para conseguir revogar; o cookie carrega só um
  token opaco;
- no banco fica o SHA-256 do token, não o token. Vazamento da base não dá
  sessão válida a ninguém;
- cookie HttpOnly + SameSite=Lax + Secure, então JavaScript não lê e site de
  terceiro não reaproveita;
- toda leitura é filtrada pelos nichos do usuário, no servidor. Trocar o nicho
  na URL não dá acesso a dado de outro cliente;
- login e exportação vão para trilha de auditoria — a LGPD pede saber quem
  acessou dado pessoal e quando.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

logger = logging.getLogger(__name__)

COOKIE_SESSAO = "painel_sessao"
DURACAO_SESSAO = timedelta(hours=8)

PAPEL_ADMIN = "admin"
# Lê e marca conferência de reserva. É o papel da Camily: ela precisa gravar
# quais leads viraram reserva de fato.
PAPEL_OPERADOR = "operador"
# Só lê. É o papel do Adriano: ele confere o fechamento, não edita.
PAPEL_LEITOR = "leitor"

PAPEIS = (PAPEL_ADMIN, PAPEL_OPERADOR, PAPEL_LEITOR)

# scrypt com os parâmetros recomendados para uso interativo.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


@dataclass(frozen=True)
class Usuario:
    email: str
    senha_hash: str
    papel: str = PAPEL_LEITOR
    nichos: tuple[str, ...] = ()
    ativo: bool = True

    @property
    def eh_admin(self) -> bool:
        return self.papel == PAPEL_ADMIN

    def pode_ver(self, nicho: str) -> bool:
        return self.eh_admin or nicho in self.nichos

    def pode_conferir(self, nicho: str) -> bool:
        """Se pode marcar reserva confirmada neste nicho.

        A conferência alimenta o cálculo da comissão, então é escrita — e o
        Adriano, que audita o fechamento, não deve poder editar o que audita.
        """
        if not self.pode_ver(nicho):
            return False
        return self.papel in (PAPEL_ADMIN, PAPEL_OPERADOR)

    def nichos_visiveis(self, todos: list[str]) -> list[str]:
        if self.eh_admin:
            return sorted(todos)
        return sorted(n for n in self.nichos if n in todos) or sorted(self.nichos)


# --- Senhas ---------------------------------------------------------------


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        senha.encode(), salt=sal, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sal.hex()}${derivada.hex()}"


def conferir_senha(senha: str, senha_hash: str) -> bool:
    try:
        algoritmo, n, r, p, sal_hex, esperado_hex = senha_hash.split("$")
        if algoritmo != "scrypt":
            return False
        derivada = hashlib.scrypt(
            senha.encode(),
            salt=bytes.fromhex(sal_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(esperado_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada.hex(), esperado_hex)


# Hash descartável, usado quando o e-mail não existe. Sem ele, a resposta volta
# rápido demais para usuário inexistente e o tempo denuncia quem tem conta.
_HASH_ISCA = gerar_hash(secrets.token_urlsafe(16))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- CSRF -----------------------------------------------------------------
#
# A conferência é escrita que mexe no valor da comissão, então não basta o
# SameSite=Lax do cookie. O token sai do próprio token de sessão via HMAC:
# quem não tem a sessão não consegue forjá-lo, e não precisa guardar nada.


def csrf_token(token_sessao: str) -> str:
    return hmac.new(token_sessao.encode(), b"csrf", hashlib.sha256).hexdigest()


def csrf_valido(token_sessao: str | None, enviado: str | None) -> bool:
    if not token_sessao or not enviado:
        return False
    return hmac.compare_digest(csrf_token(token_sessao), enviado)


# --- Repositório de usuários e sessões ------------------------------------


class RepoAuth(Protocol):
    async def buscar_usuario(self, email: str) -> Usuario | None: ...
    async def salvar_sessao(self, token_hash: str, email: str, expira_em: datetime) -> None: ...
    async def buscar_sessao(self, token_hash: str) -> tuple[str, datetime] | None: ...
    async def apagar_sessao(self, token_hash: str) -> None: ...
    async def registrar_auditoria(self, evento: dict) -> None: ...


@dataclass
class RepoAuthMemoria:
    """Para testes e para rodar local sem GCP."""

    usuarios: dict[str, Usuario] = field(default_factory=dict)
    sessoes: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    auditoria: list[dict] = field(default_factory=list)

    async def buscar_usuario(self, email: str) -> Usuario | None:
        return self.usuarios.get(email.strip().lower())

    async def salvar_sessao(self, token_hash: str, email: str, expira_em: datetime) -> None:
        self.sessoes[token_hash] = (email, expira_em)

    async def buscar_sessao(self, token_hash: str) -> tuple[str, datetime] | None:
        return self.sessoes.get(token_hash)

    async def apagar_sessao(self, token_hash: str) -> None:
        self.sessoes.pop(token_hash, None)

    async def registrar_auditoria(self, evento: dict) -> None:
        self.auditoria.append(evento)


class RepoAuthFirestore:
    def __init__(self, cfg, client=None) -> None:
        self.cfg = cfg
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self.cfg.gcp_project_id)
        return self._client

    async def buscar_usuario(self, email: str) -> Usuario | None:
        doc = await self._get_client().collection("painel_usuarios").document(
            email.strip().lower()
        ).get()
        if not doc.exists:
            return None
        d = doc.to_dict() or {}
        return Usuario(
            email=email.strip().lower(),
            senha_hash=d.get("senha_hash", ""),
            papel=d.get("papel", PAPEL_LEITOR),
            nichos=tuple(d.get("nichos", ())),
            ativo=bool(d.get("ativo", True)),
        )

    async def salvar_sessao(self, token_hash: str, email: str, expira_em: datetime) -> None:
        await self._get_client().collection("painel_sessoes").document(token_hash).set(
            {"email": email, "expira_em": expira_em}
        )

    async def buscar_sessao(self, token_hash: str) -> tuple[str, datetime] | None:
        doc = await self._get_client().collection("painel_sessoes").document(
            token_hash
        ).get()
        if not doc.exists:
            return None
        d = doc.to_dict() or {}
        expira = d.get("expira_em")
        if not expira:
            return None
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        return d.get("email", ""), expira

    async def apagar_sessao(self, token_hash: str) -> None:
        await self._get_client().collection("painel_sessoes").document(
            token_hash
        ).delete()

    async def registrar_auditoria(self, evento: dict) -> None:
        await self._get_client().collection("painel_auditoria").add(evento)


# --- Tentativas de login --------------------------------------------------


class ControleTentativas:
    """Trava o login após tentativas seguidas erradas.

    Vive na memória da instância. Com várias instâncias no Cloud Run a trava é
    por instância, então é atrito contra força bruta, não barreira absoluta.
    Para barreira de verdade o caminho é Cloud Armor na frente do serviço.
    """

    def __init__(self, limite: int = 5, janela_s: int = 900) -> None:
        self.limite = limite
        self.janela_s = janela_s
        self._tentativas: dict[str, list[float]] = {}

    def bloqueado(self, chave: str) -> bool:
        agora = time.monotonic()
        recentes = [t for t in self._tentativas.get(chave, []) if agora - t < self.janela_s]
        self._tentativas[chave] = recentes
        return len(recentes) >= self.limite

    def registrar_falha(self, chave: str) -> None:
        self._tentativas.setdefault(chave, []).append(time.monotonic())

    def limpar(self, chave: str) -> None:
        self._tentativas.pop(chave, None)


# --- Operações ------------------------------------------------------------


async def autenticar(repo: RepoAuth, email: str, senha: str) -> Usuario | None:
    """Confere e-mail e senha. Devolve o usuário, ou None."""
    usuario = await repo.buscar_usuario(email)
    if usuario is None:
        # Gasta o mesmo tempo de um usuário real, para não vazar quem existe.
        conferir_senha(senha, _HASH_ISCA)
        return None
    if not usuario.ativo:
        conferir_senha(senha, _HASH_ISCA)
        return None
    if not conferir_senha(senha, usuario.senha_hash):
        return None
    return usuario


async def abrir_sessao(repo: RepoAuth, usuario: Usuario) -> str:
    token = secrets.token_urlsafe(32)
    expira_em = datetime.now(timezone.utc) + DURACAO_SESSAO
    await repo.salvar_sessao(hash_token(token), usuario.email, expira_em)
    return token


async def usuario_da_sessao(repo: RepoAuth, token: str | None) -> Usuario | None:
    if not token:
        return None
    sessao = await repo.buscar_sessao(hash_token(token))
    if sessao is None:
        return None
    email, expira_em = sessao
    if expira_em <= datetime.now(timezone.utc):
        await repo.apagar_sessao(hash_token(token))
        return None
    usuario = await repo.buscar_usuario(email)
    if usuario is None or not usuario.ativo:
        return None
    return usuario


async def fechar_sessao(repo: RepoAuth, token: str | None) -> None:
    if token:
        await repo.apagar_sessao(hash_token(token))


async def auditar(
    repo: RepoAuth, *, quem: str, acao: str, detalhe: str = "", ip: str = ""
) -> None:
    await repo.registrar_auditoria(
        {
            "quem": quem,
            "acao": acao,
            "detalhe": detalhe,
            "ip": ip,
            "quando": datetime.now(timezone.utc),
        }
    )
