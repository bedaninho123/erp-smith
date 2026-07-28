"""Define (ou redefine) a senha de login de um usuário do painel
administrativo. Script interativo, rodado pelo próprio usuário -- a senha
nunca passa por nenhum outro lugar, só fica guardada como hash (nunca em
texto puro) na coluna usuario.senha_hash.

Uso: .venv\\Scripts\\python.exe -m webapp.definir_senha

Multi-tenant: este é um dos poucos lugares que usa conectar_admin() e
enxerga o banco inteiro, de propósito -- quem roda isto é o dono da
instalação, no terminal da máquina, e precisa conseguir cadastrar a
senha de qualquer usuário. O e-mail deixou de ser único globalmente
(UNIQUE(empresa_id, email)), então a listagem mostra a empresa junto:
sem isso, dois "Ana / ana@..." de empresas diferentes ficariam
indistinguíveis na hora de escolher o ID.
"""
import getpass

from werkzeug.security import generate_password_hash

from core.conexao import conectar_admin


def main():
    con = conectar_admin()
    try:
        usuarios = con.execute(
            "SELECT u.usuario_id, u.nome, u.email, u.empresa_id, e.nome AS empresa_nome "
            "FROM usuario u LEFT JOIN empresa e ON e.empresa_id = u.empresa_id "
            "WHERE u.ativo = 'Sim' ORDER BY u.empresa_id, u.nome"
        ).fetchall()
        if not usuarios:
            print("Nenhum usuário ativo encontrado.")
            return

        print("Usuários disponíveis:")
        for u in usuarios:
            empresa = u["empresa_nome"] or u["empresa_id"]
            print(f"  {u['usuario_id']} -- {u['nome']} ({u['email']}) [{empresa}]")

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
