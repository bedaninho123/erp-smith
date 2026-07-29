"""Cria a tabela usuario_permissao no banco que já está em uso -- sem
recriar nada.

Nenhum seed: ausência de linha em usuario_permissao já significa
"permitido" (core/motor_usuarios.tem_permissao), então não há nada para
popular -- Atendente existente continua com acesso a tudo que já tinha
até o Gestor desligar algo explicitamente pela tela de Usuários.

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe na estrutura do banco, que é de todas as empresas ao mesmo tempo
(CLAUDE.md: admin só em script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_permissoes_usuario`
"""
from core.conexao import conectar_admin

CRIAR_TABELA = """
CREATE TABLE usuario_permissao (
    usuario_id  TEXT NOT NULL REFERENCES usuario(usuario_id),
    empresa_id  TEXT NOT NULL REFERENCES empresa(empresa_id),
    funcao      TEXT NOT NULL,
    ativo       TEXT NOT NULL DEFAULT 'Sim',
    PRIMARY KEY (usuario_id, funcao)
)
"""


def main() -> None:
    con = conectar_admin()
    try:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuario_permissao'"
        ).fetchone()
        if existe:
            print("Nada a fazer: a tabela usuario_permissao já existe.")
            return

        con.execute(CRIAR_TABELA)
        con.execute(
            "CREATE INDEX idx_usuario_permissao_empresa_id ON usuario_permissao(empresa_id)"
        )
        con.commit()
        print("Pronto. Tabela usuario_permissao criada.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
