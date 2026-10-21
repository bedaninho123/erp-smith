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
    con, empresa_id: str, caso_id: str, tipo_evento: str, descricao: str, criado_por: str,
) -> None:
    historico_id = con.execute(
        "SELECT MAX(CAST(SUBSTR(historico_id, 5) AS INTEGER)) FROM historico"
    ).fetchone()[0] or 0
    novo_id = f"HIS-{historico_id + 1:06d}"
    con.execute(
        "INSERT INTO historico (historico_id, empresa_id, caso_id, tipo_evento, "
        "descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (novo_id, empresa_id, caso_id, tipo_evento, descricao, None, None,
         _agora_iso(), criado_por),
    )


def criar_processo(
    empresa_id: str,
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
    con = conectar(empresa_id)
    try:
        existe_servico = con.execute(
            "SELECT 1 FROM servico WHERE service_id = ? AND empresa_id = ? AND ativo = 'Sim'",
            (servico_id, empresa_id),
        ).fetchone()
        if not existe_servico:
            raise ValueError(f"Serviço não encontrado ou inativo: {servico_id}")

        # O caso também tem que ser desta empresa -- caso contrário o
        # processo nasceria ligando dado de duas empresas.
        existe_caso = con.execute(
            "SELECT 1 FROM caso WHERE caso_id = ? AND empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
        if not existe_caso:
            raise ValueError(f"Caso não encontrado nesta empresa: {caso_id}")

        novo_id = _proximo_id(con)
        agora = _agora_iso()
        con.execute(
            "INSERT INTO processo (processo_id, empresa_id, caso_id, cliente_id, "
            "servico_id, protocolo, status, data_abertura, prazo_estimado, "
            "proxima_acao, responsavel_id, ultima_atualizacao, observacoes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, caso_id, cliente_id, servico_id, protocolo,
                status, agora, prazo_estimado, proxima_acao, responsavel_id,
                agora, observacoes,
            ),
        )
        _registrar_historico_caso(
            con, empresa_id, caso_id, "outro", f"Processo criado: {novo_id}.",
            criado_por=criado_por,
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def atualizar_processo(
    empresa_id: str,
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
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT caso_id, status FROM processo WHERE processo_id = ? AND empresa_id = ?",
            (processo_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Processo não encontrado: {processo_id}")
        status_antigo = linha["status"]

        if responsavel_id:
            existe_usuario = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ? AND ativo = 'Sim'",
                (responsavel_id, empresa_id),
            ).fetchone()
            if not existe_usuario:
                raise ValueError(f"Usuário não encontrado ou inativo: {responsavel_id}")

        con.execute(
            "UPDATE processo SET status=?, protocolo=?, prazo_estimado=?, proxima_acao=?, "
            "responsavel_id=?, observacoes=?, ultima_atualizacao=? "
            "WHERE processo_id=? AND empresa_id=?",
            (status, protocolo, prazo_estimado, proxima_acao, responsavel_id,
             observacoes, _agora_iso(), processo_id, empresa_id),
        )
        if status != status_antigo:
            _registrar_historico_caso(
                con, empresa_id, linha["caso_id"], "outro",
                f"Status do processo {processo_id} alterado de {status_antigo!r} para {status!r}.",
                criado_por=alterado_por,
            )
        con.commit()
        return status_antigo, linha["caso_id"]
    finally:
        con.close()


STATUS_CONCLUIDO = "Concluído"


def concluir_com_documento(
    empresa_id: str,
    processo_id: str,
    conteudo: bytes,
    nome_arquivo: str,
    tipo_documento: str,
    data_validade: Optional[str] = None,
    referencia: Optional[str] = None,
    finalidade: Optional[str] = None,
    concluido_por: str = "Painel administrativo",
) -> dict:
    """Entrega o que o cliente pagou para receber (2026-10-20): o CRAF
    renovado, a guia emitida. Guarda o arquivo no DOSSIÊ da pessoa -- é
    dela, para sempre, e aparece em "Minha conta" no Portal -- e liga ao
    processo, que vira Concluído no mesmo gesto. No Portal o cliente vê o
    "Concluído" com o documento ao lado.

    O dono do documento é o cliente DO PROCESSO, lido do banco, nunca de
    quem chamou: é isso que garante que o arquivo só aparece para ele.

    Devolve {status_anterior, caso_id, documento_id}.
    """
    from core.motor_documentos import salvar_no_dossie

    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT caso_id, cliente_id, status FROM processo "
            "WHERE processo_id = ? AND empresa_id = ?",
            (processo_id, empresa_id),
        ).fetchone()
    finally:
        con.close()
    if not linha:
        raise ValueError(f"Processo não encontrado: {processo_id}")

    documento_id = salvar_no_dossie(
        empresa_id, linha["cliente_id"], conteudo, nome_arquivo,
        tipo_documento=tipo_documento, data_validade=data_validade,
        referencia=referencia, finalidade=finalidade,
    )

    con = conectar(empresa_id)
    try:
        con.execute(
            "UPDATE processo SET status = ?, documento_final_id = ?, ultima_atualizacao = ? "
            "WHERE processo_id = ? AND empresa_id = ?",
            (STATUS_CONCLUIDO, documento_id, _agora_iso(), processo_id, empresa_id),
        )
        _registrar_historico_caso(
            con, empresa_id, linha["caso_id"], "outro",
            f"Processo {processo_id} concluído com o documento {tipo_documento.strip()} "
            f"({documento_id}) entregue ao cliente.",
            criado_por=concluido_por,
        )
        con.commit()
    finally:
        con.close()
    return {"status_anterior": linha["status"], "caso_id": linha["caso_id"],
            "documento_id": documento_id}
