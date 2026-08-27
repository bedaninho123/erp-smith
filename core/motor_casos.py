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

# Mesmas quatro de core/motor_tarefas.py, de propósito: prioridade de
# caso e prioridade de tarefa aparecem lado a lado na mesma tela, e duas
# escalas diferentes ("Média" num lugar, "Normal" no outro) fariam a
# pessoa traduzir de cabeça. Tupla, não set, para a ordem valer na tela.
PRIORIDADES_VALIDAS = ("Baixa", "Normal", "Alta", "Urgente")

# Por onde o caso chegou. Inclui os que a IA nunca vai usar -- Presencial
# e Telefone -- porque o caso aberto à mão costuma ser exatamente esse:
# o cliente ligou ou apareceu na porta.
CANAIS_ORIGEM = ("Email", "WhatsApp", "Telefone", "Presencial", "Portal")


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def _registrar_historico(
    con, empresa_id: str, caso_id: str, tipo_evento: str, descricao: str,
    valor_anterior: Optional[str] = None, valor_novo: Optional[str] = None,
    criado_por: str = "Motor de Casos",
) -> None:
    novo_id = _proximo_id(con, "historico", "historico_id", "HIS")
    con.execute(
        "INSERT INTO historico (historico_id, empresa_id, caso_id, tipo_evento, "
        "descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (novo_id, empresa_id, caso_id, tipo_evento, descricao, valor_anterior,
         valor_novo, _agora_iso(), criado_por),
    )


def localizar_caso_aberto(
    empresa_id: str, cliente_id: str, categoria: Optional[str] = None
) -> Optional[str]:
    con = conectar(empresa_id)
    try:
        query = (
            "SELECT caso_id FROM caso WHERE empresa_id = ? AND cliente_id = ? "
            "AND ativo = 'Sim' AND status NOT IN ('Encerrado', 'Cancelado')"
        )
        params: list = [empresa_id, cliente_id]
        if categoria:
            query += " AND categoria = ?"
            params.append(categoria)
        query += " ORDER BY atualizado_em DESC LIMIT 1"
        linha = con.execute(query, params).fetchone()
        return linha["caso_id"] if linha else None
    finally:
        con.close()


def criar_caso(
    empresa_id: str, cliente_id: str, titulo: str, categoria: str,
    tipo_caso: str = "Solicitação", origem: str = "Atendimento",
    canal_origem: str = "Email", criado_por: str = "Motor IA",
    descricao: Optional[str] = None, prioridade: str = "Normal",
    responsavel_id: Optional[str] = None,
) -> str:
    """Abre um caso. Chamado pelo orquestrador quando chega mensagem, e
    pelo painel quando alguém abre à mão (cliente ligou, apareceu na
    porta) -- o mesmo caminho para os dois, para não existirem duas
    formas de um caso nascer com regras diferentes."""
    titulo = (titulo or "").strip()
    categoria = (categoria or "").strip()
    if not titulo:
        raise ValueError("Informe o título do caso.")
    if not categoria:
        raise ValueError("Informe a categoria do caso.")
    if prioridade not in PRIORIDADES_VALIDAS:
        raise ValueError(
            f"Prioridade inválida: {prioridade}. Use uma de {list(PRIORIDADES_VALIDAS)}."
        )

    con = conectar(empresa_id)
    try:
        # O cliente precisa ser desta empresa -- sem esta checagem, um
        # cliente_id de outra empresa criaria um caso órfão, com o dado
        # de duas empresas amarrado na mesma linha.
        dono = con.execute(
            "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
            (cliente_id, empresa_id),
        ).fetchone()
        if not dono:
            raise ValueError(f"Cliente não encontrado nesta empresa: {cliente_id}")

        # Funcionário de outra empresa nunca pode nascer responsável --
        # mesma checagem de atualizar_responsavel, pelo mesmo motivo.
        if responsavel_id:
            existe = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ? AND ativo = 'Sim'",
                (responsavel_id, empresa_id),
            ).fetchone()
            if not existe:
                raise ValueError(f"Usuário não encontrado ou inativo: {responsavel_id}")

        novo_id = _proximo_id(con, "caso", "caso_id", "CAS")
        agora = _agora_iso()
        con.execute(
            "INSERT INTO caso (caso_id, empresa_id, cliente_id, titulo, descricao, "
            "categoria, tipo_caso, origem, canal_origem, status, fase, prioridade, "
            "responsavel_id, criado_em, atualizado_em, criado_por, alterado_por, "
            "versao, ativo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, cliente_id, titulo, descricao, categoria,
                tipo_caso, origem, canal_origem, "Aberto", "Triagem", prioridade,
                responsavel_id, agora, agora, criado_por, criado_por, 1, "Sim",
            ),
        )
        _registrar_historico(
            con, empresa_id, novo_id, "criacao", f"Caso criado: {titulo}",
            criado_por=criado_por,
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def localizar_ou_criar_caso(
    empresa_id: str, cliente_id: str, titulo: str, categoria: str, **kwargs
) -> str:
    existente = localizar_caso_aberto(empresa_id, cliente_id, categoria=categoria)
    if existente:
        return existente
    return criar_caso(empresa_id, cliente_id, titulo, categoria, **kwargs)


def atualizar_status(
    empresa_id: str, caso_id: str, novo_status: str, motivo: Optional[str] = None,
    alterado_por: str = "Motor de Casos",
) -> str:
    """Devolve o status anterior -- quem chama usa isso pra saber se o
    status realmente mudou (ex.: decidir se notifica o cliente).

    O empresa_id no WHERE é o que impede um caso_id de outra empresa ser
    alterado -- mesma lógica em todas as funções deste módulo."""
    if novo_status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: {novo_status}. Use um de {sorted(STATUS_VALIDOS)}")

    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT status, versao, encerrado_em FROM caso WHERE caso_id = ? AND empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")
        status_antigo = linha["status"]

        # encerrado_em existia no schema desde o começo e nunca era
        # preenchido -- ou seja, "quantos casos você concluiu em agosto?"
        # não tinha resposta. É carimbado ao encerrar e APAGADO ao
        # reabrir, mesma regra da data de conclusão de uma tarefa: caso
        # reaberto com "encerrado em" de antes seria data que já não
        # significa nada. 'Cancelado' não conta como encerramento --
        # trabalho cancelado não é trabalho entregue.
        agora = _agora_iso()
        if novo_status == "Encerrado":
            encerrado_em = linha["encerrado_em"] or agora
        else:
            encerrado_em = None

        con.execute(
            "UPDATE caso SET status = ?, encerrado_em = ?, atualizado_em = ?, "
            "alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ? AND empresa_id = ?",
            (novo_status, encerrado_em, agora, alterado_por, caso_id, empresa_id),
        )
        _registrar_historico(
            con, empresa_id, caso_id, "mudanca_status",
            motivo or f"Status alterado de {status_antigo} para {novo_status}",
            valor_anterior=status_antigo, valor_novo=novo_status, criado_por=alterado_por,
        )
        con.commit()
        return status_antigo
    finally:
        con.close()


def atualizar_responsavel(
    empresa_id: str, caso_id: str, novo_responsavel_id: Optional[str],
    alterado_por: str = "Motor de Casos",
) -> None:
    # RCA-007: toda troca de responsável gera registro em historico.
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT responsavel_id FROM caso WHERE caso_id = ? AND empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")
        if novo_responsavel_id:
            # Funcionário de outra empresa nunca pode virar responsável --
            # seria dado de duas empresas amarrado na mesma linha.
            existe = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ? AND ativo = 'Sim'",
                (novo_responsavel_id, empresa_id),
            ).fetchone()
            if not existe:
                raise ValueError(f"Usuário não encontrado ou inativo: {novo_responsavel_id}")
        responsavel_antigo = linha["responsavel_id"]

        con.execute(
            "UPDATE caso SET responsavel_id = ?, atualizado_em = ?, alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ? AND empresa_id = ?",
            (novo_responsavel_id, _agora_iso(), alterado_por, caso_id, empresa_id),
        )
        _registrar_historico(
            con, empresa_id, caso_id, "troca_responsavel",
            f"Responsável alterado de {responsavel_antigo or '(nenhum)'} para {novo_responsavel_id or '(nenhum)'}",
            valor_anterior=responsavel_antigo, valor_novo=novo_responsavel_id, criado_por=alterado_por,
        )
        con.commit()
    finally:
        con.close()


def atualizar_descricao(
    empresa_id: str, caso_id: str, nova_descricao: str,
    alterado_por: str = "Motor de Casos",
) -> None:
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT descricao FROM caso WHERE caso_id = ? AND empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Caso não encontrado: {caso_id}")

        con.execute(
            "UPDATE caso SET descricao = ?, atualizado_em = ?, alterado_por = ?, versao = versao + 1 "
            "WHERE caso_id = ? AND empresa_id = ?",
            (nova_descricao, _agora_iso(), alterado_por, caso_id, empresa_id),
        )
        _registrar_historico(
            con, empresa_id, caso_id, "outro", "Descrição do caso editada.",
            valor_anterior=linha["descricao"], valor_novo=nova_descricao, criado_por=alterado_por,
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    caso_id = localizar_ou_criar_caso(
        EMPRESA, "CLI-000002", titulo="Dúvida sobre transferência de arma",
        categoria="Transferência",
    )
    print(f"Caso localizado/criado: {caso_id}")

    # Chamando de novo com a mesma categoria -- deve reaproveitar o mesmo caso.
    caso_id_2 = localizar_ou_criar_caso(
        EMPRESA, "CLI-000002", titulo="Outra pergunta sobre transferência",
        categoria="Transferência",
    )
    print(f"Segunda chamada (deve ser igual): {caso_id_2}")

    atualizar_status(EMPRESA, caso_id, "Em andamento", motivo="Cliente respondeu com os documentos.")
    print("Status atualizado.")

    con = conectar(EMPRESA)
    print("--- caso ---")
    for row in con.execute("SELECT caso_id, status, versao FROM caso WHERE caso_id = ?", (caso_id,)):
        print(dict(row))
    print("--- historico ---")
    for row in con.execute("SELECT * FROM historico WHERE caso_id = ? ORDER BY criado_em", (caso_id,)):
        print(dict(row))
    con.close()
