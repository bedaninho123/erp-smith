"""Cria a tabela log_administrativo no banco que já está em uso -- sem
recriar nada. Nenhum seed: é um log append-only, começa vazio (o que já
tinha acontecido antes desta migração não deixou rastro, e não tem como
reconstruir isso agora).

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe na estrutura do banco, que é de todas as empresas ao mesmo tempo
(CLAUDE.md: admin só em script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_log_administrativo`
"""
from core.conexao import conectar_admin

CRIAR_TABELA = """
CREATE TABLE log_administrativo (
    log_administrativo_id TEXT PRIMARY KEY,
    empresa_id             TEXT NOT NULL REFERENCES empresa(empresa_id),
    tipo_evento             TEXT NOT NULL,
    alvo                    TEXT NOT NULL,
    descricao                TEXT,
    valor_anterior          TEXT,
    valor_novo               TEXT,
    criado_em                TEXT NOT NULL,
    criado_por                TEXT NOT NULL
)
"""


def main() -> None:
    con = conectar_admin()
    try:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'log_administrativo'"
        ).fetchone()
        if existe:
            print("Nada a fazer: a tabela log_administrativo já existe.")
            return

        con.execute(CRIAR_TABELA)
        con.execute(
            "CREATE INDEX idx_log_administrativo_empresa_id ON log_administrativo(empresa_id)"
        )
        con.commit()
        print("Pronto. Tabela log_administrativo criada.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
