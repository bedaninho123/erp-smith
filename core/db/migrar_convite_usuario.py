"""Tabela `usuario_convite` (2026-10-20): link por e-mail para a própria
pessoa criar a senha do painel -- ver core/motor_convite_usuario.py.

Idempotente, e roda sozinha na subida do servidor de produção
(webapp/servir.py), como migrar_codigo_portal.

    .venv\\Scripts\\python.exe -m core.db.migrar_convite_usuario
"""
from core.conexao import conectar_admin


def migrar() -> dict:
    con = conectar_admin()
    try:
        existia = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuario_convite'"
        ).fetchone() is not None
        con.execute(
            "CREATE TABLE IF NOT EXISTS usuario_convite ("
            "usuario_convite_id TEXT PRIMARY KEY, "
            "empresa_id TEXT NOT NULL REFERENCES empresa(empresa_id), "
            "usuario_id TEXT NOT NULL REFERENCES usuario(usuario_id), "
            "token_hash TEXT NOT NULL UNIQUE, "
            "motivo TEXT NOT NULL, "
            "criado_em TEXT NOT NULL, "
            "expira_em TEXT NOT NULL, "
            "usado_em TEXT, "
            "invalidado_em TEXT)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_usuario_convite_usuario "
            "ON usuario_convite(empresa_id, usuario_id)"
        )
        con.commit()
        return {"tabela_criada": not existia}
    finally:
        con.close()


if __name__ == "__main__":
    print(migrar())
