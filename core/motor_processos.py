"""Motor de Processos: cria e atualiza um processo dentro de um caso.
Estado do Core, sem IA -- hoje só é chamado pelo painel administrativo
(um funcionário abrindo/atualizando um processo), nunca pelo Motor IA
(RCA/matriz: "a IA nunca altera processo.status; só informa proxima_acao
cadastrada" -- ver core/db/schema.sql).

status/protocolo/proxima_acao são texto livre por enquanto (mesmo padrão
de outros campos "gerados por pessoa" no projeto -- não têm lista
controlada no schema, ao contrário de caso.status).
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(processo_id, 5) AS INTEGER)) FROM processo"
    ).fetchone()[0] or 0
    return f"PRO-{maior + 1:06d}"


def _registrar_historico_caso(
    con, caso_id: str, tipo_evento: str, descricao: str, criado_por: str,
) -> None:
    historico_id = con.execute(
        "SELECT MAX(CAST(SUBSTR(historico_id, 5) AS INTEGER)) FROM historico"
    ).fetchone()[0] or 0
    novo_id = f"HIS-{historico_id + 1:06d}"
    con.execute(
        "INSERT INTO historico VALUES (?,?,?,?,?,?,?,?)",
        (novo_id, caso_id, tipo_evento, descricao, None, None, _agora_iso(), criado_por),
    )


def criar_processo(
    caso_id: str,
    cliente_id: str,
    servico_id: str,
    protocolo: Optional[str] = None,
    status: str = "Aberto",
    prazo_estimado: Optional[str] = None,
    proxima_acao: Optional[str] = None,
    responsavel_id: Optional[str] = None,
    observacoes: Optional[str] = None,
    criado_por: str = "Painel administrativo",
) -> str:
    con = conectar()
    try:
        existe_servico = con.execute(
            "SELECT 1 FROM servico WHERE service_id = ? AND ativo = 'Sim'", (servico_id,)
        ).fetchone()
        if not existe_servico:
            raise ValueError(f"Serviço não encontrado ou inativo: {servico_id}")

        novo_id = _proximo_id(con)
        agora = _agora_iso()
        con.execute(
            "INSERT INTO processo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, caso_id, cliente_id, servico_id, protocolo, status,
                agora, prazo_estimado, proxima_acao, responsavel_id, agora, observacoes,
            ),
        )
        _registrar_historico_caso(
            con, caso_id, "outro", f"Processo criado: {novo_id}.", criado_por=criado_por,
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_processo(
    processo_id: str,
    status: str,
    protocolo: Optional[str],
    prazo_estimado: Optional[str],
    proxima_acao: Optional[str],
    responsavel_id: Optional[str],
    observacoes: Optional[str],
    alterado_por: str = "Painel administrativo",
) -> tuple[str, str]:
    """Devolve (status_anterior, caso_id) -- quem chama usa isso pra saber
    se o status realmente mudou e a qual caso notificar."""
    con = conectar()
    try:
        linha = con.execute(
            "SELECT caso_id, status FROM processo WHERE processo_id = ?", (processo_id,)
        ).fetchone()
        if not linha:
            raise ValueError(f"Processo não encontrado: {processo_id}")
        status_antigo = linha["status"]

        if responsavel_id:
            existe_usuario = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND ativo = 'Sim'", (responsavel_id,)
            ).fetchone()
            if not existe_usuario:
                raise ValueError(f"Usuário não encontrado ou inativo: {responsavel_id}")

        con.execute(
            "UPDATE processo SET status=?, protocolo=?, prazo_estimado=?, proxima_acao=?, "
            "responsavel_id=?, observacoes=?, ultima_atualizacao=? WHERE processo_id=?",
            (status, protocolo, prazo_estimado, proxima_acao, responsavel_id,
             observacoes, _agora_iso(), processo_id),
        )
        if status != status_antigo:
            _registrar_historico_caso(
                con, linha["caso_id"], "outro",
                f"Status do processo {processo_id} alterado de {status_antigo!r} para {status!r}.",
                criado_por=alterado_por,
            )
        con.commit()
        return status_antigo, linha["caso_id"]
    finally:
        con.close()
