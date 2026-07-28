"""Registro de documentos recebidos do cliente (fotos, PDFs -- CR, CRAF,
Aquisição, Transferência, Guia exigem esse tipo de comprovante). Hoje o
único canal que produz anexo é e-mail (ver integracoes/gmail.py +
atendimento/poller.py), mas este módulo não sabe de canal nenhum -- só
recebe bytes e metadados e grava.

Os arquivos ficam salvos em atendimento/documentos_recebidos/ (fora do
git -- documento de identidade e de arma é dado sensível, nunca deve
aparecer num commit). O banco só guarda caminho e metadados, nunca o
conteúdo do arquivo. Estado do Core, sem IA -- este módulo não decide
quais documentos são exigidos por processo, só registra o que chegou.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.conexao import conectar

PASTA_DOCUMENTOS = Path(__file__).resolve().parent.parent / "atendimento" / "documentos_recebidos"

STATUS_RECEBIDO = "Recebido"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(documento_id, 5) AS INTEGER)) FROM documento"
    ).fetchone()[0] or 0
    return f"DOC-{maior + 1:06d}"


def _nome_seguro(nome_original: str) -> str:
    # Nunca confiar no nome de um anexo de e-mail -- sanitiza pra impedir
    # path traversal (../../etc) e caractere que o filesystem não aceita.
    base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(nome_original).name)
    return base[:150] or "arquivo"


def salvar_documento(
    empresa_id: str,
    cliente_id: str,
    conteudo: bytes,
    nome_arquivo_original: str,
    caso_id: Optional[str] = None,
    processo_id: Optional[str] = None,
    tipo_documento: str = "Anexo recebido por e-mail",
    observacoes: Optional[str] = None,
    mensagem_id: Optional[str] = None,
) -> str:
    if not caso_id and not processo_id:
        raise ValueError("Documento precisa de caso_id ou processo_id (restrição do banco).")

    con = conectar(empresa_id)
    try:
        # O cliente tem que ser desta empresa antes de qualquer arquivo
        # ser gravado em disco -- checar depois de escrever deixaria
        # arquivo órfão na pasta de outra empresa.
        dono = con.execute(
            "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
            (cliente_id, empresa_id),
        ).fetchone()
        if not dono:
            raise ValueError(f"Cliente não encontrado nesta empresa: {cliente_id}")

        documento_id = _proximo_id(con)

        # Pasta por empresa e depois por cliente -- dado de empresas
        # diferentes nunca divide diretório no disco.
        pasta_cliente = PASTA_DOCUMENTOS / empresa_id / cliente_id
        pasta_cliente.mkdir(parents=True, exist_ok=True)
        nome_salvo = f"{documento_id}_{_nome_seguro(nome_arquivo_original)}"
        caminho = pasta_cliente / nome_salvo
        caminho.write_bytes(conteudo)

        con.execute(
            "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
            "processo_id, tipo_documento, nome_arquivo, link_arquivo, status, "
            "data_envio, observacoes, mensagem_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                documento_id, empresa_id, cliente_id, caso_id, processo_id,
                tipo_documento, nome_arquivo_original, str(caminho),
                STATUS_RECEBIDO, _agora_iso(), observacoes, mensagem_id,
            ),
        )
        con.commit()
        return documento_id
    finally:
        con.close()


def listar_por_mensagem(empresa_id: str, mensagem_id: str) -> list:
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT * FROM documento WHERE mensagem_id = ? AND empresa_id = ? "
            "ORDER BY data_envio",
            (mensagem_id, empresa_id),
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        con.close()
