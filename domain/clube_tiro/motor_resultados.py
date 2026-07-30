"""Motor de Resultados: CRUD da classificação de uma prova/campeonato já
ocorrida. Vive no Domínio (não no Core), mesmo raciocínio de
motor_campeonatos.py -- "resultado de prova" é vocabulário específico de
clube de tiro. Populado à mão por enquanto (origem='manual'); quando a
credencial do Shooting House existir, a ideia é reconciliar com
origem='shooting_house' em vez de manter duas fontes de verdade.

Mostra a classificação completa da prova (todo mundo que participou),
não só o resultado de um cliente específico -- por isso nome_atirador é
sempre obrigatório e cliente_id é opcional (só quando o atirador também
é cliente do despachante, ver schema.sql).
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
    # Mesmo motivo do core/conexao.py: este arquivo também é escrito
    # pelo webapp e, via motor_ia/conexao.py, pelo poller/webhook -- sem
    # WAL + busy_timeout, escrita concorrente esbarra em "database is
    # locked".
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(resultado_id, 5) AS INTEGER)) FROM resultado_campeonato"
    ).fetchone()[0] or 0
    return f"RES-{maior + 1:06d}"


def listar_resultados(empresa_id: str, campeonato_id: str) -> list:
    """Classificação completa da prova, ordenada por modalidade e depois
    colocação (quem não tem colocação registrada vai para o fim de cada
    grupo, não para o topo)."""
    con = conectar()
    try:
        linhas = con.execute(
            "SELECT * FROM resultado_campeonato WHERE campeonato_id = ? AND empresa_id = ? "
            "ORDER BY COALESCE(modalidade, ''), "
            "CASE WHEN colocacao IS NULL THEN 1 ELSE 0 END, colocacao",
            (campeonato_id, empresa_id),
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        con.close()


def criar_resultado(
    empresa_id: str,
    campeonato_id: str,
    nome_atirador: str,
    cliente_id: Optional[str] = None,
    modalidade: Optional[str] = None,
    colocacao: Optional[int] = None,
    pontuacao: Optional[str] = None,
    observacoes: Optional[str] = None,
    origem: str = "manual",
) -> str:
    con = conectar()
    try:
        existe_campeonato = con.execute(
            "SELECT 1 FROM campeonato WHERE campeonato_id = ? AND empresa_id = ?",
            (campeonato_id, empresa_id),
        ).fetchone()
        if not existe_campeonato:
            raise ValueError(f"Campeonato não encontrado: {campeonato_id}")

        novo_id = _proximo_id(con)
        agora = _agora_iso()
        con.execute(
            "INSERT INTO resultado_campeonato "
            "(resultado_id, empresa_id, campeonato_id, cliente_id, nome_atirador, "
            "modalidade, colocacao, pontuacao, observacoes, origem, criado_em, "
            "atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, campeonato_id, cliente_id, nome_atirador,
                modalidade, colocacao, pontuacao, observacoes, origem, agora, agora,
            ),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_resultado(
    empresa_id: str,
    resultado_id: str,
    nome_atirador: str,
    cliente_id: Optional[str] = None,
    modalidade: Optional[str] = None,
    colocacao: Optional[int] = None,
    pontuacao: Optional[str] = None,
    observacoes: Optional[str] = None,
) -> None:
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM resultado_campeonato WHERE resultado_id = ? AND empresa_id = ?",
            (resultado_id, empresa_id),
        ).fetchone()
        if not existe:
            raise ValueError(f"Resultado não encontrado: {resultado_id}")
        con.execute(
            "UPDATE resultado_campeonato SET cliente_id = ?, nome_atirador = ?, "
            "modalidade = ?, colocacao = ?, pontuacao = ?, observacoes = ?, "
            "atualizado_em = ? WHERE resultado_id = ? AND empresa_id = ?",
            (
                cliente_id, nome_atirador, modalidade, colocacao, pontuacao,
                observacoes, _agora_iso(), resultado_id, empresa_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def remover_resultado(empresa_id: str, resultado_id: str) -> None:
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM resultado_campeonato WHERE resultado_id = ? AND empresa_id = ?",
            (resultado_id, empresa_id),
        ).fetchone()
        if not existe:
            raise ValueError(f"Resultado não encontrado: {resultado_id}")
        con.execute(
            "DELETE FROM resultado_campeonato WHERE resultado_id = ? AND empresa_id = ?",
            (resultado_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    from domain.clube_tiro.motor_campeonatos import criar_campeonato, remover_campeonato

    EMPRESA = "EMP-000001"
    campeonato_id = criar_campeonato(EMPRESA, "Prova de fumaça (resultados)", "2026-01-01")
    print(f"Campeonato de teste: {campeonato_id}")

    r1 = criar_resultado(EMPRESA, campeonato_id, "Felipe Bedani", cliente_id="CLI-000001", modalidade="Tiro Prático", colocacao=1, pontuacao="285/300")
    r2 = criar_resultado(EMPRESA, campeonato_id, "Atirador Convidado", modalidade="Tiro Prático", colocacao=2, pontuacao="270/300")
    print("Resultados criados:", r1, r2)

    print("Classificação:", listar_resultados(EMPRESA, campeonato_id))

    atualizar_resultado(EMPRESA, r2, "Atirador Convidado (corrigido)", modalidade="Tiro Prático", colocacao=2, pontuacao="271/300")
    remover_resultado(EMPRESA, r1)
    print("Após atualizar/remover:", listar_resultados(EMPRESA, campeonato_id))

    remover_campeonato(EMPRESA, campeonato_id)
