"""Motor de Campeonatos: CRUD do calendário de provas/campeonatos do
clube. Vive no Domínio (não no Core) porque "campeonato" é vocabulário
específico de clube de tiro -- mesmo raciocínio de conhecimento
(domain/clube_tiro/db/schema.sql). Populado à mão por enquanto
(origem='manual'); quando a credencial do Shooting House existir
(integracoes/shooting_house.py já cita "campeonatos" como dado que o
sistema deles guarda), a ideia é reconciliar com origem='shooting_house'
em vez de manter duas fontes de verdade permanentes.
"""
from datetime import datetime, timezone
from typing import Optional

import os
import sqlite3

DB_PATH = os.environ.get(
    "ERP_DOMAIN_DB", "domain/clube_tiro/db/dominio_clube_tiro.db"
)


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(campeonato_id, 5) AS INTEGER)) FROM campeonato"
    ).fetchone()[0] or 0
    return f"CAM-{maior + 1:06d}"


def listar_campeonatos(
    empresa_id: str, ano: Optional[int] = None, apenas_ativos: bool = True
) -> list:
    con = conectar()
    try:
        query = "SELECT * FROM campeonato WHERE empresa_id = ?"
        params: list = [empresa_id]
        if apenas_ativos:
            query += " AND ativo = 'Sim'"
        if ano:
            query += " AND strftime('%Y', data_inicio) = ?"
            params.append(str(ano))
        query += " ORDER BY data_inicio"
        return [dict(row) for row in con.execute(query, params).fetchall()]
    finally:
        con.close()


def obter_campeonato(empresa_id: str, campeonato_id: str) -> Optional[dict]:
    con = conectar()
    try:
        linha = con.execute(
            "SELECT * FROM campeonato WHERE campeonato_id = ? AND empresa_id = ?",
            (campeonato_id, empresa_id),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def criar_campeonato(
    empresa_id: str, nome: str, data_inicio: str, data_fim: Optional[str] = None,
    local: Optional[str] = None, observacoes: Optional[str] = None,
    origem: str = "manual",
) -> str:
    con = conectar()
    try:
        novo_id = _proximo_id(con)
        agora = _agora_iso()
        con.execute(
            "INSERT INTO campeonato "
            "(campeonato_id, empresa_id, nome, data_inicio, data_fim, local, "
            "observacoes, origem, ativo, criado_em, atualizado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, nome, data_inicio, data_fim or data_inicio,
                local, observacoes, origem, "Sim", agora, agora,
            ),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_campeonato(
    empresa_id: str, campeonato_id: str, nome: str, data_inicio: str, data_fim: Optional[str] = None,
    local: Optional[str] = None, observacoes: Optional[str] = None,
) -> None:
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM campeonato WHERE campeonato_id = ? AND empresa_id = ?",
            (campeonato_id, empresa_id),
        ).fetchone()
        if not existe:
            raise ValueError(f"Campeonato não encontrado: {campeonato_id}")
        con.execute(
            "UPDATE campeonato SET nome = ?, data_inicio = ?, data_fim = ?, "
            "local = ?, observacoes = ?, atualizado_em = ? "
            "WHERE campeonato_id = ? AND empresa_id = ?",
            (
                nome, data_inicio, data_fim or data_inicio, local, observacoes,
                _agora_iso(), campeonato_id, empresa_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def remover_campeonato(empresa_id: str, campeonato_id: str) -> None:
    """Soft delete -- mesmo padrão de conhecimento.ativo, nunca DELETE de
    verdade (mantém histórico do que já foi divulgado)."""
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM campeonato WHERE campeonato_id = ? AND empresa_id = ?",
            (campeonato_id, empresa_id),
        ).fetchone()
        if not existe:
            raise ValueError(f"Campeonato não encontrado: {campeonato_id}")
        con.execute(
            "UPDATE campeonato SET ativo = 'Não', atualizado_em = ? "
            "WHERE campeonato_id = ? AND empresa_id = ?",
            (_agora_iso(), campeonato_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    novo_id = criar_campeonato(
        EMPRESA, "Prova de fumaça", "2026-01-01", "2026-01-02", local="Sede Smith",
    )
    print(f"Campeonato criado: {novo_id}")
    print(listar_campeonatos(EMPRESA, ano=2026))
    atualizar_campeonato(EMPRESA, novo_id, "Prova de fumaça (editada)", "2026-01-01", "2026-01-02")
    remover_campeonato(EMPRESA, novo_id)
    print("Removido (soft delete):", obter_campeonato(EMPRESA, novo_id))
