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
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.conexao import conectar

# Sobrescrevível por ERP_DOCUMENTOS_DIR -- mesmo padrão (e mesmo motivo) de
# ERP_CORE_DB em core/conexao.py. As demonstrações rodam com banco
# descartável, mas o arquivo em disco não seguia o banco: os PDFs
# inventados iam parar na MESMA pasta dos documentos de cliente de
# verdade (empresa_id e cliente_id se repetem entre os dois bancos),
# sobreviviam ao fim da demonstração e entravam no backup diário.
PASTA_DOCUMENTOS = Path(
    os.environ.get("ERP_DOCUMENTOS_DIR")
    or Path(__file__).resolve().parent.parent / "atendimento" / "documentos_recebidos"
)

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


def _registrar_historico(
    con, empresa_id: str, caso_id: str, descricao: str, criado_por: str,
) -> None:
    """Mesma regra do resto do Core: mudança de estado sempre deixa
    rastro (CLAUDE.md). `tipo_evento='outro'` pelo mesmo motivo de
    core/motor_checklist.py: a lista fechada do schema cobre eventos do
    Caso em si, e documento é evento dentro do caso, não status dele."""
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(historico_id, 5) AS INTEGER)) FROM historico"
    ).fetchone()[0] or 0
    con.execute(
        "INSERT INTO historico (historico_id, empresa_id, caso_id, tipo_evento, "
        "descricao, criado_em, criado_por) VALUES (?,?,?,'outro',?,?,?)",
        (f"HIS-{maior + 1:06d}", empresa_id, caso_id, descricao, _agora_iso(), criado_por),
    )


def excluir_de_caso(
    empresa_id: str, documento_id: str, excluido_por: str = "Painel administrativo",
) -> Optional[str]:
    """Apaga um documento de CASO -- linha, marcação de checklist (se
    houver) e arquivo em disco. Devolve o caso_id (para a camada de cima
    poder recarregar a ficha certa), ou None se o documento não tinha
    caso associado.

    Só documento de Caso sai por aqui -- dossiê tem sua própria rota
    (webapp/app.py::dossie_remover), de propósito: as consequências são
    diferentes (aqui existe checklist marcado e histórico de caso pra
    limpar; lá não existe nenhum dos dois).

    A ordem importa: `documento_checklist.documento_id` referencia esta
    linha SEM CASCADE (schema.sql), e o projeto roda com
    `PRAGMA foreign_keys = ON` -- apagar o documento antes da marcação
    seria rejeitado pela própria integridade referencial do banco. Apagar
    a marcação primeiro devolve o item pro estado "faltando", exatamente
    como já acontece quando um documento é recusado.
    """
    con = conectar(empresa_id)
    try:
        documento = con.execute(
            "SELECT caso_id, tipo_documento, link_arquivo, categoria FROM documento "
            "WHERE documento_id = ? AND empresa_id = ?",
            (documento_id, empresa_id),
        ).fetchone()
        if not documento:
            raise ValueError(f"Documento não encontrado: {documento_id}")
        documento = dict(documento)
        if documento["categoria"] == CATEGORIA_DOSSIE:
            raise ValueError("Documento do dossiê -- use a remoção do dossiê, não esta.")

        con.execute(
            "DELETE FROM documento_checklist WHERE documento_id = ? AND empresa_id = ?",
            (documento_id, empresa_id),
        )
        con.execute(
            "DELETE FROM documento WHERE documento_id = ? AND empresa_id = ?",
            (documento_id, empresa_id),
        )
        if documento["caso_id"]:
            _registrar_historico(
                con, empresa_id, documento["caso_id"],
                descricao=f"Documento excluído: {documento['tipo_documento']}",
                criado_por=excluido_por,
            )
        con.commit()
    finally:
        con.close()

    caminho = documento.get("link_arquivo")
    if caminho and os.path.exists(caminho):
        try:
            os.remove(caminho)
        except OSError:
            # Mesma escolha de dossie_remover: arquivo que não sai não
            # desfaz a exclusão do banco -- vira órfão, e
            # core.db.auditar_documentos denuncia depois.
            import traceback
            traceback.print_exc()

    return documento["caso_id"]


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
    finalidade: Optional[str] = None,
) -> str:
    """Guarda um documento permanente da pessoa.

    `referencia` é o "de qual arma" -- CRAF, guia de tráfego e nota
    fiscal existem mais de uma vez por pessoa, e sem isso três CRAFs no
    dossiê ficam indistinguíveis. Vai em `observacoes`, que já existia.

    `finalidade` é a que ACERVO essa arma pertence -- 'Tiro' / 'Caça' /
    'Coleção' (domain/clube_tiro/documentos_cac.FINALIDADES_ARMA). Texto
    livre aqui também: o Core não valida contra essa lista, que é
    vocabulário de CAC oferecido como SELECT na tela.

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
            "data_envio, data_validade, observacoes, categoria, finalidade) "
            "VALUES (?,?,?,NULL,NULL,?,?,?,?,?,?,?,?,?)",
            (documento_id, empresa_id, cliente_id, tipo_documento,
             nome_arquivo_original, str(caminho), STATUS_RECEBIDO, _agora_iso(),
             (data_validade or "").strip() or None,
             (referencia or "").strip() or None, CATEGORIA_DOSSIE,
             (finalidade or "").strip() or None),
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
