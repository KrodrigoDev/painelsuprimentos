"""
Cria (ou reativa) um usuário ADMINISTRADOR do painel.

    python -m scripts.criar_admin                 # pergunta login, nome e senha no terminal
    python -m scripts.criar_admin --login kaua    # pergunta só nome e senha

A senha é digitada no terminal (getpass, sem eco) e gravada só como hash —
nunca fica em código, .env ou log. Para automação, `--senha-stdin` lê a senha
da entrada padrão (ex.: de um cofre de segredos).
Se o login já existir, a senha é redefinida e o usuário volta a ser administrador.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.seguranca import repo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login")
    ap.add_argument("--nome")
    ap.add_argument("--senha-stdin", action="store_true", help="lê a senha da entrada padrão (1ª linha)")
    a = ap.parse_args()
    if not repo.tabelas_existem():
        print("Tabelas de acesso não existem: rode `alembic upgrade head` antes.", file=sys.stderr)
        return 2
    login = a.login or input("Login (minúsculo, ex.: kaua.rodrigo): ").strip()
    nome = a.nome or input("Nome completo: ").strip() or login
    if a.senha_stdin:
        senha = sys.stdin.readline().rstrip("\n")
    else:
        senha = getpass.getpass("Senha (mín. 8, letras e números): ")
        if senha != getpass.getpass("Repita a senha: "):
            print("As senhas não conferem.", file=sys.stderr)
            return 1
    try:
        uid = repo.criar_admin(login, nome, senha)
    except repo.ErroAcesso as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    print(f"Administrador '{repo.normalizar_login(login)}' pronto (id {uid}). Entre em /login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
