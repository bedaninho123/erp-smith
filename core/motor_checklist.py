"""Rastreamento de documento recebido vs. exigido, por processo. Estado
do Core, sem IA -- a decisão de que um arquivo atende a um item do
checklist (documento_exigido) é sempre de uma pessoa, nunca inferida
automaticamente: decidir "este PDF é a certidão X" é julgamento
humano/regra de negócio, não algo que a IA decide (ver CLAUDE.md, "a IA
nunca contém regra de negócio").

Quem cria a ligação mudou em 2026-07-29, e por isso ela ganhou estado:

- **Funcionário, pelo painel** -- ele abriu o arquivo e decidiu que
  atende o item. A marcação já nasce `Aprovado`, porque a conferência
  aconteceu no mesmo gesto.
- **Cliente, pelo Portal** -- ele envia o arquivo dizendo a que item
  corresponde. Isso é uma *afirmação dele*, não uma conferência: nasce
  `Aguardando aprovação` e só vira `Aprovado` quando alguém da equipe
  olhar.

`Recusado` continua existindo como linha em vez de ser apagado: é o que
guarda o motivo pra mostrar ao cliente ("foto ilegível") e o que impede
o histórico de sumir. Para efeito de checklist, item com documento
recusado volta a contar como faltando.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

STATUS_AGUARDANDO = "Aguardando aprovação"
STATUS_APROVADO = "Aprovado"
STATUS_RECUSADO = "Recusado"

MARCADO_POR_CLIENTE = "Cliente (Portal)"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna}, 5) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def _registrar_historico(
    con, empresa_id: str, caso_id: str, descricao: str,
    valor_anterior: Optional[str], valor_novo: Optional[str], criado_por: str,
) -> None:
    """Mesma regra do resto do Core: mudança de estado sempre deixa
    rastro (CLAUDE.md). `tipo_evento` usa 'outro' porque a lista fechada
    do schema cobre eventos do Caso em si -- documento é evento dentro
    do caso, não uma mudança de status dele."""
    con.execute(
        "INSERT INTO historico (historico_id, empresa_id, caso_id, tipo_evento, "
        "descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,'outro',?,?,?,?,?)",
        (
            _proximo_id(con, "historico", "historico_id", "HIS"), empresa_id, caso_id,
            descricao, valor_anterior, valor_novo, _agora_iso(), criado_por,
        ),
    )


def status_checklist(con, empresa_id: str, processo_id: str) -> list:
    """Itens exigidos pelo serviço do processo + quais documentos já foram
    marcados atendendo cada um. Aceita uma conexão já aberta (chamado de
    dentro de webapp/app.py, que já tem uma pra montar o resto da tela de
    Detalhe do Caso) -- não abre/fecha conexão própria, diferente de
    marcar_documento()/desmarcar(). Por isso recebe empresa_id como
    parâmetro em vez de tirar da conexão."""
    linha = con.execute(
        "SELECT servico_id FROM processo WHERE processo_id = ? AND empresa_id = ?",
        (processo_id, empresa_id),
    ).fetchone()
    if not linha:
        raise ValueError(f"Processo não encontrado: {processo_id}")
    servico_id = linha["servico_id"]

    # Itens do serviço + os extras DESTE processo (processo_id preenchido).
    # O extra herda a `ordem` do item de que foi copiado, e o desempate
    # põe o original primeiro e os extras logo abaixo, na ordem em que
    # foram criados.
    itens = con.execute(
        "SELECT documento_exigido_id, grupo, item, ordem, processo_id FROM documento_exigido "
        "WHERE servico_id = ? AND empresa_id = ? AND ativo = 'Sim' "
        "AND (processo_id IS NULL OR processo_id = ?) "
        "ORDER BY ordem, processo_id IS NOT NULL, documento_exigido_id",
        (servico_id, empresa_id, processo_id),
    ).fetchall()

    resultado = []
    for item in itens:
        marcados = con.execute(
            "SELECT dck.documento_checklist_id, dck.documento_id, dck.status, "
            "dck.motivo_recusa, dck.revisado_em, dck.revisado_por, dck.marcado_por, "
            "d.nome_arquivo "
            "FROM documento_checklist dck "
            "JOIN documento d ON d.documento_id = dck.documento_id "
            "WHERE dck.processo_id = ? AND dck.documento_exigido_id = ? AND dck.empresa_id = ? "
            "ORDER BY dck.marcado_em",
            (processo_id, item["documento_exigido_id"], empresa_id),
        ).fetchall()
        documentos = [dict(m) for m in marcados]

        aprovados = [d for d in documentos if d["status"] == STATUS_APROVADO]
        aguardando = [d for d in documentos if d["status"] == STATUS_AGUARDANDO]
        recusados = [d for d in documentos if d["status"] == STATUS_RECUSADO]

        # Aprovado ganha de aguardando, que ganha de faltando. Um item já
        # resolvido não volta a "aguardando" só porque o cliente mandou
        # um arquivo a mais.
        if aprovados:
            estado = "aprovado"
        elif aguardando:
            estado = "aguardando"
        else:
            estado = "faltando"

        resultado.append({
            "documento_exigido_id": item["documento_exigido_id"],
            "grupo": item["grupo"],
            "item": item["item"],
            "ordem": item["ordem"],
            "extra": item["processo_id"] is not None,
            "estado": estado,
            # `recebido` continua significando "este item está resolvido"
            # -- é o que alimenta a contagem X/Y e o anel de progresso.
            # Documento pendente de conferência não conta como resolvido:
            # contar inflaria o progresso com trabalho que ninguém fez
            # ainda.
            "recebido": estado == "aprovado",
            "documentos": documentos,
            "aguardando": aguardando,
            # Só interessa quando o item voltou a faltar -- é o que
            # explica ao cliente por que ele precisa reenviar.
            "motivo_recusa": recusados[-1]["motivo_recusa"] if recusados and estado == "faltando" else None,
        })
    return resultado


def adicionar_item_extra(
    empresa_id: str, processo_id: str, documento_exigido_id: str,
    complemento: str = "",
) -> str:
    """Mais um item igual a um existente, só neste processo (2026-09-24).

    Pedido do usuário: quem tem pistola, carabina e revólver precisa de
    uma capacidade técnica para cada. `complemento` diz de qual ("Carabina")
    e vira parte do nome; sem ele, "adicional". O texto base é sempre o do
    item de SERVIÇO -- copiar de um extra faria "X — Carabina — Revólver".
    """
    con = conectar(empresa_id)
    try:
        processo = con.execute(
            "SELECT servico_id FROM processo WHERE processo_id = ? AND empresa_id = ?",
            (processo_id, empresa_id),
        ).fetchone()
        if not processo:
            raise ValueError(f"Processo não encontrado: {processo_id}")
        base = con.execute(
            "SELECT grupo, item, ordem, processo_id FROM documento_exigido "
            "WHERE documento_exigido_id = ? AND servico_id = ? AND empresa_id = ? "
            "AND ativo = 'Sim' AND (processo_id IS NULL OR processo_id = ?)",
            (documento_exigido_id, processo["servico_id"], empresa_id, processo_id),
        ).fetchone()
        if not base:
            raise ValueError("Este item não pertence ao checklist deste processo.")
        texto = base["item"]
        if base["processo_id"] is not None:
            texto = texto.split(" — ")[0]
        complemento = (complemento or "").strip()
        novo_texto = f"{texto} — {complemento or 'adicional'}"

        novo_id = _proximo_id(con, "documento_exigido", "documento_exigido_id", "DEX")
        con.execute(
            "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
            "grupo, item, ordem, ativo, processo_id) VALUES (?,?,?,?,?,?,'Sim',?)",
            (novo_id, empresa_id, processo["servico_id"], base["grupo"], novo_texto,
             base["ordem"], processo_id),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def remover_item_extra(empresa_id: str, processo_id: str, documento_exigido_id: str) -> None:
    """Tira um item extra criado por engano. Só extra deste processo, e só
    se nenhum documento foi marcado nele -- marcação é registro de
    conferência, e sumir com o item deixaria a marcação apontando para o
    nada. Item do serviço nunca sai por aqui."""
    con = conectar(empresa_id)
    try:
        item = con.execute(
            "SELECT 1 FROM documento_exigido WHERE documento_exigido_id = ? "
            "AND empresa_id = ? AND processo_id = ?",
            (documento_exigido_id, empresa_id, processo_id),
        ).fetchone()
        if not item:
            raise ValueError("Só dá para remover item adicionado a este processo.")
        marcado = con.execute(
            "SELECT 1 FROM documento_checklist WHERE documento_exigido_id = ? AND empresa_id = ?",
            (documento_exigido_id, empresa_id),
        ).fetchone()
        if marcado:
            raise ValueError("Este item já tem documento marcado. Desmarque antes de remover.")
        con.execute(
            "DELETE FROM documento_exigido WHERE documento_exigido_id = ? AND empresa_id = ?",
            (documento_exigido_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


def _conferir_processo_e_item(con, empresa_id: str, processo_id: str, documento_exigido_id: str):
    """Processo e item de checklist têm que ser desta empresa, e o item
    tem que ser do serviço deste processo. Devolve a linha do processo."""
    processo = con.execute(
        "SELECT servico_id, caso_id, cliente_id FROM processo WHERE processo_id = ? AND empresa_id = ?",
        (processo_id, empresa_id),
    ).fetchone()
    if not processo:
        raise ValueError(f"Processo não encontrado: {processo_id}")

    # Item extra de OUTRO processo não serve aqui, mesmo sendo do
    # mesmo serviço -- é a carabina de outra pessoa.
    existe_item = con.execute(
        "SELECT 1 FROM documento_exigido WHERE documento_exigido_id = ? "
        "AND servico_id = ? AND empresa_id = ? "
        "AND (processo_id IS NULL OR processo_id = ?)",
        (documento_exigido_id, processo["servico_id"], empresa_id, processo_id),
    ).fetchone()
    if not existe_item:
        raise ValueError("Este item de checklist não pertence ao serviço deste processo.")
    return processo


def conferir_item(empresa_id: str, processo_id: str, documento_exigido_id: str) -> dict:
    """A mesma conferência de marcar_documento(), para quem precisa dela
    ANTES de gravar o arquivo em disco (envio pelo checklist do painel):
    item errado descoberto depois deixaria um arquivo solto no caso."""
    con = conectar(empresa_id)
    try:
        return dict(_conferir_processo_e_item(con, empresa_id, processo_id, documento_exigido_id))
    finally:
        con.close()


def marcar_documento(
    empresa_id: str, processo_id: str, documento_exigido_id: str, documento_id: str,
    marcado_por: str = "Painel administrativo",
    status: str = STATUS_APROVADO,
) -> str:
    """`status` só é informado por quem chama de fora da equipe: o Portal
    passa STATUS_AGUARDANDO. O padrão continua sendo aprovado porque o
    chamador histórico (painel) é uma pessoa conferindo o arquivo."""
    if status not in (STATUS_APROVADO, STATUS_AGUARDANDO):
        raise ValueError(f"status inválido para uma marcação nova: {status}")

    con = conectar(empresa_id)
    try:
        # Cada um dos três IDs é conferido contra a empresa: processo,
        # item de checklist e documento têm que ser todos dela.
        processo = _conferir_processo_e_item(con, empresa_id, processo_id, documento_exigido_id)

        # E o documento tem que ser da MESMA PESSOA do processo (2026-10-20).
        # O filtro de empresa não cobre dois clientes do mesmo despachante:
        # sem isto, o arquivo do Bruno marcado no processo da Ana apareceria
        # no checklist que a Ana vê no Portal.
        existe_documento = con.execute(
            "SELECT 1 FROM documento WHERE documento_id = ? AND empresa_id = ? AND cliente_id = ?",
            (documento_id, empresa_id, processo["cliente_id"]),
        ).fetchone()
        if not existe_documento:
            raise ValueError(f"Documento não encontrado: {documento_id}")

        ja_marcado = con.execute(
            "SELECT status FROM documento_checklist "
            "WHERE processo_id = ? AND documento_exigido_id = ? AND documento_id = ?",
            (processo_id, documento_exigido_id, documento_id),
        ).fetchone()
        if ja_marcado:
            if ja_marcado["status"] == STATUS_RECUSADO:
                # Mensagem própria: "já está marcado" faria o cliente
                # achar que deu certo, quando na verdade este arquivo
                # exato já foi olhado e recusado -- ele precisa enviar
                # outro, não reenviar o mesmo.
                raise ValueError(
                    "Este arquivo já foi enviado para este item e recusado. Envie um novo arquivo."
                )
            raise ValueError("Este documento já está marcado para este item.")

        novo_id = _proximo_id(con, "documento_checklist", "documento_checklist_id", "DCK")
        con.execute(
            "INSERT INTO documento_checklist (documento_checklist_id, empresa_id, "
            "processo_id, documento_exigido_id, documento_id, marcado_em, marcado_por, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (novo_id, empresa_id, processo_id, documento_exigido_id, documento_id,
             _agora_iso(), marcado_por, status),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def _carregar_pendencia(con, empresa_id: str, documento_checklist_id: str) -> dict:
    """Carrega a marcação junto do caso e do item a que ela pertence.

    O JOIN existe pra conseguir o caso_id (o histórico é sempre por caso)
    e o texto do item (a descrição do evento precisa dizer *qual*
    documento foi decidido). Todos os saltos filtram por empresa: um
    documento_checklist_id de outra empresa não pode chegar até aqui e
    revelar nome de item, de processo ou de caso.
    """
    linha = con.execute(
        "SELECT dck.documento_checklist_id, dck.status, dck.processo_id, "
        "       dck.documento_id, p.caso_id, dex.item "
        "FROM documento_checklist dck "
        "JOIN processo p ON p.processo_id = dck.processo_id AND p.empresa_id = dck.empresa_id "
        "JOIN documento_exigido dex ON dex.documento_exigido_id = dck.documento_exigido_id "
        "     AND dex.empresa_id = dck.empresa_id "
        "WHERE dck.documento_checklist_id = ? AND dck.empresa_id = ?",
        (documento_checklist_id, empresa_id),
    ).fetchone()
    if not linha:
        raise ValueError(f"Marcação não encontrada: {documento_checklist_id}")
    return dict(linha)


def aprovar(
    empresa_id: str, documento_checklist_id: str,
    revisado_por: str = "Painel administrativo",
) -> dict:
    """Confirma que o arquivo enviado atende ao item. Devolve o caso e o
    item, que é o que a camada de cima precisa pra avisar/redirecionar."""
    con = conectar(empresa_id)
    try:
        pendencia = _carregar_pendencia(con, empresa_id, documento_checklist_id)
        if pendencia["status"] == STATUS_APROVADO:
            raise ValueError("Este documento já está aprovado.")

        con.execute(
            "UPDATE documento_checklist SET status = ?, revisado_em = ?, "
            "revisado_por = ?, motivo_recusa = NULL "
            "WHERE documento_checklist_id = ? AND empresa_id = ?",
            (STATUS_APROVADO, _agora_iso(), revisado_por, documento_checklist_id, empresa_id),
        )
        _registrar_historico(
            con, empresa_id, pendencia["caso_id"],
            descricao=f"Documento aprovado para o item: {pendencia['item']}",
            valor_anterior=pendencia["status"], valor_novo=STATUS_APROVADO,
            criado_por=revisado_por,
        )
        con.commit()
        return pendencia
    finally:
        con.close()


def recusar(
    empresa_id: str, documento_checklist_id: str, motivo: str,
    revisado_por: str = "Painel administrativo",
) -> dict:
    """Recusa o arquivo e devolve o item para "faltando", guardando o
    porquê. O motivo é obrigatório de propósito: recusa sem explicação
    faz o cliente reenviar o mesmo arquivo errado."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Explique o motivo da recusa -- ele é mostrado ao cliente.")

    con = conectar(empresa_id)
    try:
        pendencia = _carregar_pendencia(con, empresa_id, documento_checklist_id)
        if pendencia["status"] == STATUS_RECUSADO:
            raise ValueError("Este documento já foi recusado.")

        con.execute(
            "UPDATE documento_checklist SET status = ?, revisado_em = ?, "
            "revisado_por = ?, motivo_recusa = ? "
            "WHERE documento_checklist_id = ? AND empresa_id = ?",
            (STATUS_RECUSADO, _agora_iso(), revisado_por, motivo,
             documento_checklist_id, empresa_id),
        )
        _registrar_historico(
            con, empresa_id, pendencia["caso_id"],
            descricao=f"Documento recusado para o item: {pendencia['item']} -- {motivo}",
            valor_anterior=pendencia["status"], valor_novo=STATUS_RECUSADO,
            criado_por=revisado_por,
        )
        con.commit()
        return pendencia
    finally:
        con.close()


def listar_pendentes(empresa_id: str) -> list:
    """Fila de conferência do painel: tudo que cliente enviou e ninguém
    olhou ainda, de todos os clientes da empresa, mais antigo primeiro
    (quem esperou mais aparece antes)."""
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT dck.documento_checklist_id, dck.marcado_em, dck.marcado_por, "
            "       dck.documento_id, d.nome_arquivo, d.tipo_documento, "
            "       dex.item, dex.grupo, "
            "       p.processo_id, p.caso_id, s.nome_servico, "
            "       c.titulo AS caso_titulo, cl.cliente_id, cl.nome AS cliente_nome "
            "FROM documento_checklist dck "
            "JOIN documento d ON d.documento_id = dck.documento_id AND d.empresa_id = dck.empresa_id "
            "JOIN documento_exigido dex ON dex.documento_exigido_id = dck.documento_exigido_id "
            "     AND dex.empresa_id = dck.empresa_id "
            "JOIN processo p ON p.processo_id = dck.processo_id AND p.empresa_id = dck.empresa_id "
            "JOIN caso c ON c.caso_id = p.caso_id AND c.empresa_id = dck.empresa_id "
            "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = dck.empresa_id "
            # servico.service_id (e não servico_id) é herança da planilha
            # original -- processo.servico_id aponta pra ele.
            "LEFT JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = dck.empresa_id "
            "WHERE dck.empresa_id = ? AND dck.status = ? "
            "ORDER BY dck.marcado_em",
            (empresa_id, STATUS_AGUARDANDO),
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        con.close()


def desmarcar(empresa_id: str, documento_checklist_id: str) -> None:
    con = conectar(empresa_id)
    try:
        existe = con.execute(
            "SELECT 1 FROM documento_checklist WHERE documento_checklist_id = ? AND empresa_id = ?",
            (documento_checklist_id, empresa_id),
        ).fetchone()
        if not existe:
            raise ValueError(f"Marcação não encontrada: {documento_checklist_id}")
        con.execute(
            "DELETE FROM documento_checklist WHERE documento_checklist_id = ? AND empresa_id = ?",
            (documento_checklist_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    con = conectar(EMPRESA)
    try:
        processo = con.execute(
            "SELECT processo_id FROM processo WHERE empresa_id = ? LIMIT 1", (EMPRESA,)
        ).fetchone()
        if not processo:
            print("Nenhum processo cadastrado para testar.")
        else:
            status = status_checklist(con, EMPRESA, processo["processo_id"])
            print(f"Checklist de {processo['processo_id']}: {len(status)} itens.")
            for item in status:
                print(f"  [{item['estado']}] {item['item']}")
                if item["motivo_recusa"]:
                    print(f"       recusado antes: {item['motivo_recusa']}")
    finally:
        con.close()

    pendentes = listar_pendentes(EMPRESA)
    print(f"\nAguardando conferência da equipe: {len(pendentes)}")
    for p in pendentes:
        print(f"  {p['cliente_nome']} -- {p['item']} ({p['nome_arquivo']})")
