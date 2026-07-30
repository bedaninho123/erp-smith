"""Log administrativo: registro append-only de mudança de papel,
permissão e ativo de usuário, e de configuração da empresa. Mesmo
espírito de core/motor_casos.py::_registrar_historico (evento de negócio
do Caso), mas pra ação de gestão -- sem isso, "quem desligou a revisão
humana" ou "quem tirou a permissão da Ana" não tinha resposta nenhuma
(achado na auditoria de riscos de 2026-07-30).

`registrar()` recebe a conexão já aberta pelo chamador (como
_registrar_historico) -- o registro do log entra na MESMA transação da
mudança em si, então os dois sempre acontecem juntos ou nenhum dos dois
acontece.

Só existe pra consulta manual por enquanto (SELECT direto, ou
core.motor_log_administrativo.listar() num script) -- não alimenta
nenhuma tela do painel ainda.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def registrar(
    con, empresa_id: str, tipo_evento: str, alvo: str, descricao: str,
    valor_anterior: Optional[str], valor_novo: Optional[str], criado_por: str,
) -> None:
    novo_id = _proximo_id(con, "log_administrativo", "log_administrativo_id", "ADM")
    con.execute(
        "INSERT INTO log_administrativo (log_administrativo_id, empresa_id, "
        "tipo_evento, alvo, descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (novo_id, empresa_id, tipo_evento, alvo, descricao,
         valor_anterior, valor_novo, _agora_iso(), criado_por),
    )


def listar(empresa_id: str, limite: int = 200) -> list[dict]:
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT * FROM log_administrativo WHERE empresa_id = ? "
            "ORDER BY criado_em DESC LIMIT ?",
            (empresa_id, limite),
        ).fetchall()
        return [dict(l) for l in linhas]
    finally:
        con.close()
