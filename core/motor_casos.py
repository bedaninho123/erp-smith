"""Motor de Casos: localiza/cria e atualiza o status de um caso. Estado
do Core -- regra de negócio, não Motor IA. A IA nunca decide sozinha
encerrar/cancelar/mudar prioridade de um caso (RCA-009); este módulo
garante que toda mudança de status segue a lista controlada
(RCA-003) e fica registrada em historico -- quem decide chamar
continua sendo o orquestrador do Core, não uma decisão livre da IA.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

STATUS_VALIDOS = {
    "Aberto", "Em triagem", "Em andamento", "Aguardando cliente",
    "Aguardando terceiro", "Suspenso", "Encerrado", "Cancelado",
}


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def _registrar_historico(
    con, caso_id: str, tipo_evento: str, descricao: str,
    valor_anterior: Optional[str] = None, valor_novo: Optional[str] = None,
    criado_por: str = "Motor de Casos",
) -> None:
    novo_id = _proximo_id(con, "historico", "historico_id", "HIS")
    con.execute(
        "INSERT INTO historico VALUES (?,?,?,?,?,?,?,?)",
        (novo_id, caso_id, tipo_evento, descricao, valor_anterior, valor_novo, _agora_iso(), criado_por),
    )


def localizar_caso_aberto(cliente_id: str, categoria: Optional[str] = None) -> Optional[str]:
    con = conectar()
    try:
        query = (
            "SELECT caso_id FROM caso WHERE cliente_id = ? AND ativo = 'Sim' "
            "AND status NOT IN ('Encerrado', 'Cancelado')"
        )
        params: list = [cliente_id]
        if categoria:
            query += " AND categoria = ?"
            params.append(categoria)
        query += " ORDER BY atualizado_em DESC LIMIT 1"
        linha = con.execute(query, params).fetchone()
        return linha["caso_id"] if linha else None
    finally:
        con.close()


def criar_caso(
    cliente_id: str, titulo: str, categoria: str,
    tipo_caso: str = "Solicitação", origem: str = "Atendimento",
    canal_origem: str = "Email", criado_por: str = "Motor IA",
    descricao: Optional[str] = None,
) -> str:
    con = conectar()
    try:
        novo_id = _proximo_id(con, "caso", "caso_id", "CAS")
        agora = _agora_iso()
        con.execute(
            "INSERT INTO caso VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, cliente_id, titulo, descricao, categoria, tipo_caso, origem,
                canal_origem, "Aberto", "Triagem", "Normal", None, None, None, None,
                agora, agora, None, None, criado_por, criado_por, 1, "Sim", None, None,
            ),
        )
        _registrar_historico(con, novo_id, "criacao", f"Caso criado: {titulo}", criado_por=criado_por)
        con.commit()
        return novo_id
    finally:
        con.close()


def localizar_ou_criar_caso(cliente_id: str, titulo: str, categoria: str, **kwargs) -> str:
    existente = localizar_caso_aberto(cliente_id, categoria=categoria)
    if existente:
        return existente
    return criar_caso(cliente_id, titulo, categoria, **kwargs)


def atualizar_status(
    caso_id: str, novo_status: str, motivo: Optional[str] = None,
    alterado_por: str = "Motor de Casos",
) -> str:
    """Devolve o status anterior -- quem chama usa isso pra saber se o
    status realmente mudou (ex.: decidir se notifica o cliente)."""
    if novo_status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: {novo_status}. Use um de {sorted(STATUS_VALIDOS)}")

    con = conectar()
    try:
        linha = con.execute(
            "SELECT status, versao FROM caso WHERE caso_id = ?", (caso_id,)
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")
        status_antigo = linha["status"]

        con.execute(
            "UPDATE caso SET status = ?, atualizado_em = ?, alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ?",
            (novo_status, _agora_iso(), alterado_por, caso_id),
        )
        _registrar_historico(
            con, caso_id, "mudanca_status",
            motivo or f"Status alterado de {status_antigo} para {novo_status}",
            valor_anterior=status_antigo, valor_novo=novo_status, criado_por=alterado_por,
        )
        con.commit()
        return status_antigo
    finally:
        con.close()


def atualizar_responsavel(
    caso_id: str, novo_responsavel_id: Optional[str], alterado_por: str = "Motor de Casos",
) -> None:
    # RCA-007: toda troca de responsável gera registro em historico.
    con = conectar()
    try:
        linha = con.execute(
            "SELECT responsavel_id FROM caso WHERE caso_id = ?", (caso_id,)
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")
        if novo_responsavel_id:
            existe = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND ativo = 'Sim'",
                (novo_responsavel_id,),
            ).fetchone()
            if not existe:
                raise ValueError(f"Usuário não encontrado ou inativo: {novo_responsavel_id}")
        responsavel_antigo = linha["responsavel_id"]

        con.execute(
            "UPDATE caso SET responsavel_id = ?, atualizado_em = ?, alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ?",
            (novo_responsavel_id, _agora_iso(), alterado_por, caso_id),
        )
        _registrar_historico(
            con, caso_id, "troca_responsavel",
            f"Responsável alterado de {responsavel_antigo or '(nenhum)'} para {novo_responsavel_id or '(nenhum)'}",
            valor_anterior=responsavel_antigo, valor_novo=novo_responsavel_id, criado_por=alterado_por,
        )
        con.commit()
    finally:
        con.close()


def atualizar_descricao(
    caso_id: str, nova_descricao: str, alterado_por: str = "Motor de Casos",
) -> None:
    con = conectar()
    try:
        linha = con.execute(
            "SELECT descricao FROM caso WHERE caso_id = ?", (caso_id,)
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")

        con.execute(
            "UPDATE caso SET descricao = ?, atualizado_em = ?, alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ?",
            (nova_descricao, _agora_iso(), alterado_por, caso_id),
        )
        _registrar_historico(
            con, caso_id, "outro", "Descrição do caso editada.",
            valor_anterior=linha["descricao"], valor_novo=nova_descricao, criado_por=alterado_por,
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    caso_id = localizar_ou_criar_caso(
        "CLI-000002", titulo="Dúvida sobre transferência de arma",
        categoria="Transferência",
    )
    print(f"Caso localizado/criado: {caso_id}")

    # Chamando de novo com a mesma categoria -- deve reaproveitar o mesmo caso.
    caso_id_2 = localizar_ou_criar_caso(
        "CLI-000002", titulo="Outra pergunta sobre transferência",
        categoria="Transferência",
    )
    print(f"Segunda chamada (deve ser igual): {caso_id_2}")

    atualizar_status(caso_id, "Em andamento", motivo="Cliente respondeu com os documentos.")
    print("Status atualizado.")

    con = conectar()
    print("--- caso ---")
    for row in con.execute("SELECT caso_id, status, versao FROM caso WHERE caso_id = ?", (caso_id,)):
        print(dict(row))
    print("--- historico ---")
    for row in con.execute("SELECT * FROM historico WHERE caso_id = ? ORDER BY criado_em", (caso_id,)):
        print(dict(row))
    con.close()
