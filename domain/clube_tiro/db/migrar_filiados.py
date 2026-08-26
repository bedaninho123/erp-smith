"""Cria a tabela `filiado` no banco de Domínio que já está em uso -- sem
recriar nada.

Nenhum seed: a tabela nasce vazia e é preenchida pela sincronização
(`domain.clube_tiro.sincronizar_habitualidade`), que espelha a lista do
Shooting House. Enquanto a integração estiver no modo simulado, ela é
preenchida com as pessoas fictícias de `_FILIADOS_TESTE`.

Idempotente -- rodar de novo não faz nada.

Uso: `.venv\\Scripts\\python.exe -m domain.clube_tiro.db.migrar_filiados`
"""
import sqlite3

from motor_ia.conexao import DOMAIN_DB

CRIAR_TABELA = """
CREATE TABLE filiado (
    filiado_id           TEXT PRIMARY KEY,
    empresa_id           TEXT NOT NULL,
    idatirador           INTEGER,
    matricula            TEXT,
    nome                 TEXT NOT NULL,
    cpf                  TEXT NOT NULL,
    email                TEXT,
    status_filiacao      TEXT,
    participacoes_12m    INTEGER,
    ultima_participacao  TEXT,
    sincronizado_em      TEXT,
    sincronizacao_erro   TEXT,
    criado_em            TEXT NOT NULL,
    atualizado_em        TEXT NOT NULL,
    UNIQUE (empresa_id, cpf)
)
"""

INDICES = [
    "CREATE INDEX idx_filiado_empresa_id ON filiado(empresa_id)",
    "CREATE INDEX idx_filiado_cpf ON filiado(cpf)",
    "CREATE INDEX idx_filiado_sincronizado ON filiado(empresa_id, sincronizado_em)",
]


def migrar() -> None:
    con = sqlite3.connect(DOMAIN_DB)
    try:
        existe = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='filiado'"
        ).fetchone()
        if existe:
            print("Tabela `filiado` já existe -- nada a fazer.")
            return

        con.execute(CRIAR_TABELA)
        for indice in INDICES:
            con.execute(indice)
        con.commit()
        print("Tabela `filiado` criada (vazia).")
        print()
        print("Próximo passo -- preencher a partir do Shooting House:")
        print("  .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade")
    finally:
        con.close()


if __name__ == "__main__":
    migrar()
