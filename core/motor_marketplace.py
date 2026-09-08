"""Marketplace de classificados entre os clientes de uma empresa --
mural onde cada um anuncia o que quer vender (arma, equipamento, luneta,
acessório, no domínio de clube de tiro) e outro entra em contato direto
com quem anunciou. Estado do Core, sem IA -- este módulo não decide o
que é um anúncio válido além do que já está aqui, só registra.

Genérico de propósito (Core, não Domínio): "mural visível só para quem
participa de uma comunidade/afiliação dentro da empresa" não é exclusivo
de clube de tiro -- quem decide QUEM participa (aqui, "filiado ativo do
clube") é a camada de cima (portal/app.py + domain/clube_tiro), este
módulo só sabe empresa_id e cliente_id.

`categoria` é TEXTO LIVRE, mesmo padrão de documento.tipo_documento: o
Core não sabe o que é "Luneta/Mira" -- a lista de sugestão vive no
Domínio (domain/clube_tiro/categorias_marketplace.py). Isso inclui não
ter uma lista de categorias PROIBIDAS aqui (ex. munição) -- o freio
contra isso é o mesmo freio que protege qualquer anúncio impróprio: todo
anúncio nasce Pendente e só fica visível depois que um Gestor/Atendente
aprova (ver STATUS_VALIDOS).

SEM tabela de pedido/pagamento e SEM "comprador": é mural de
classificados, decisão do usuário (2026-09-02) -- combinar preço e
entrega acontece fora do sistema. O contato (telefone/e-mail) vai direto
no anúncio, visível a quem navega -- também decisão do usuário, que
considera a base de filiados confiável o bastante pra dispensar um
intermediário de contato.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.conexao import conectar

# Mesmo padrão (e mesmo motivo) de core/motor_documentos.PASTA_DOCUMENTOS
# -- sobrescrevível por env var pra demonstração não gravar foto de
# anúncio fictício na pasta de produção.
PASTA_ANUNCIOS = Path(
    os.environ.get("ERP_ANUNCIOS_DIR")
    or Path(__file__).resolve().parent.parent / "atendimento" / "marketplace_fotos"
)

# Fila de moderação -- mesmo padrão do status do Caso e do documento de
# checklist: lista controlada em código, não CHECK no schema.
STATUS_PENDENTE = "Pendente"
STATUS_APROVADO = "Aprovado"
STATUS_RECUSADO = "Recusado"
STATUS_VENDIDO = "Vendido"
STATUS_REMOVIDO = "Removido"
STATUS_VALIDOS = (STATUS_PENDENTE, STATUS_APROVADO, STATUS_RECUSADO, STATUS_VENDIDO, STATUS_REMOVIDO)

FOTO_EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
FOTO_TAMANHO_MAXIMO = 15 * 1024 * 1024  # 15 MB, mesmo limite do resto do projeto


class AnuncioInvalido(ValueError):
    pass


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(anuncio_id, 5) AS INTEGER)) FROM anuncio"
    ).fetchone()[0] or 0
    return f"ANC-{maior + 1:06d}"


def _nome_seguro(nome_original: str) -> str:
    # Mesma sanitização de motor_documentos.py -- nunca confiar no nome
    # de um arquivo enviado por upload (path traversal, caractere que o
    # filesystem não aceita).
    base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(nome_original).name)
    return base[:150] or "arquivo"


def _salvar_fotos(empresa_id: str, anuncio_id: str, fotos: list[tuple[bytes, str]]) -> str:
    """Grava as fotos em disco e devolve os caminhos, um por linha (lista
    simples -- não há por que estruturar isso como JSON, é só uma lista
    de arquivos)."""
    pasta = PASTA_ANUNCIOS / empresa_id / anuncio_id
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = []
    for indice, (conteudo, nome_original) in enumerate(fotos, start=1):
        nome_salvo = f"{indice:02d}_{_nome_seguro(nome_original)}"
        caminho = pasta / nome_salvo
        caminho.write_bytes(conteudo)
        caminhos.append(str(caminho))
    return "\n".join(caminhos)


def criar_anuncio(
    empresa_id: str,
    cliente_id: str,
    categoria: str,
    titulo: str,
    descricao: Optional[str] = None,
    valor: Optional[float] = None,
    contato_telefone: Optional[str] = None,
    contato_email: Optional[str] = None,
    fotos: Optional[list[tuple[bytes, str]]] = None,
) -> str:
    """Cria um anúncio, sempre nascendo Pendente -- só um Gestor/
    Atendente aprovando pelo painel é que o torna visível na vitrine."""
    categoria = (categoria or "").strip()
    titulo = (titulo or "").strip()
    if not categoria:
        raise AnuncioInvalido("Informe a categoria do anúncio.")
    if not titulo:
        raise AnuncioInvalido("Informe o título do anúncio.")
    if not (contato_telefone or "").strip() and not (contato_email or "").strip():
        raise AnuncioInvalido("Informe pelo menos um contato (telefone ou e-mail).")

    con = conectar(empresa_id)
    try:
        dono = con.execute(
            "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
            (cliente_id, empresa_id),
        ).fetchone()
        if not dono:
            raise AnuncioInvalido(f"Cliente não encontrado nesta empresa: {cliente_id}")

        anuncio_id = _proximo_id(con)
        caminhos_fotos = _salvar_fotos(empresa_id, anuncio_id, fotos) if fotos else None
        agora = _agora_iso()
        con.execute(
            "INSERT INTO anuncio (anuncio_id, empresa_id, cliente_id, categoria, titulo, "
            "descricao, valor, contato_telefone, contato_email, fotos, status, "
            "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (anuncio_id, empresa_id, cliente_id, categoria, titulo,
             (descricao or "").strip() or None, valor,
             (contato_telefone or "").strip() or None,
             (contato_email or "").strip() or None,
             caminhos_fotos, STATUS_PENDENTE, agora, agora),
        )
        con.commit()
        return anuncio_id
    finally:
        con.close()


def _linha_para_dict(linha) -> dict:
    item = dict(linha)
    item["fotos"] = item["fotos"].split("\n") if item.get("fotos") else []
    return item


def listar_anuncios(
    empresa_id: str, status: Optional[str] = None, cliente_id: Optional[str] = None,
) -> list[dict]:
    """A vitrine chama com status='Aprovado' (o que qualquer filiado pode
    ver); "meus anúncios" chama com cliente_id (o dono vê os próprios em
    qualquer status); o painel chama sem filtro nenhum ou só com status,
    pra moderar."""
    con = conectar(empresa_id)
    try:
        sql = "SELECT * FROM anuncio WHERE empresa_id = ?"
        parametros: list = [empresa_id]
        if status:
            sql += " AND status = ?"
            parametros.append(status)
        if cliente_id:
            sql += " AND cliente_id = ?"
            parametros.append(cliente_id)
        sql += " ORDER BY criado_em DESC"
        linhas = con.execute(sql, parametros).fetchall()
        return [_linha_para_dict(l) for l in linhas]
    finally:
        con.close()


def obter_anuncio(empresa_id: str, anuncio_id: str) -> Optional[dict]:
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT * FROM anuncio WHERE anuncio_id = ? AND empresa_id = ?",
            (anuncio_id, empresa_id),
        ).fetchone()
        return _linha_para_dict(linha) if linha else None
    finally:
        con.close()


def _mudar_status(
    empresa_id: str, anuncio_id: str, novo_status: str,
    revisado_por: Optional[str] = None, motivo_recusa: Optional[str] = None,
) -> None:
    if novo_status not in STATUS_VALIDOS:
        raise AnuncioInvalido(f"Status inválido: {novo_status}")
    con = conectar(empresa_id)
    try:
        existe = con.execute(
            "SELECT 1 FROM anuncio WHERE anuncio_id = ? AND empresa_id = ?",
            (anuncio_id, empresa_id),
        ).fetchone()
        if not existe:
            raise AnuncioInvalido(f"Anúncio não encontrado: {anuncio_id}")
        con.execute(
            "UPDATE anuncio SET status = ?, motivo_recusa = ?, revisado_por = ?, "
            "revisado_em = ?, atualizado_em = ? WHERE anuncio_id = ? AND empresa_id = ?",
            (novo_status, motivo_recusa, revisado_por, _agora_iso(), _agora_iso(),
             anuncio_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


def aprovar(empresa_id: str, anuncio_id: str, revisado_por: str) -> None:
    _mudar_status(empresa_id, anuncio_id, STATUS_APROVADO, revisado_por=revisado_por)


def recusar(empresa_id: str, anuncio_id: str, motivo: str, revisado_por: str) -> None:
    motivo = (motivo or "").strip()
    if not motivo:
        raise AnuncioInvalido("Informe o motivo da recusa.")
    _mudar_status(empresa_id, anuncio_id, STATUS_RECUSADO, revisado_por=revisado_por, motivo_recusa=motivo)


def marcar_vendido(empresa_id: str, anuncio_id: str) -> None:
    _mudar_status(empresa_id, anuncio_id, STATUS_VENDIDO)


def remover(empresa_id: str, anuncio_id: str) -> None:
    """Marca como Removido -- não apaga a linha nem o arquivo de foto,
    mesmo espírito de outras remoções "lógicas" do projeto (ex.
    modalidade que sai do catálogo vira ativo='Não'): um anúncio some da
    vitrine, mas o histórico de quem publicou o quê continua rastreável
    pro painel."""
    _mudar_status(empresa_id, anuncio_id, STATUS_REMOVIDO)


def editar_anuncio(
    empresa_id: str,
    anuncio_id: str,
    categoria: str,
    titulo: str,
    descricao: Optional[str] = None,
    valor: Optional[float] = None,
    contato_telefone: Optional[str] = None,
    contato_email: Optional[str] = None,
) -> None:
    """Correção de texto/preço/contato feita pelo painel (2026-09-02) --
    ex.: título com erro de digitação, preço errado. Não mexe em
    `status`: uma edição de texto não é uma decisão de moderação nova,
    então um anúncio já Aprovado continua Aprovado depois de editado
    (não some da vitrine nem exige aprovar de novo). Fotos ficam de fora
    por enquanto -- trocar imagem é operação à parte."""
    categoria = (categoria or "").strip()
    titulo = (titulo or "").strip()
    if not categoria:
        raise AnuncioInvalido("Informe a categoria do anúncio.")
    if not titulo:
        raise AnuncioInvalido("Informe o título do anúncio.")
    if not (contato_telefone or "").strip() and not (contato_email or "").strip():
        raise AnuncioInvalido("Informe pelo menos um contato (telefone ou e-mail).")

    con = conectar(empresa_id)
    try:
        existe = con.execute(
            "SELECT 1 FROM anuncio WHERE anuncio_id = ? AND empresa_id = ?",
            (anuncio_id, empresa_id),
        ).fetchone()
        if not existe:
            raise AnuncioInvalido(f"Anúncio não encontrado: {anuncio_id}")
        con.execute(
            "UPDATE anuncio SET categoria = ?, titulo = ?, descricao = ?, valor = ?, "
            "contato_telefone = ?, contato_email = ?, atualizado_em = ? "
            "WHERE anuncio_id = ? AND empresa_id = ?",
            (categoria, titulo, (descricao or "").strip() or None, valor,
             (contato_telefone or "").strip() or None,
             (contato_email or "").strip() or None,
             _agora_iso(), anuncio_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()
