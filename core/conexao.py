"""Conexão com o banco do Core. O Core não depende de nenhuma camada
acima dele (Motor IA, Integrações) -- só o contrário.

MULTI-TENANT (docs/schema_multi_tenant.md §5): `conectar()` exige
empresa_id. Isso é de propósito -- não existe conexão "sem empresa" por
descuido. Quem realmente precisa enxergar o banco inteiro (scripts de
migração, criação de empresa) usa `conectar_admin()`, que tem nome
próprio justamente para aparecer numa busca por revisão de segurança.

A função empresa_atual() registrada aqui é o que faz as views do Core
(core/db/views.sql) se filtrarem sozinhas. Como o Motor IA já é obrigado
a ler só por view, ele fica isolado por empresa sem precisar saber que
multi-tenancy existe.
"""
import os
import sqlite3

# Caminho do banco vem de variável de ambiente com o banco real como
# padrão -- é o que permite a suíte de testes (tests/conftest.py) rodar
# contra um banco descartável sem nunca tocar em core/db/erp_smith.db.
# Lido uma vez na importação: quem quiser trocar precisa definir
# ERP_CORE_DB antes de importar qualquer módulo do Core.
CORE_DB = os.environ.get("ERP_CORE_DB", "core/db/erp_smith.db")


def conectar(empresa_id: str) -> sqlite3.Connection:
    """Conexão já amarrada a uma empresa. As views só devolvem linha
    dessa empresa; tabela crua continua exigindo o filtro à mão (é por
    isso que os testes de isolamento existem)."""
    if not empresa_id:
        raise ValueError(
            "conectar() exige empresa_id. Para acesso administrativo "
            "(migração, criação de empresa), use conectar_admin()."
        )
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.create_function("empresa_atual", 0, lambda: empresa_id)
    return con


def conectar_admin() -> sqlite3.Connection:
    """Conexão sem empresa -- enxerga o banco inteiro.

    Só para scripts de setup/migração e para criar a própria empresa.
    NÃO registra empresa_atual(), então qualquer SELECT numa view falha
    com "no such function" em vez de devolver dado de todas as empresas
    misturado. Falhar é o comportamento certo aqui: significa que a
    conexão errada foi usada.
    """
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
