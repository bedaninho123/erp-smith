"""Cria o banco do Domínio Clube de Tiro a partir do schema.sql daqui.

Mesma ideia do core/db/criar_banco.py, e propositalmente um script
separado: o Core não conhece o Domínio, então quem cria o banco de
Domínio mora no Domínio. Os dois bancos são arquivos distintos de
propósito (ver CLAUDE.md, "Dois bancos SQLite físicos").

Uso:
    python -m domain.clube_tiro.db.criar_banco             # só cria se não existir
    python -m domain.clube_tiro.db.criar_banco --recriar   # apaga e cria do zero
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Mesmo par variável/padrão dos motores do Domínio (motor_campeonatos.py,
# motor_resultados.py) -- repetido em vez de centralizado para seguir o
# que o resto da camada já faz.
DB_PATH = os.environ.get(
    "ERP_DOMAIN_DB", "domain/clube_tiro/db/dominio_clube_tiro.db"
)

PASTA = Path(__file__).resolve().parent
SCHEMA = PASTA / "schema.sql"


def criar(caminho: Path) -> None:
    con = sqlite3.connect(caminho)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()


def main() -> None:
    recriar = "--recriar" in sys.argv
    caminho = Path(DB_PATH)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    if caminho.exists():
        if not recriar:
            print(f"{caminho} já existe. Nada foi feito.")
            print("Para apagar e criar do zero: --recriar "
                  "(o banco atual vira um backup na mesma pasta).")
            return
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = caminho.with_name(f"backup_{carimbo}.db")
        caminho.rename(backup)
        print(f"Banco anterior preservado em {backup}")

    criar(caminho)
    print(f"Banco do Domínio criado em {caminho}.")
    print("Próximos passos: python -m domain.clube_tiro.db.popular_conhecimento")
    print("                 python -m domain.clube_tiro.db.popular_campeonatos_2026")


if __name__ == "__main__":
    main()
