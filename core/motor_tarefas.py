"""Motor de Tarefas: o que uma PESSOA precisa fazer, e até quando.

A tabela `tarefas` existe no schema desde o Core mínimo, mas até aqui só
era escrita pelo script de migração de dado de teste e lida pelo
`motor_ia/montador_contexto.py` -- ou seja, prazo de despachante não
morava em lugar nenhum do sistema. Este módulo é o que faltava.

Não confundir com `processo.proxima_acao`: aquilo é o estado de um
processo perante o órgão ("aguardando comprovante"), texto que descreve
a situação. Tarefa é trabalho com dono e data, que alguém marca como
feito. Um processo parado pode ter três tarefas; uma tarefa pode não ter
processo nenhum (ligar para o cliente).

**Toda tarefa pertence a um caso** -- `caso_id` e `cliente_id` são NOT
NULL no schema, e é de propósito: tarefa solta viraria uma segunda lista
de afazeres sem ligação com o atendimento, e ninguém acharia depois. O
`cliente_id` NUNCA vem de quem chama: é lido do próprio caso, senão uma
tarefa poderia nascer amarrando o caso de uma pessoa ao nome de outra.

A IA não cria nem conclui tarefa. Mesmo espírito do
core/motor_casos.py: quem decide que o trabalho foi feito é o humano que
fez o trabalho.
"""
from datetime import date, datetime, timezone
from typing import Optional

from core.conexao import conectar

# Lista controlada em código, não CHECK no schema -- mesmo padrão do
# status do Caso e dos papéis de usuário. "Pendente" é o primeiro valor
# porque já é o que as linhas migradas da planilha usam; mudar o nome
# agora exigiria migração sem ganho nenhum.
STATUS_VALIDOS = ("Pendente", "Em andamento", "Concluída", "Cancelada")

# O que ainda pede trabalho de alguém. É esta tupla que decide o que
# aparece na fila da tela e no que o painel conta como "em aberto" --
# tarefa cancelada não é pendência, é decisão registrada.
STATUS_ABERTOS = ("Pendente", "Em andamento")

PRIORIDADES_VALIDAS = ("Baixa", "Normal", "Alta", "Urgente")

# `tipo` continua texto livre (o painel oferece sugestões numa datalist,
# não uma lista fechada): o serviço de um despachante de clube de tiro
# não tem os mesmos tipos de tarefa que o do próximo domínio, e uma lista
# fechada aqui viraria dívida na primeira semana de uso.
TIPOS_SUGERIDOS = (
    "Cobrar documento",
    "Consultar andamento",
    "Ligar para o cliente",
    "Protocolar",
    "Conferir documento",
    "Agendar",
)


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hoje_local() -> str:
    """A data de hoje NA MÁQUINA, em 'AAAA-MM-DD'.

    Existe pra não usar `date('now')` do SQLite, que é UTC: às 21h de
    Brasília o UTC já virou o dia seguinte, e toda tarefa que vence hoje
    apareceria como atrasada -- justamente no fim do expediente, quando a
    tela mais é olhada.
    """
    return date.today().isoformat()


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def _registrar_historico(
    con, empresa_id: str, caso_id: str, descricao: str,
    valor_anterior: Optional[str] = None, valor_novo: Optional[str] = None,
    criado_por: str = "Motor de Tarefas",
) -> None:
    """Evento de tarefa na linha do tempo do Caso.

    Sempre 'outro': `historico.tipo_evento` tem CHECK no schema com cinco
    valores, todos sobre o Caso em si. Um 'mudanca_status' aqui seria
    lido como mudança de status DO CASO por qualquer código que filtre
    por tipo -- o texto da descrição já diz que é tarefa, e diz melhor.

    Só registra o que muda o combinado com o cliente: criação, status,
    responsável e prazo. Editar a descrição ou uma observação não entra,
    senão o histórico do caso vira o log de digitação de uma pessoa e
    deixa de servir pra reconstituir o atendimento.
    """
    novo_id = _proximo_id(con, "historico", "historico_id", "HIS")
    con.execute(
        "INSERT INTO historico (historico_id, empresa_id, caso_id, tipo_evento, "
        "descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,'outro',?,?,?,?,?)",
        (novo_id, empresa_id, caso_id, descricao, valor_anterior, valor_novo,
         _agora_iso(), criado_por),
    )


def normalizar_prazo(prazo: Optional[str]) -> Optional[str]:
    """Prazo é um DIA, não um instante -- guarda 'AAAA-MM-DD' e nada mais.

    O campo <input type="date"> do painel já manda nesse formato, mas as
    linhas vindas da planilha têm ISO completo ('...T00:00:00Z'). Cortar
    pro dia nos dois casos é o que faz a comparação de atraso ser sempre
    entre coisas comparáveis. Vazio vira None: "sem prazo" é um estado
    legítimo (tarefa que só precisa ser feita algum dia), e string vazia
    no banco leria como prazo existente e ilegível.
    """
    prazo = (prazo or "").strip()
    if not prazo:
        return None
    dia = prazo[:10]
    try:
        datetime.strptime(dia, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Prazo inválido: {prazo}. Use o formato AAAA-MM-DD.")
    return dia


def _validar_responsavel(con, empresa_id: str, responsavel_id: Optional[str]) -> None:
    if not responsavel_id:
        return
    # Funcionário de outra empresa nunca pode ser dono de uma tarefa --
    # mesma checagem de core/motor_casos.py::atualizar_responsavel.
    existe = con.execute(
        "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ? AND ativo = 'Sim'",
        (responsavel_id, empresa_id),
    ).fetchone()
    if not existe:
        raise ValueError(f"Usuário não encontrado ou inativo: {responsavel_id}")


def criar_tarefa(
    empresa_id: str,
    caso_id: str,
    tipo: str,
    descricao: Optional[str] = None,
    responsavel_id: Optional[str] = None,
    prazo: Optional[str] = None,
    prioridade: str = "Normal",
    processo_id: Optional[str] = None,
    observacoes: Optional[str] = None,
    criado_por: str = "Painel administrativo",
) -> str:
    tipo = (tipo or "").strip()
    if not tipo:
        raise ValueError("Informe o tipo da tarefa.")
    if prioridade not in PRIORIDADES_VALIDAS:
        raise ValueError(
            f"Prioridade inválida: {prioridade}. Use uma de {list(PRIORIDADES_VALIDAS)}."
        )
    prazo = normalizar_prazo(prazo)

    con = conectar(empresa_id)
    try:
        # O cliente vem DAQUI, não de quem chamou (ver docstring do
        # módulo) -- e o filtro por empresa neste SELECT é o que impede
        # uma tarefa de nascer pendurada no caso de outro despachante.
        caso = con.execute(
            "SELECT cliente_id FROM caso WHERE caso_id = ? AND empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
        if not caso:
            raise ValueError(f"Caso não encontrado nesta empresa: {caso_id}")

        if processo_id:
            # Não basta o processo ser da empresa: tem que ser DESTE caso.
            # Dois casos da mesma empresa é o cruzamento que o filtro de
            # empresa não pega -- mesma armadilha do upload do Portal.
            do_caso = con.execute(
                "SELECT 1 FROM processo WHERE processo_id = ? AND caso_id = ? AND empresa_id = ?",
                (processo_id, caso_id, empresa_id),
            ).fetchone()
            if not do_caso:
                raise ValueError(f"Processo não pertence a este caso: {processo_id}")

        _validar_responsavel(con, empresa_id, responsavel_id)

        novo_id = _proximo_id(con, "tarefas", "tarefa_id", "TAR")
        con.execute(
            "INSERT INTO tarefas (tarefa_id, empresa_id, caso_id, cliente_id, "
            "processo_id, tipo, descricao, responsavel_id, prazo, prioridade, "
            "status, data_conclusao, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?)",
            (novo_id, empresa_id, caso_id, caso["cliente_id"], processo_id, tipo,
             descricao, responsavel_id, prazo, prioridade, "Pendente", observacoes),
        )
        _registrar_historico(
            con, empresa_id, caso_id,
            f"Tarefa {novo_id} criada: {tipo}"
            + (f" (prazo {prazo})" if prazo else " (sem prazo)"),
            criado_por=criado_por,
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def listar_tarefas(
    empresa_id: str,
    status: Optional[str] = None,
    responsavel_id: Optional[str] = None,
    caso_id: Optional[str] = None,
    vencimento: Optional[str] = None,
    somente_abertas: bool = False,
) -> list[dict]:
    """As tarefas da empresa, já com nome de cliente e de responsável.

    `vencimento` filtra pela data: 'atrasadas', 'hoje', 'semana' (os
    próximos 7 dias, hoje incluído) ou 'sem_prazo'. Atrasada e hoje só
    fazem sentido para tarefa em aberto -- uma concluída ontem com prazo
    de anteontem não é uma pendência atrasada, é trabalho feito --, então
    esses dois já trazem o recorte de aberto embutido.

    A ordenação existe pra tela ser útil sem ninguém mexer em filtro:
    quem tem prazo primeiro, do mais antigo pro mais novo, e prazo nenhum
    por último (é o que pode esperar).
    """
    hoje = hoje_local()

    query = (
        "SELECT t.*, c.titulo AS caso_titulo, c.status AS caso_status, "
        "cl.nome AS cliente_nome, u.nome AS responsavel_nome, "
        "s.nome_servico AS processo_servico "
        "FROM tarefas t "
        "JOIN caso c ON c.caso_id = t.caso_id AND c.empresa_id = t.empresa_id "
        "JOIN cliente cl ON cl.cliente_id = t.cliente_id AND cl.empresa_id = t.empresa_id "
        "LEFT JOIN usuario u ON u.usuario_id = t.responsavel_id "
        "LEFT JOIN processo p ON p.processo_id = t.processo_id AND p.empresa_id = t.empresa_id "
        "LEFT JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = t.empresa_id "
        "WHERE t.empresa_id = ?"
    )
    params: list = [empresa_id]

    if status:
        query += " AND t.status = ?"
        params.append(status)
    if somente_abertas:
        query += f" AND t.status IN ({','.join('?' * len(STATUS_ABERTOS))})"
        params.extend(STATUS_ABERTOS)
    if responsavel_id:
        query += " AND t.responsavel_id = ?"
        params.append(responsavel_id)
    if caso_id:
        query += " AND t.caso_id = ?"
        params.append(caso_id)

    # SUBSTR(prazo, 1, 10) em vez do valor cru: as linhas migradas da
    # planilha guardam ISO completo, e '2026-07-30T00:00:00Z' < '2026-07-30'
    # é falso na comparação de texto -- a tarefa sumiria do filtro de hoje.
    if vencimento == "atrasadas":
        query += (
            f" AND t.status IN ({','.join('?' * len(STATUS_ABERTOS))})"
            " AND t.prazo IS NOT NULL AND SUBSTR(t.prazo, 1, 10) < ?"
        )
        params.extend(STATUS_ABERTOS)
        params.append(hoje)
    elif vencimento == "hoje":
        query += (
            f" AND t.status IN ({','.join('?' * len(STATUS_ABERTOS))})"
            " AND SUBSTR(t.prazo, 1, 10) = ?"
        )
        params.extend(STATUS_ABERTOS)
        params.append(hoje)
    elif vencimento == "semana":
        query += (
            f" AND t.status IN ({','.join('?' * len(STATUS_ABERTOS))})"
            " AND t.prazo IS NOT NULL AND SUBSTR(t.prazo, 1, 10) BETWEEN ? AND date(?, '+7 day')"
        )
        params.extend(STATUS_ABERTOS)
        params.extend([hoje, hoje])
    elif vencimento == "sem_prazo":
        query += " AND t.prazo IS NULL"

    query += " ORDER BY (t.prazo IS NULL), SUBSTR(t.prazo, 1, 10), t.tarefa_id"

    con = conectar(empresa_id)
    try:
        linhas = [dict(l) for l in con.execute(query, params).fetchall()]
    finally:
        con.close()

    for linha in linhas:
        linha["prazo"] = linha["prazo"][:10] if linha["prazo"] else None
        linha["atrasada"] = bool(
            linha["prazo"] and linha["prazo"] < hoje and linha["status"] in STATUS_ABERTOS
        )
        linha["vence_hoje"] = bool(
            linha["prazo"] == hoje and linha["status"] in STATUS_ABERTOS
        )
    return linhas


def contar_tarefas(empresa_id: str, responsavel_id: Optional[str] = None) -> dict:
    """Os três números que a tela inicial mostra. Uma consulta só.

    Passa por listar_tarefas de propósito, em vez de repetir os
    comparativos de data em SQL: se a regra de "atrasada" mudar (ex.:
    passar a ignorar fim de semana), muda num lugar e a contagem e a
    lista continuam concordando -- duas implementações da mesma regra
    divergem cedo ou tarde, e aí o painel mostra 3 atrasadas numa lista
    com 2 linhas.
    """
    abertas = listar_tarefas(
        empresa_id, responsavel_id=responsavel_id, somente_abertas=True
    )
    return {
        "abertas": len(abertas),
        "atrasadas": sum(1 for t in abertas if t["atrasada"]),
        "hoje": sum(1 for t in abertas if t["vence_hoje"]),
    }


def atualizar_tarefa(
    empresa_id: str,
    tarefa_id: str,
    tipo: str,
    descricao: Optional[str],
    responsavel_id: Optional[str],
    prazo: Optional[str],
    prioridade: str,
    status: str,
    observacoes: Optional[str],
    alterado_por: str = "Painel administrativo",
) -> None:
    tipo = (tipo or "").strip()
    if not tipo:
        raise ValueError("Informe o tipo da tarefa.")
    if status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: {status}. Use um de {list(STATUS_VALIDOS)}.")
    if prioridade not in PRIORIDADES_VALIDAS:
        raise ValueError(
            f"Prioridade inválida: {prioridade}. Use uma de {list(PRIORIDADES_VALIDAS)}."
        )
    prazo = normalizar_prazo(prazo)

    con = conectar(empresa_id)
    try:
        atual = con.execute(
            "SELECT caso_id, status, responsavel_id, prazo, data_conclusao "
            "FROM tarefas WHERE tarefa_id = ? AND empresa_id = ?",
            (tarefa_id, empresa_id),
        ).fetchone()
        if not atual:
            raise ValueError(f"Tarefa não encontrada: {tarefa_id}")

        _validar_responsavel(con, empresa_id, responsavel_id)

        # A data de conclusão é consequência do status, nunca um campo
        # que alguém digita: concluir carimba a data, e reabrir apaga.
        # Sem isso, uma tarefa reaberta continuaria "concluída em" uma
        # data que já não significa nada.
        if status == "Concluída":
            data_conclusao = atual["data_conclusao"] or _agora_iso()
        else:
            data_conclusao = None

        con.execute(
            "UPDATE tarefas SET tipo=?, descricao=?, responsavel_id=?, prazo=?, "
            "prioridade=?, status=?, data_conclusao=?, observacoes=? "
            "WHERE tarefa_id=? AND empresa_id=?",
            (tipo, descricao, responsavel_id, prazo, prioridade, status,
             data_conclusao, observacoes, tarefa_id, empresa_id),
        )

        if status != atual["status"]:
            _registrar_historico(
                con, empresa_id, atual["caso_id"],
                f"Tarefa {tarefa_id} ({tipo}): status alterado de "
                f"{atual['status']} para {status}",
                valor_anterior=atual["status"], valor_novo=status,
                criado_por=alterado_por,
            )
        if (responsavel_id or None) != (atual["responsavel_id"] or None):
            _registrar_historico(
                con, empresa_id, atual["caso_id"],
                f"Tarefa {tarefa_id} ({tipo}): responsável alterado de "
                f"{atual['responsavel_id'] or '(nenhum)'} para "
                f"{responsavel_id or '(nenhum)'}",
                valor_anterior=atual["responsavel_id"], valor_novo=responsavel_id,
                criado_por=alterado_por,
            )
        prazo_antigo = atual["prazo"][:10] if atual["prazo"] else None
        if prazo != prazo_antigo:
            _registrar_historico(
                con, empresa_id, atual["caso_id"],
                f"Tarefa {tarefa_id} ({tipo}): prazo alterado de "
                f"{prazo_antigo or '(sem prazo)'} para {prazo or '(sem prazo)'}",
                valor_anterior=prazo_antigo, valor_novo=prazo,
                criado_por=alterado_por,
            )
        con.commit()
    finally:
        con.close()


def concluir_tarefa(
    empresa_id: str, tarefa_id: str, alterado_por: str = "Painel administrativo",
) -> None:
    """Atalho do botão "Concluir" da lista -- a ação mais comum da tela,
    e a única que precisa acontecer sem abrir formulário nenhum.

    Reaproveita atualizar_tarefa em vez de fazer o próprio UPDATE: é lá
    que mora a regra da data de conclusão e o registro no histórico.
    """
    con = conectar(empresa_id)
    try:
        atual = con.execute(
            "SELECT tipo, descricao, responsavel_id, prazo, prioridade, observacoes "
            "FROM tarefas WHERE tarefa_id = ? AND empresa_id = ?",
            (tarefa_id, empresa_id),
        ).fetchone()
        if not atual:
            raise ValueError(f"Tarefa não encontrada: {tarefa_id}")
        campos = dict(atual)
    finally:
        con.close()

    atualizar_tarefa(
        empresa_id, tarefa_id, tipo=campos["tipo"], descricao=campos["descricao"],
        responsavel_id=campos["responsavel_id"], prazo=campos["prazo"],
        prioridade=campos["prioridade"], status="Concluída",
        observacoes=campos["observacoes"], alterado_por=alterado_por,
    )


if __name__ == "__main__":
    # Só lógica de data, sem banco -- pode rodar em qualquer máquina.
    print(f"Hoje (local): {hoje_local()}")
    print(f"Status válidos: {list(STATUS_VALIDOS)}")
    print(f"Em aberto: {list(STATUS_ABERTOS)}")
    print(f"Prioridades: {list(PRIORIDADES_VALIDAS)}")
    for bruto in ["2026-08-27", "2026-08-27T00:00:00Z", "", None]:
        print(f"  normalizar_prazo({bruto!r}) -> {normalizar_prazo(bruto)!r}")
    try:
        normalizar_prazo("27/08/2026")
    except ValueError as e:
        print(f"  data em formato brasileiro é recusada: {e}")
