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


# ---------------------------------------------------------------------
# DOSSIÊ DO CLIENTE (2026-08-27)
#
# Documento que pertence à PESSOA, não a um atendimento: CR, CRAF,
# comprovante de residência, laudos. Vale por anos, atravessa vários
# casos e continua valendo quando todos fecharem -- por isso `caso_id` e
# `processo_id` ficam NULL, e o CHECK do banco recusa que tenham valor
# (ver core/db/migrar_dossie_cliente.py).
#
# `tipo_documento` continua TEXTO livre. A lista de tipos de CAC (CR,
# CRAF, guia de tráfego) é vocabulário de clube de tiro e vive no
# Domínio -- `domain/clube_tiro/documentos_cac.py` --, oferecida como
# sugestão na tela. O Core não sabe o que é um CRAF, e é assim que ele
# continua servindo a um domínio futuro que não tenha nenhum.
# ---------------------------------------------------------------------

CATEGORIA_CASO = "Caso"
CATEGORIA_DOSSIE = "Dossiê"
CATEGORIAS_VALIDAS = (CATEGORIA_CASO, CATEGORIA_DOSSIE)


def salvar_no_dossie(
    empresa_id: str,
    cliente_id: str,
    conteudo: bytes,
    nome_arquivo_original: str,
    tipo_documento: str,
    data_validade: Optional[str] = None,
    referencia: Optional[str] = None,
) -> str:
    """Guarda um documento permanente da pessoa.

    `referencia` é o "de qual arma" -- CRAF, guia de tráfego e nota
    fiscal existem mais de uma vez por pessoa, e sem isso três CRAFs no
    dossiê ficam indistinguíveis. Vai em `observacoes`, que já existia.

    ATENÇÃO ao que se guarda aí: número de série de arma é dado sensível
    (ver a regra do Redator em CLAUDE.md). Aqui ele é legítimo -- o
    dossiê é do dono, protegido por login, e nunca entra em prompt de IA;
    nenhum módulo do Motor IA lê esta tabela.
    """
    tipo_documento = (tipo_documento or "").strip()
    if not tipo_documento:
        raise ValueError("Informe o tipo do documento.")

    con = conectar(empresa_id)
    try:
        # O cliente tem que ser desta empresa ANTES de qualquer byte ir
        # para o disco -- mesma ordem de salvar_documento(), pelo mesmo
        # motivo: checar depois deixaria arquivo órfão na pasta errada.
        dono = con.execute(
            "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
            (cliente_id, empresa_id),
        ).fetchone()
        if not dono:
            raise ValueError(f"Cliente não encontrado nesta empresa: {cliente_id}")

        documento_id = _proximo_id(con)
        pasta_cliente = PASTA_DOCUMENTOS / empresa_id / cliente_id
        pasta_cliente.mkdir(parents=True, exist_ok=True)
        nome_salvo = f"{documento_id}_{_nome_seguro(nome_arquivo_original)}"
        caminho = pasta_cliente / nome_salvo
        caminho.write_bytes(conteudo)

        con.execute(
            "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
            "processo_id, tipo_documento, nome_arquivo, link_arquivo, status, "
            "data_envio, data_validade, observacoes, categoria) "
            "VALUES (?,?,?,NULL,NULL,?,?,?,?,?,?,?,?)",
            (documento_id, empresa_id, cliente_id, tipo_documento,
             nome_arquivo_original, str(caminho), STATUS_RECEBIDO, _agora_iso(),
             (data_validade or "").strip() or None,
             (referencia or "").strip() or None, CATEGORIA_DOSSIE),
        )
        con.commit()
        return documento_id
    finally:
        con.close()


def listar_dossie(empresa_id: str, cliente_id: str, hoje: Optional[str] = None) -> list:
    """O dossiê da pessoa, do mais recente para o mais antigo.

    Cada linha traz `situacao_validade`, que é o que a tela pinta:

        'vencido'  -- a data já passou
        'vencendo' -- vence dentro de DIAS_ALERTA_VALIDADE
        'valido'   -- ainda vale
        None       -- SEM data de validade cadastrada

    O `None` não é o mesmo que 'valido', e é a distinção de sempre neste
    projeto: documento sem data não é documento em dia, é documento cuja
    validade ninguém sabe. Pintar de verde seria afirmar o que não se
    consultou.
    """
    from datetime import date, timedelta

    from domain.clube_tiro.documentos_cac import DIAS_ALERTA_VALIDADE

    hoje = hoje or date.today().isoformat()
    limite = (date.fromisoformat(hoje) + timedelta(days=DIAS_ALERTA_VALIDADE)).isoformat()

    con = conectar(empresa_id)
    try:
        linhas = [
            dict(l) for l in con.execute(
                "SELECT * FROM documento WHERE empresa_id = ? AND cliente_id = ? "
                "AND categoria = ? ORDER BY data_envio DESC",
                (empresa_id, cliente_id, CATEGORIA_DOSSIE),
            ).fetchall()
        ]
    finally:
        con.close()

    for linha in linhas:
        validade = (linha.get("data_validade") or "")[:10]
        if not validade:
            linha["situacao_validade"] = None
        elif validade < hoje:
            linha["situacao_validade"] = "vencido"
        elif validade < limite:
            linha["situacao_validade"] = "vencendo"
        else:
            linha["situacao_validade"] = "valido"
    return linhas


def obter_documento(empresa_id: str, documento_id: str) -> Optional[dict]:
    """Um documento pelo id, já filtrado por empresa. Quem serve arquivo
    ainda precisa conferir o DONO -- este filtro não separa dois clientes
    da mesma empresa, que é justamente o caso perigoso do Portal."""
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT * FROM documento WHERE documento_id = ? AND empresa_id = ?",
            (documento_id, empresa_id),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()
