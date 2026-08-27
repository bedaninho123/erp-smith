"""Cria a tabela `modalidade` num banco de Domínio já em uso.

Espelho de GET /championship/modalities/groups -- o único endpoint de
campeonato que responde com dado para a credencial do clube (2026-08-27).
`/championship/stage` devolve lista vazia, então etapa e resultado por
prova continuam fora do alcance; o que dá para trazer é o vocabulário.

Nasce VAZIA. Para preencher (uma chamada só, poucos segundos):

    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_modalidades

Idempotente: confere se a tabela existe antes de criar.

    .venv\\Scripts\\python.exe -m domain.clube_tiro.db.migrar_modalidades
"""
from domain.clube_tiro.motor_filiados import conectar

CRIAR = """
CREATE TABLE modalidade (
    modalidade_id     TEXT PRIMARY KEY,
    empresa_id        TEXT NOT NULL,
    grupo_id_sh       INTEGER,
    grupo             TEXT NOT NULL,
    modalidade_id_sh  INTEGER NOT NULL,
    nome              TEXT NOT NULL,
    ativo             TEXT NOT NULL DEFAULT 'Sim',
    sincronizado_em   TEXT NOT NULL,
    UNIQUE (empresa_id, grupo_id_sh, modalidade_id_sh)
);
CREATE INDEX idx_modalidade_empresa_id ON modalidade(empresa_id);
"""


def migrar() -> dict:
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='modalidade'"
        ).fetchone()
        if existe:
            total = con.execute("SELECT COUNT(*) FROM modalidade").fetchone()[0]
            return {"criada": False, "modalidades": total}
        con.executescript(CRIAR)
        con.commit()
        return {"criada": True, "modalidades": 0}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    if saida["criada"]:
        print("Tabela modalidade criada (vazia).")
    else:
        print(f"Tabela modalidade já existe, com {saida['modalidades']} linha(s).")
    print()
    print("Para preencher com o catálogo do clube:")
    print("  .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_modalidades")
