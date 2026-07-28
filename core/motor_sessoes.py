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
    empresa_id: str, cliente_id: str, canal: str, identificador_canal: Optional[str] = None
) -> str:
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT sessao_id FROM sessao WHERE empresa_id = ? AND cliente_id = ? "
            "AND ativo = 'Sim' AND status_sessao NOT IN ('Encerrada', 'Expirada') "
            "ORDER BY ultima_interacao_em DESC LIMIT 1",
            (empresa_id, cliente_id),
        ).fetchone()
        if linha:
            return linha["sessao_id"]

        novo_id = _proximo_sessao_id(con)
        agora = _agora_iso()
        expira = (
            datetime.now(timezone.utc) + timedelta(hours=DURACAO_SESSAO_HORAS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute(
            "INSERT INTO sessao (sessao_id, empresa_id, cliente_id, caso_id, canal, "
            "identificador_canal, status_sessao, iniciada_em, ultima_interacao_em, "
            "expira_em, encaminhada_humano, ativo) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, cliente_id, None, canal, identificador_canal,
                "Aberta", agora, agora, expira, "Não", "Sim",
            ),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_sessao(empresa_id: str, sessao_id: str, **campos) -> None:
    if not campos:
        return
    campos = dict(campos)
    campos["ultima_interacao_em"] = _agora_iso()
    con = conectar(empresa_id)
    try:
        set_clause = ", ".join(f"{campo} = ?" for campo in campos)
        # empresa_id no WHERE: sem isso, um sessao_id de outra empresa
        # seria atualizado normalmente.
        con.execute(
            f"UPDATE sessao SET {set_clause} WHERE sessao_id = ? AND empresa_id = ?",
            (*campos.values(), sessao_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


def expirar_sessoes_antigas(empresa_id: str) -> int:
    con = conectar(empresa_id)
    try:
        agora = _agora_iso()
        cur = con.execute(
            "UPDATE sessao SET status_sessao = 'Expirada' "
            "WHERE empresa_id = ? AND status_sessao NOT IN ('Encerrada', 'Expirada') "
            "AND expira_em < ?",
            (empresa_id, agora),
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    sessao_id = localizar_ou_criar_sessao(EMPRESA, "CLI-000002", "Email", "joao.teste@example.com")
    print(f"Sessão localizada/criada: {sessao_id}")

    atualizar_sessao(EMPRESA, sessao_id, ultima_intencao="consulta_processo", assunto_atual="Teste do Motor de Sessões")
    print("Sessão atualizada.")

    n = expirar_sessoes_antigas(EMPRESA)
    print(f"Sessões expiradas nesta chamada: {n}")

    con = conectar(EMPRESA)
    for row in con.execute("SELECT sessao_id, cliente_id, status_sessao, ultima_intencao, assunto_atual FROM sessao WHERE sessao_id = ?", (sessao_id,)):
        print(dict(row))
    con.close()
