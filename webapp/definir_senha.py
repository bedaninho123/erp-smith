"""Define (ou redefine) a senha de login de um usuário do painel
administrativo. Script interativo, rodado pelo próprio usuário -- a senha
nunca passa por nenhum outro lugar, só fica guardada como hash (nunca em
texto puro) na coluna usuario.senha_hash.

Uso: .venv\\Scripts\\python.exe -m webapp.definir_senha
"""
import getpass
import sqlite3

from werkzeug.security import generate_password_hash

from core.conexao import conectar


def main():
    con = conectar()
    try:
        usuarios = con.execute(
            "SELECT usuario_id, nome, email FROM usuario WHERE ativo = 'Sim' ORDER BY nome"
        ).fetchall()
        if not usuarios:
            print("Nenhum usuário ativo encontrado.")
            return

        print("Usuários disponíveis:")
        for u in usuarios:
            print(f"  {u['usuario_id']} -- {u['nome']} ({u['email']})")

        usuario_id = input("\nID do usuário (ex.: USR-000001): ").strip()
        linha = con.execute(
            "SELECT usuario_id, nome FROM usuario WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        if not linha:
            print(f"Usuário {usuario_id} não encontrado.")
            return

        senha = getpass.getpass(f"Nova senha para {linha['nome']}: ")
        if len(senha) < 8:
            print("Senha muito curta -- use pelo menos 8 caracteres.")
            return
        confirmacao = getpass.getpass("Confirme a senha: ")
        if senha != confirmacao:
            print("As senhas não coincidem -- nada foi alterado.")
            return

        con.execute(
            "UPDATE usuario SET senha_hash = ? WHERE usuario_id = ?",
            (generate_password_hash(senha), usuario_id),
        )
        con.commit()
        print(f"Senha de {linha['nome']} definida com sucesso.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
