"""Conversa como envelope de atendimento -- o "fio" que liga as mensagens
trocadas com um cliente por um canal (E-mail, WhatsApp) numa unidade só.
É o que a tela de Atendimentos (CRM) do painel lê. Estado do Core, sem
IA, mesmo padrão de motor_sessoes/motor_casos/motor_mensagens.

A tabela `conversa` existe desde o Core mínimo (2026-07-22), desenhada a
partir da aba 07_Conversas da planilha -- mas até aqui só tinha linha
vinda de migração: nada no pipeline em uso a escrevia. Por isso cada
`mensagem` ficava solta, sem histórico navegável, e não havia como
montar uma tela de CRM. Este módulo fecha esse buraco.

DIFERENÇA PARA `sessao` (que parece a mesma coisa e não é): sessão é
contexto de curto prazo do Motor IA -- expira sozinha, existe para a IA
saber do que se estava falando agora. Conversa é registro de longo prazo
para uma PESSOA ler depois: nunca expira, agrupa por canal e sobrevive à
sessão. Um mesmo cliente pode ter várias sessões dentro de uma conversa.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

STATUS_ABERTA = "Aberta"
STATUS_AGUARDANDO_CLIENTE = "Aguardando cliente"
STATUS_ENCERRADA = "Encerrada"

STATUS_VALIDOS = (STATUS_ABERTA, STATUS_AGUARDANDO_CLIENTE, STATUS_ENCERRADA)

# Canais que o sistema sabe atender hoje. Lista controlada em código, não
# CHECK no schema -- mesmo padrão de motor_casos.STATUS_VALIDOS e
# motor_usuarios.PAPEIS_VALIDOS: acrescentar um canal novo (Instagram,
# Telegram) é mudança de código revisada, não linha digitada no banco.
CANAIS_VALIDOS = ("Email", "WhatsApp")

# Rótulo para tela. O valor gravado no banco continua sendo a chave --
# quem escreve "E-mail" com hífen no banco quebra o filtro por canal.
CANAIS_ROTULO = {"Email": "E-mail", "WhatsApp": "WhatsApp"}


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def localizar_ou_criar_conversa(
    empresa_id: str,
    cliente_id: str,
    canal: str,
    caso_id: Optional[str] = None,
    assunto: Optional[str] = None,
    origem: str = "Cliente",
    criado_por: str = "Motor IA",
    con=None,
) -> str:
    """A conversa aberta daquele cliente NAQUELE canal, ou uma nova.

    O canal entra na chave de propósito: e-mail e WhatsApp do mesmo
    cliente são dois fios de conversa distintos para quem atende (têm
    ritmo, tom e histórico próprios), mesmo sendo a mesma pessoa. Juntar
    os dois numa thread só produziria um histórico ilegível.

    `con` opcional segue o padrão de motor_checklist.status_checklist:
    quem já tem uma conexão aberta (o pipeline, que grava mensagem na
    mesma transação) passa a dele em vez de abrir uma segunda -- SQLite
    com dois escritores no mesmo processo é justamente o que o WAL +
    busy_timeout tenta evitar, não faz sentido provocar de graça.
    """
    if canal not in CANAIS_VALIDOS:
        raise ValueError(
            f"Canal inválido: {canal}. Válidos: {', '.join(CANAIS_VALIDOS)}."
        )

    proprio = con is None
    con = con or conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT conversa_id FROM conversa WHERE empresa_id = ? AND cliente_id = ? "
            "AND canal = ? AND status != ? AND ativo = 'Sim' "
            "ORDER BY ultima_mensagem_em DESC LIMIT 1",
            (empresa_id, cliente_id, canal, STATUS_ENCERRADA),
        ).fetchone()
        if linha:
            return linha["conversa_id"]

        agora = _agora_iso()
        conversa_id = _proximo_id(con, "conversa", "conversa_id", "CON")
        con.execute(
            "INSERT INTO conversa (conversa_id, empresa_id, cliente_id, caso_id, "
            "canal, origem, status, assunto_principal, iniciada_em, "
            "ultima_mensagem_em, total_mensagens, criado_por, atualizado_por) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                conversa_id, empresa_id, cliente_id, caso_id, canal, origem,
                STATUS_ABERTA, assunto, agora, agora, 0, criado_por, criado_por,
            ),
        )
        if proprio:
            con.commit()
        return conversa_id
    finally:
        if proprio:
            con.close()


def registrar_movimento(
    empresa_id: str,
    conversa_id: str,
    caso_id: Optional[str] = None,
    assunto: Optional[str] = None,
    precisa_humano: Optional[str] = None,
    atualizado_por: str = "Motor IA",
    con=None,
) -> None:
    """Carimba a conversa depois de uma mensagem nova: relógio da última
    mensagem, contador, e o caso/assunto quando ainda não tinha um.

    Nunca sobrescreve `caso_id`/`assunto_principal` já preenchidos: a
    primeira mensagem é que define do que a conversa trata; uma pergunta
    solta no meio não deve sequestrar o rótulo do fio inteiro.
    """
    proprio = con is None
    con = con or conectar(empresa_id)
    try:
        con.execute(
            "UPDATE conversa SET ultima_mensagem_em = ?, "
            "total_mensagens = total_mensagens + 1, "
            "caso_id = COALESCE(caso_id, ?), "
            "assunto_principal = COALESCE(assunto_principal, ?), "
            "precisa_humano = COALESCE(?, precisa_humano), "
            "atualizado_por = ?, versao = versao + 1 "
            "WHERE conversa_id = ? AND empresa_id = ?",
            (
                _agora_iso(), caso_id, assunto, precisa_humano,
                atualizado_por, conversa_id, empresa_id,
            ),
        )
        if proprio:
            con.commit()
    finally:
        if proprio:
            con.close()


def listar_conversas(
    empresa_id: str,
    canal: Optional[str] = None,
    status: Optional[str] = None,
    busca: Optional[str] = None,
    limite: int = 200,
) -> list[dict]:
    """A caixa de entrada do CRM: uma linha por conversa, mais recente
    primeiro, com um trecho da última mensagem para dar contexto sem
    precisar abrir.

    MULTI-TENANT: este arquivo lê tabela crua (as views do Core não
    cobrem `conversa`), então o filtro de empresa é escrito à mão em todo
    WHERE -- inclusive nos subselects, que sem isso trariam o trecho da
    mensagem de outra empresa para a linha certa.
    """
    con = conectar(empresa_id)
    try:
        sql = [
            "SELECT c.*, cl.nome AS cliente_nome, cl.email AS cliente_email, "
            "cl.telefone AS cliente_telefone, cl.cpf AS cliente_cpf, "
            "u.nome AS responsavel_nome, "
            "(SELECT COALESCE(m.mensagem, m.resposta_ia) FROM mensagem m "
            " WHERE m.conversa_id = c.conversa_id AND m.empresa_id = c.empresa_id "
            " ORDER BY m.data_hora DESC, m.mensagem_id DESC LIMIT 1) AS ultima_previa, "
            "(SELECT COUNT(*) FROM mensagem m "
            " WHERE m.conversa_id = c.conversa_id AND m.empresa_id = c.empresa_id "
            " AND m.status_processamento = 'Aguardando Revisão') AS pendentes "
            "FROM conversa c "
            "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = c.empresa_id "
            "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id AND u.empresa_id = c.empresa_id "
            "WHERE c.empresa_id = ? AND c.ativo = 'Sim'"
        ]
        params: list = [empresa_id]

        if canal:
            sql.append("AND c.canal = ?")
            params.append(canal)
        if status:
            sql.append("AND c.status = ?")
            params.append(status)
        if busca:
            sql.append(
                "AND (cl.nome LIKE ? OR cl.email LIKE ? OR cl.cpf LIKE ? "
                "OR c.assunto_principal LIKE ?)"
            )
            termo = f"%{busca}%"
            params.extend([termo, termo, termo, termo])

        sql.append("ORDER BY c.ultima_mensagem_em DESC LIMIT ?")
        params.append(limite)

        linhas = con.execute(" ".join(sql), params).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        con.close()


def obter_conversa(empresa_id: str, conversa_id: str) -> Optional[dict]:
    """A conversa com a thread inteira montada.

    Cada linha de `mensagem` vira ATÉ DUAS bolhas na tela: o que o
    cliente escreveu (`mensagem`) e o que saiu como resposta
    (`resposta_ia`) -- é assim que a tabela guarda desde sempre, um
    par pergunta/resposta por linha. Mensagem que o atendente começou
    (sem o cliente ter escrito nada) tem só a segunda metade.
    """
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT c.*, cl.nome AS cliente_nome, cl.email AS cliente_email, "
            "cl.telefone AS cliente_telefone, cl.cpf AS cliente_cpf, "
            "u.nome AS responsavel_nome "
            "FROM conversa c "
            "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = c.empresa_id "
            "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id AND u.empresa_id = c.empresa_id "
            "WHERE c.conversa_id = ? AND c.empresa_id = ?",
            (conversa_id, empresa_id),
        ).fetchone()
        if not linha:
            return None

        conversa = dict(linha)
        registros = con.execute(
            "SELECT m.*, u.nome AS responsavel_nome FROM mensagem m "
            "LEFT JOIN usuario u ON u.usuario_id = m.responsavel_id AND u.empresa_id = m.empresa_id "
            "WHERE m.conversa_id = ? AND m.empresa_id = ? "
            "ORDER BY m.data_hora, m.mensagem_id",
            (conversa_id, empresa_id),
        ).fetchall()

        thread: list[dict] = []
        for reg in registros:
            reg = dict(reg)
            if reg.get("mensagem"):
                thread.append({
                    "mensagem_id": reg["mensagem_id"],
                    "lado": "cliente",
                    "texto": reg["mensagem"],
                    "data_hora": reg["data_hora"],
                    "assunto": reg.get("assunto"),
                    "intent": reg.get("intent"),
                    "status": None,
                    "autor": conversa["cliente_nome"],
                })
            if reg.get("resposta_ia"):
                # Quem assina: o atendente que aprovou, quando houve
                # aprovação humana; senão foi a IA que respondeu sozinha.
                autor = reg.get("responsavel_nome") or (
                    "Atendimento" if reg.get("origem") == "Atendente" else "Assistente IA"
                )
                thread.append({
                    "mensagem_id": reg["mensagem_id"],
                    "lado": "empresa",
                    "texto": reg["resposta_ia"],
                    "data_hora": reg["data_hora"],
                    "assunto": None,
                    "intent": None,
                    "status": reg.get("status_processamento"),
                    "autor": autor,
                })

        conversa["thread"] = thread
        return conversa
    finally:
        con.close()


def registrar_saida(
    empresa_id: str,
    conversa_id: str,
    cliente_id: str,
    texto: str,
    canal: str,
    caso_id: Optional[str] = None,
    destino: Optional[str] = None,
    assunto: Optional[str] = None,
    responsavel_id: Optional[str] = None,
    status: str = "Enviado",
) -> str:
    """Grava uma mensagem que PARTIU da empresa (atendente escrevendo do
    painel), não uma resposta a algo que o cliente mandou.

    Fica na mesma tabela `mensagem`, com `origem='Atendente'` e o campo
    `mensagem` (o que o cliente escreveu) vazio -- é isso que distingue
    as duas coisas sem precisar de tabela nova.
    """
    con = conectar(empresa_id)
    try:
        mensagem_id = _proximo_id(con, "mensagem", "mensagem_id", "MSG")
        con.execute(
            "INSERT INTO mensagem (mensagem_id, empresa_id, cliente_id, caso_id, "
            "conversa_id, canal, data_hora, origem, email_remetente, assunto, "
            "mensagem, status_processamento, resposta_ia, responsavel_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mensagem_id, empresa_id, cliente_id, caso_id, conversa_id, canal,
                _agora_iso(), "Atendente", destino, assunto, None, status,
                texto, responsavel_id,
            ),
        )
        registrar_movimento(
            empresa_id, conversa_id, caso_id=caso_id,
            atualizado_por=responsavel_id or "Painel administrativo", con=con,
        )
        # A empresa respondeu: a bola está com o cliente agora. Sem isso a
        # caixa de entrada mostraria como "Aberta" (= precisa de ação
        # nossa) uma conversa que já foi respondida.
        con.execute(
            "UPDATE conversa SET status = ? WHERE conversa_id = ? AND empresa_id = ? "
            "AND status = ?",
            (STATUS_AGUARDANDO_CLIENTE, conversa_id, empresa_id, STATUS_ABERTA),
        )
        con.commit()
        return mensagem_id
    finally:
        con.close()


def atualizar_status(
    empresa_id: str, conversa_id: str, status: str,
    atualizado_por: str = "Painel administrativo",
) -> None:
    if status not in STATUS_VALIDOS:
        raise ValueError(
            f"Status inválido: {status}. Válidos: {', '.join(STATUS_VALIDOS)}."
        )
    con = conectar(empresa_id)
    try:
        con.execute(
            "UPDATE conversa SET status = ?, encerrada_em = ?, atualizado_por = ?, "
            "versao = versao + 1 WHERE conversa_id = ? AND empresa_id = ?",
            (
                status,
                _agora_iso() if status == STATUS_ENCERRADA else None,
                atualizado_por, conversa_id, empresa_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def atualizar_responsavel(
    empresa_id: str, conversa_id: str, responsavel_id: Optional[str],
    atualizado_por: str = "Painel administrativo",
) -> None:
    """Quem está cuidando desta conversa. `None` devolve para a fila
    geral. Valida que o usuário é da mesma empresa e está ativo -- mesmo
    cuidado de motor_casos.atualizar_responsavel."""
    con = conectar(empresa_id)
    try:
        if responsavel_id:
            existe = con.execute(
                "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ? AND ativo = 'Sim'",
                (responsavel_id, empresa_id),
            ).fetchone()
            if not existe:
                raise ValueError(f"Usuário inválido ou inativo: {responsavel_id}.")
        con.execute(
            "UPDATE conversa SET responsavel_id = ?, atualizado_por = ?, "
            "versao = versao + 1 WHERE conversa_id = ? AND empresa_id = ?",
            (responsavel_id, atualizado_por, conversa_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


def contar_por_canal(empresa_id: str) -> dict:
    """Contadores da caixa de entrada, por canal -- alimenta os badges do
    menu sem precisar carregar a lista inteira."""
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT canal, COUNT(*) AS total FROM conversa "
            "WHERE empresa_id = ? AND ativo = 'Sim' AND status = ? "
            "GROUP BY canal",
            (empresa_id, STATUS_ABERTA),
        ).fetchall()
        return {linha["canal"]: linha["total"] for linha in linhas}
    finally:
        con.close()


if __name__ == "__main__":
    # Teste de fumaça com dado real do banco, mesmo padrão dos outros
    # motores do Core -- não cria nada, só lê.
    from atendimento.config import EMPRESA_ID

    print(f"Empresa: {EMPRESA_ID}")
    print(f"Abertas por canal: {contar_por_canal(EMPRESA_ID)}")
    conversas = listar_conversas(EMPRESA_ID, limite=5)
    print(f"\n{len(conversas)} conversa(s) mais recentes:")
    for c in conversas:
        previa = (c["ultima_previa"] or "")[:60].replace("\n", " ")
        print(
            f"  {c['conversa_id']}  {CANAIS_ROTULO.get(c['canal'], c['canal']):9}  "
            f"{c['cliente_nome'][:20]:20}  {c['status']:18}  {previa}"
        )
    if conversas:
        detalhe = obter_conversa(EMPRESA_ID, conversas[0]["conversa_id"])
        print(f"\nThread de {detalhe['conversa_id']}: {len(detalhe['thread'])} bolha(s)")
        for bolha in detalhe["thread"][:6]:
            print(f"  [{bolha['lado']:7}] {bolha['autor'][:18]:18} {bolha['texto'][:50]}")
