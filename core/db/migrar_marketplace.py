"""Cria a tabela `anuncio` no banco que já está em uso -- sem recriar
nada.

Marketplace de classificados entre os afiliados de uma empresa (ver
core/motor_marketplace.py e portal/app.py para as regras de quem pode
ver/publicar). Nasce sem nenhuma linha -- não há dado antigo pra migrar,
é funcionalidade nova.

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe na estrutura do banco, que é de todas as empresas ao mesmo tempo
(CLAUDE.md: admin só em script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_marketplace`
"""
from core.conexao import conectar_admin

CRIAR_TABELA = """
CREATE TABLE anuncio (
    anuncio_id       TEXT PRIMARY KEY,
    empresa_id       TEXT NOT NULL REFERENCES empresa(empresa_id),
    cliente_id       TEXT NOT NULL REFERENCES cliente(cliente_id),
    categoria        TEXT NOT NULL,
    titulo           TEXT NOT NULL,
    descricao        TEXT,
    valor            REAL,
    contato_telefone TEXT,
    contato_email    TEXT,
    fotos            TEXT,
    status           TEXT NOT NULL DEFAULT 'Pendente',
    motivo_recusa    TEXT,
    revisado_por     TEXT,
    revisado_em      TEXT,
    criado_em        TEXT NOT NULL,
    atualizado_em    TEXT NOT NULL
)
"""


def main() -> None:
    con = conectar_admin()
    try:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'anuncio'"
        ).fetchone()
        if existe:
            print("Nada a fazer: a tabela anuncio já existe.")
            return

        con.execute(CRIAR_TABELA)
        con.execute("CREATE INDEX idx_anuncio_empresa_id ON anuncio(empresa_id)")
        con.execute("CREATE INDEX idx_anuncio_cliente_id ON anuncio(cliente_id)")
        con.execute("CREATE INDEX idx_anuncio_status ON anuncio(empresa_id, status)")
        con.commit()
        print("Pronto. Tabela anuncio criada.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
