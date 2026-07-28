"""Conexão compartilhada com o banco do Core, já com o banco de Domínio
anexado (ATTACH DATABASE) -- usada por qualquer módulo do Motor IA que
precise ler Core e Domínio juntos, na mesma consulta.

MULTI-TENANT: repassa empresa_id para core.conexao.conectar(), que
registra empresa_atual() e faz as views do Core se filtrarem sozinhas.
Como o Motor IA já era obrigado a ler só por view (CLAUDE.md), ele fica
isolado por empresa sem precisar saber que multi-tenancy existe.

Atenção ao Domínio: `conhecimento` é compartilhado entre empresas (é
legislação federal), mas `campeonato` e `resultado_campeonato` têm
empresa_id e precisam de filtro explícito -- SQLite não aplica as views
do Core sobre um banco anexado (ver docs/schema_multi_tenant.md §7.1).
"""
import os
import sqlite3

from core.conexao import CORE_DB, conectar as _conectar_core

DOMAIN_DB = os.environ.get(
    "ERP_DOMAIN_DB", "domain/clube_tiro/db/dominio_clube_tiro.db"
)


def conectar(empresa_id: str) -> sqlite3.Connection:
    con = _conectar_core(empresa_id)
    con.execute("ATTACH DATABASE ? AS dominio", (DOMAIN_DB,))
    return con
