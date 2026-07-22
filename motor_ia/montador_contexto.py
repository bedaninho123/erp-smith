"""Monta o objeto de contexto único que o Motor IA usa para responder sobre um
caso — o equivalente em código da VW_ATENDIMENTO_COMPLETO do PROJETO_1.md.

Só lê pelas views do Core (core/db/views.sql) e pelo banco de Domínio via
ATTACH DATABASE — nunca SELECT direto em tabela crua fora daqui. Nenhuma
regra de negócio: este módulo apenas consulta e agrupa; decidir o que fazer
com o contexto é responsabilidade de outros módulos (Planejador, Redator).
"""
import json
import sqlite3

CORE_DB = "core/db/erp_smith.db"
DOMAIN_DB = "domain/clube_tiro/db/dominio_clube_tiro.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(f"ATTACH DATABASE '{DOMAIN_DB}' AS dominio")
    return con


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def montar_contexto(caso_id: str) -> dict:
    con = _connect()
    try:
        caso = _row_to_dict(
            con.execute("SELECT * FROM caso WHERE caso_id = ?", (caso_id,)).fetchone()
        )
        if caso is None:
            raise ValueError(f"Caso não encontrado: {caso_id}")

        cliente_view = _row_to_dict(
            con.execute(
                "SELECT * FROM VW_CLIENTE WHERE cliente_id = ?", (caso["cliente_id"],)
            ).fetchone()
        )
        campos_memoria = {
            "memoria_id", "resumo_cliente", "preferencia_canal",
            "tom_recomendado", "restricoes_atendimento", "informacoes_importantes",
        }
        cliente = {k: v for k, v in cliente_view.items() if k not in campos_memoria}
        memoria = {k: cliente_view[k] for k in campos_memoria if cliente_view.get(k) is not None} or None

        processos = [
            dict(r) for r in con.execute(
                "SELECT * FROM VW_PROCESSO WHERE caso_id = ?", (caso_id,)
            ).fetchall()
        ]

        servico_ids = {p["service_id"] for p in processos}
        servicos = [
            dict(r) for r in con.execute(
                f"SELECT * FROM VW_SERVICO WHERE service_id IN "
                f"({','.join('?' * len(servico_ids))})", tuple(servico_ids)
            ).fetchall()
        ] if servico_ids else []

        sessao = _row_to_dict(
            con.execute(
                "SELECT * FROM sessao WHERE caso_id = ? AND ativo = 'Sim' "
                "ORDER BY ultima_interacao_em DESC LIMIT 1",
                (caso_id,),
            ).fetchone()
        )

        documentos = [
            dict(r) for r in con.execute(
                "SELECT * FROM documento WHERE caso_id = ? OR processo_id IN "
                "(SELECT processo_id FROM processo WHERE caso_id = ?)",
                (caso_id, caso_id),
            ).fetchall()
        ]

        tarefas = [
            dict(r) for r in con.execute(
                "SELECT * FROM tarefas WHERE caso_id = ?", (caso_id,)
            ).fetchall()
        ]

        configuracoes = {
            r["chave"]: r["valor"]
            for r in con.execute(
                "SELECT chave, valor FROM configuracoes WHERE ativo = 'Sim'"
            ).fetchall()
        }

        conhecimento = [
            dict(r) for r in con.execute(
                "SELECT * FROM dominio.conhecimento "
                "WHERE categoria = ? AND aprovado = 'Sim' AND ativo = 'Sim'",
                (caso["categoria"],),
            ).fetchall()
        ]

        return {
            "cliente": cliente,
            "caso": caso,
            "processos": processos,
            "servicos": servicos,
            "memoria": memoria,
            "sessao": sessao,
            "configuracoes": configuracoes,
            "conhecimento": conhecimento,
            "documentos": documentos,
            "tarefas": tarefas,
        }
    finally:
        con.close()


if __name__ == "__main__":
    contexto = montar_contexto("CAS-000001")
    print(json.dumps(contexto, indent=2, ensure_ascii=False))
