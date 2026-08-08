#!/usr/bin/env python3
"""Cria ou atualiza um usuário do painel no Firestore.

A senha é pedida no terminal sem eco, ou lida de SENHA_PAINEL quando os
comandos são colados em bloco e o prompt interativo não sobrevive. Em nenhum
dos dois casos ela vai para o histórico do shell. No banco fica só o hash
scrypt.

Uso:
    python cabanas-agent/scripts/criar_usuario.py lucas@luduran.com --papel admin
    python cabanas-agent/scripts/criar_usuario.py adriano@exemplo.com --nichos cabanas
    python cabanas-agent/scripts/criar_usuario.py camily@exemplo.com --papel operador --nichos cabanas
    python cabanas-agent/scripts/criar_usuario.py alguem@exemplo.com --desativar

Papéis:
  admin     todos os nichos, lê e confere
  operador  só os nichos de --nichos, lê e confere (Camily)
  leitor    só os nichos de --nichos, apenas lê (Adriano)

Quem confere marca quais leads viraram reserva, e isso entra no cálculo da
comissão. Por isso o Adriano, que audita o fechamento, é `leitor`: ele não
deve poder editar o que audita.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.painel.auth import PAPEIS, PAPEL_ADMIN, PAPEL_LEITOR, gerar_hash  # noqa: E402

TAMANHO_MINIMO = 12


def pedir_senha() -> str:
    """A senha vem de SENHA_PAINEL, ou é perguntada.

    A variável existe porque a pergunta interativa não sobrevive a um bloco de
    comandos colado de uma vez: a linha seguinte do bloco vira a resposta, ou o
    terminal engole o prompt e o script morre com KeyboardInterrupt. Colar um
    bloco é exatamente como se instala isso na prática.

        read -s -p "Senha: " SENHA_PAINEL; echo; export SENHA_PAINEL

    Assim a senha também não fica no histórico do shell, o que aconteceria se
    ela viesse como argumento de linha de comando.
    """
    do_ambiente = os.environ.get("SENHA_PAINEL")
    if do_ambiente:
        if len(do_ambiente) < TAMANHO_MINIMO:
            raise SystemExit(
                f"SENHA_PAINEL tem {len(do_ambiente)} caracteres; "
                f"o mínimo é {TAMANHO_MINIMO}."
            )
        return do_ambiente

    senha = getpass.getpass("Senha: ")
    if len(senha) < TAMANHO_MINIMO:
        raise SystemExit(f"Senha muito curta (mínimo {TAMANHO_MINIMO} caracteres).")
    if senha != getpass.getpass("Repita a senha: "):
        raise SystemExit("As senhas não conferem.")
    return senha


def main() -> int:
    p = argparse.ArgumentParser(description="Cria ou atualiza usuário do painel.")
    p.add_argument("email")
    p.add_argument("--papel", choices=list(PAPEIS), default=PAPEL_LEITOR)
    p.add_argument(
        "--nichos",
        default="cabanas",
        help="Lista separada por vírgula. Ignorado quando o papel é admin.",
    )
    p.add_argument("--desativar", action="store_true", help="Bloqueia o acesso.")
    args = p.parse_args()

    from google.cloud import firestore

    email = args.email.strip().lower()
    client = firestore.Client(project=settings.gcp_project_id)
    doc = client.collection("painel_usuarios").document(email)

    if args.desativar:
        if not doc.get().exists:
            raise SystemExit(f"Usuário {email} não existe.")
        doc.update({"ativo": False})
        # As sessões abertas continuariam valendo até expirar; derrubar agora
        # é o ponto do desativar.
        for sessao in client.collection("painel_sessoes").where("email", "==", email).stream():
            sessao.reference.delete()
        print(f"{email} desativado e sessões encerradas.")
        return 0

    nichos = [n.strip() for n in args.nichos.split(",") if n.strip()]
    if args.papel == PAPEL_LEITOR and not nichos:
        raise SystemExit("Um leitor precisa de pelo menos um nicho.")

    doc.set(
        {
            "senha_hash": gerar_hash(pedir_senha()),
            "papel": args.papel,
            "nichos": [] if args.papel == PAPEL_ADMIN else nichos,
            "ativo": True,
        },
        merge=True,
    )

    alcance = "todos os nichos" if args.papel == PAPEL_ADMIN else ", ".join(nichos)
    print(f"{email} gravado — papel {args.papel}, acesso a {alcance}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
