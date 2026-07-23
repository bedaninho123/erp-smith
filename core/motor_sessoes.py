"""Motor de Sessões: localiza/cria, atualiza e expira sessões de
atendimento (tabela sessao). Estado do Core -- não decide o que
responder, só administra o ciclo de vida da sessão.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.conexao import conectar

DURACAO_SESSAO_HORAS = 24


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_sessao_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(sessao_id, 5) AS INTEGER)) FROM sessao"
    ).fetchone()[0] or 0
    return f"SES-{maior + 1:06d}"


def localizar_ou_criar_sessao(
    cliente_id: str, canal: str, identificador_canal: Optional[str] = None
) -> str:
    con = conectar()
    try:
        linha = con.execute(
            "SELECT sessao_id FROM sessao WHERE cliente_id = ? AND ativo = 'Sim' "
            "AND status_sessao NOT IN ('Encerrada', 'Expirada') "
            "ORDER BY ultima_interacao_em DESC LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if linha:
            return linha["sessao_id"]

        novo_id = _proximo_sessao_id(con)
        agora = _agora_iso()
        expira = (
            datetime.now(timezone.utc) + timedelta(hours=DURACAO_SESSAO_HORAS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute(
            "INSERT INTO sessao VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, cliente_id, None, canal, identificador_canal, None, None,
                None, None, None, None, None, "Aberta", agora, agora, expira,
                "Não", None, None, "Sim", None,
            ),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_sessao(sessao_id: str, **campos) -> None:
    if not campos:
        return
    campos = dict(campos)
    campos["ultima_interacao_em"] = _agora_iso()
    con = conectar()
    try:
        set_clause = ", ".join(f"{campo} = ?" for campo in campos)
        con.execute(
            f"UPDATE sessao SET {set_clause} WHERE sessao_id = ?",
            (*campos.values(), sessao_id),
        )
        con.commit()
    finally:
        con.close()


def expirar_sessoes_antigas() -> int:
    con = conectar()
    try:
        agora = _agora_iso()
        cur = con.execute(
            "UPDATE sessao SET status_sessao = 'Expirada' "
            "WHERE status_sessao NOT IN ('Encerrada', 'Expirada') AND expira_em < ?",
            (agora,),
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


if __name__ == "__main__":
    sessao_id = localizar_ou_criar_sessao("CLI-000002", "Email", "joao.teste@example.com")
    print(f"Sessão localizada/criada: {sessao_id}")

    atualizar_sessao(sessao_id, ultima_intencao="consulta_processo", assunto_atual="Teste do Motor de Sessões")
    print("Sessão atualizada.")

    n = expirar_sessoes_antigas()
    print(f"Sessões expiradas nesta chamada: {n}")

    con = conectar()
    for row in con.execute("SELECT sessao_id, cliente_id, status_sessao, ultima_intencao, assunto_atual FROM sessao WHERE sessao_id = ?", (sessao_id,)):
        print(dict(row))
    con.close()
