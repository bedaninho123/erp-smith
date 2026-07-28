"""Cria o banco do Core a partir de core/db/schema.sql + views.sql.

Existe para que "recriar o banco" seja um comando versionado no repo, e
não uma linha de `sqlite3` que alguém precisa lembrar de digitar certo
-- o schema e as views têm que ser aplicados juntos e nessa ordem, senão
o banco nasce sem a fronteira de leitura do Motor IA.

Uso:
    python -m core.db.criar_banco             # só cria se não existir
    python -m core.db.criar_banco --recriar   # apaga e cria do zero

--recriar nunca descarta nada em silêncio: o banco atual é renomeado
para backup_AAAAMMDD_HHMMSS.db na mesma pasta antes de o novo nascer.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from core.conexao import CORE_DB

PASTA = Path(__file__).resolve().parent
SCHEMA = PASTA / "schema.sql"
VIEWS = PASTA / "views.sql"


def criar(caminho: Path) -> None:
    con = sqlite3.connect(caminho)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.executescript(VIEWS.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()


def main() -> None:
    recriar = "--recriar" in sys.argv
    caminho = Path(CORE_DB)
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
    print(f"Banco do Core criado em {caminho} (schema.sql + views.sql).")
    print("Próximo passo: python -m core.db.migrate_dados_teste")


if __name__ == "__main__":
    main()
