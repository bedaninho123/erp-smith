"""Registro de mensagens processadas pelo Atendimento -- histórico real de
cada interação (mensagem recebida + resposta da IA) e o estado de revisão
humana quando o modo de revisão está ativo (configuracoes.revisao_humana_
ativa). Estado do Core -- sem IA, mesmo padrão de motor_sessoes/motor_casos.

A tabela `mensagem` já existia no schema (desenhada desde o Core mínimo)
mas nunca foi escrita pelo pipeline em uso -- só tinha dado de migração de
teste. Este módulo é quem passa a alimentá-la de verdade.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

STATUS_ENVIADO = "Enviado"
STATUS_AGUARDANDO_REVISAO = "Aguardando Revisão"
STATUS_REJEITADO = "Rejeitado"
STATUS_ENCAMINHADO = "Encaminhado"
STATUS_ERRO = "Erro"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def registrar_mensagem(
    cliente_id: Optional[str],
    texto_recebido: str,
    resposta_ia: Optional[str],
    status_processamento: str,
    canal: str = "Email",
    caso_id: Optional[str] = None,
    email_remetente: Optional[str] = None,
    assunto: Optional[str] = None,
    intent: Optional[str] = None,
    precisa_humano: Optional[str] = None,
    modelo_ia: Optional[str] = None,
    observacoes_ia: Optional[str] = None,
) -> Optional[str]:
    # mensagem.cliente_id é NOT NULL -- remetente não identificado (ex.
    # pergunta genérica de quem não é cliente cadastrado) não gera
    # registro aqui, mesma limitação que sessão/caso/memória já têm.
    if not cliente_id:
        return None

    con = conectar()
    try:
        mensagem_id = _proximo_id(con, "mensagem", "mensagem_id", "MSG")
        con.execute(
            "INSERT INTO mensagem VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mensagem_id, cliente_id, caso_id, None, None, canal, _agora_iso(),
                "Cliente", email_remetente, assunto, texto_recebido, intent, None,
                precisa_humano, status_processamento, None, resposta_ia, None, None,
                modelo_ia, observacoes_ia,
            ),
        )
        con.commit()
        return mensagem_id
    finally:
        con.close()


def listar_pendentes() -> list:
    con = conectar()
    try:
        linhas = con.execute(
            "SELECT m.*, c.nome AS cliente_nome, c.email AS cliente_email "
            "FROM mensagem m JOIN cliente c ON c.cliente_id = m.cliente_id "
            "WHERE m.status_processamento = ? ORDER BY m.data_hora",
            (STATUS_AGUARDANDO_REVISAO,),
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        con.close()


def obter_mensagem(mensagem_id: str) -> Optional[dict]:
    con = conectar()
    try:
        linha = con.execute(
            "SELECT m.*, c.nome AS cliente_nome, c.email AS cliente_email "
            "FROM mensagem m JOIN cliente c ON c.cliente_id = m.cliente_id "
            "WHERE m.mensagem_id = ?",
            (mensagem_id,),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def marcar_status(
    mensagem_id: str, status: str, resposta_final: Optional[str] = None,
    responsavel_id: Optional[str] = None,
) -> None:
    con = conectar()
    try:
        if resposta_final is not None:
            con.execute(
                "UPDATE mensagem SET status_processamento = ?, resposta_ia = ?, "
                "responsavel_id = ? WHERE mensagem_id = ?",
                (status, resposta_final, responsavel_id, mensagem_id),
            )
        else:
            con.execute(
                "UPDATE mensagem SET status_processamento = ?, responsavel_id = ? "
                "WHERE mensagem_id = ?",
                (status, responsavel_id, mensagem_id),
            )
        con.commit()
    finally:
        con.close()
