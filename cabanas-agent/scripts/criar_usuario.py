#!/usr/bin/env python3
"""Cria ou atualiza um usuário do painel no Firestore.

A senha é pedida no terminal, sem eco, e nunca vai para o histórico do shell
nem para variável de ambiente. No banco fica só o hash scrypt.

Uso:
    python cabanas-agent/scripts/criar_usuario.py lucas@luduran.com --papel admin
    python cabanas-agent/scripts/criar_usuario.py adriano@exemplo.com --nichos cabanas
    python cabanas-agent/scripts/criar_usuario.py camile@exemplo.com --nichos cabanas
    python cabanas-agent/scripts/criar_usuario.py alguem@exemplo.com --desativar

`--papel admin` dá acesso a todos os nichos. `leitor` (padrão) só enxerga o que
estiver em `--nichos`.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.painel.auth import PAPEL_ADMIN, PAPEL_LEITOR, gerar_hash  # noqa: E402

TAMANHO_MINIMO = 12


def pedir_senha() -> str:
    senha = getpass.getpass("Senha: ")
    if len(senha) < TAMANHO_MINIMO:
        raise SystemExit(f"Senha muito curta (mínimo {TAMANHO_MINIMO} caracteres).")
    if senha != getpass.getpass("Repita a senha: "):
        raise SystemExit("As senhas não conferem.")
    return senha


def main() -> int:
    p = argparse.ArgumentParser(description="Cria ou atualiza usuário do painel.")
    p.add_argument("email")
    p.add_argument("--papel", choices=[PAPEL_ADMIN, PAPEL_LEITOR], default=PAPEL_LEITOR)
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
