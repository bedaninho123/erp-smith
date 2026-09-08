"""Isolamento de dado entre clientes do Portal.

Este é o teste mais importante do projeto. O Portal é a primeira
superfície pública do sistema, num domínio regulado (documentação de
arma de fogo): um furo aqui entrega documento de identidade de um
cliente para outro. docs/portal_cliente_arquitetura.md (seção 3) trata
isso como o único ponto realmente crítico da peça.

Todo teste aqui roda logado como a Ana (CLI-000001) tentando alcançar
dado do Bruno (CLI-000002). Os testes de controle positivo, no fim, são
tão necessários quanto os negativos: sem eles, um Portal quebrado que
negasse tudo passaria com nota máxima.
"""
from io import BytesIO

from core.conexao import conectar_admin

from tests.conftest import EMPRESA_A


def _contar_documentos(caso_id: str) -> int:
    # conectar_admin de propósito: a contagem tem que enxergar o banco
    # inteiro, senão um documento gravado na empresa errada passaria
    # despercebido justamente pelo teste que deveria pegá-lo.
    con = conectar_admin()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM documento WHERE caso_id = ?", (caso_id,)
        ).fetchone()[0]
    finally:
        con.close()


# --------------------------------------------------------------------
# Negativos -- o que NÃO pode acontecer de jeito nenhum
# --------------------------------------------------------------------

def test_nao_abre_caso_de_outro_cliente(banco, portal):
    resposta = portal.get("/portal/casos/CAS-000002")

    # Redireciona pra lista em vez de mostrar o caso -- e nunca revela
    # que o caso existe (mesma resposta de um ID inexistente).
    assert resposta.status_code == 302
    assert "/portal/casos" in resposta.headers["Location"]


def test_caso_de_outro_cliente_responde_igual_a_um_inexistente(banco, portal):
    """Se o caso alheio respondesse diferente de um ID inventado, daria
    pra descobrir quais casos existem só variando o número da URL."""
    alheio = portal.get("/portal/casos/CAS-000002")
    inexistente = portal.get("/portal/casos/CAS-999999")

    assert alheio.status_code == inexistente.status_code
    assert alheio.headers["Location"] == inexistente.headers["Location"]


def test_nao_baixa_documento_de_outro_cliente(banco, portal):
    resposta = portal.get("/portal/documentos/DOC-000002/arquivo")

    assert resposta.status_code == 404
    # O conteúdo do arquivo do Bruno não pode vazar nem por engano.
    assert b"conteudo secreto do cliente B" not in resposta.data


def test_nao_anexa_documento_no_caso_de_outro_cliente(banco, portal):
    antes = _contar_documentos("CAS-000002")

    portal.post(
        "/portal/documentos",
        data={
            "caso_id": "CAS-000002",
            "tipo_documento": "RG",
            "arquivo": (BytesIO(b"%PDF-1.4 invasao"), "invasao.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert _contar_documentos("CAS-000002") == antes, (
        "Documento foi gravado no caso de outro cliente."
    )


def test_lista_de_casos_nao_mostra_caso_alheio(banco, portal):
    corpo = portal.get("/portal/casos").get_data(as_text=True)

    assert "Caso da Ana" in corpo
    assert "Caso do Bruno" not in corpo


def test_rota_do_portal_exige_login(banco):
    from portal.app import app

    app.config.update(TESTING=True)
    anonimo = app.test_client()

    resposta = anonimo.get("/portal/casos/CAS-000001")

    assert resposta.status_code == 302
    # Manda pro login (rota "/portal/login"), nunca pro conteúdo do caso.
    assert resposta.headers["Location"] == "/portal/login"
    assert "Caso da Ana" not in resposta.get_data(as_text=True)


# --------------------------------------------------------------------
# Controles positivos -- provam que o Portal ainda funciona de verdade
# --------------------------------------------------------------------

def test_abre_o_proprio_caso(banco, portal):
    resposta = portal.get("/portal/casos/CAS-000001")

    assert resposta.status_code == 200
    assert "Caso da Ana" in resposta.get_data(as_text=True)


def test_baixa_o_proprio_documento(banco, portal):
    resposta = portal.get("/portal/documentos/DOC-000001/arquivo")

    assert resposta.status_code == 200
    assert b"conteudo secreto do cliente A" in resposta.data


def test_anexa_documento_no_proprio_caso(banco, portal):
    # A pasta de anexos já está isolada no tmp pelo conftest (fixture
    # autouse _pasta_de_documentos_isolada).
    antes = _contar_documentos("CAS-000001")

    portal.post(
        "/portal/documentos",
        data={
            "caso_id": "CAS-000001",
            "tipo_documento": "Comprovante de residência",
            "arquivo": (BytesIO(b"%PDF-1.4 documento legitimo"), "conta_de_luz.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert _contar_documentos("CAS-000001") == antes + 1


# --------------------------------------------------------------------
# Isolamento entre EMPRESAS -- problema diferente do de cima
#
# Os testes acima provam que a Ana não alcança o Bruno, que é cliente do
# MESMO despachante. Estes provam que ela não alcança a Carla, que é
# cliente de OUTRO. Um código que filtre só por cliente_id passa nos
# primeiros e falha nestes -- e é exatamente esse o buraco que a
# migração multi-tenant tinha que fechar.
# --------------------------------------------------------------------

def test_nao_abre_caso_de_outra_empresa(banco, portal):
    resposta = portal.get("/portal/casos/CAS-000003")

    assert resposta.status_code == 302
    assert "/portal/casos" in resposta.headers["Location"]


def test_caso_de_outra_empresa_responde_igual_a_um_inexistente(banco, portal):
    alheio = portal.get("/portal/casos/CAS-000003")
    inexistente = portal.get("/portal/casos/CAS-999999")

    assert alheio.status_code == inexistente.status_code
    assert alheio.headers["Location"] == inexistente.headers["Location"]


def test_nao_baixa_documento_de_outra_empresa(banco, portal):
    resposta = portal.get("/portal/documentos/DOC-000003/arquivo")

    assert resposta.status_code == 404
    assert b"conteudo secreto da empresa B" not in resposta.data


def test_nao_anexa_documento_em_caso_de_outra_empresa(banco, portal):
    antes = _contar_documentos("CAS-000003")

    portal.post(
        "/portal/documentos",
        data={
            "caso_id": "CAS-000003",
            "tipo_documento": "RG",
            "arquivo": (BytesIO(b"%PDF-1.4 invasao entre empresas"), "invasao.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert _contar_documentos("CAS-000003") == antes, (
        "Documento foi gravado num caso de outra empresa."
    )


def test_lista_de_casos_nao_mostra_caso_de_outra_empresa(banco, portal):
    corpo = portal.get("/portal/casos").get_data(as_text=True)

    assert "Caso da Ana" in corpo
    assert "Caso da Carla" not in corpo


def test_sessao_sem_empresa_nao_entra(banco):
    """Sessão criada antes do multi-tenant tem cliente_id mas não tem
    empresa_id. Ela precisa cair no login, não entrar como se nada
    tivesse mudado -- e muito menos estourar um KeyError dentro da rota."""
    from portal.app import app

    app.config.update(TESTING=True)
    antigo = app.test_client()
    with antigo.session_transaction() as sessao:
        sessao["cliente_id"] = "CLI-000001"
        sessao["cliente_nome"] = "Ana Teste"

    resposta = antigo.get("/portal/casos/CAS-000001")

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/portal/login"
    assert "Caso da Ana" not in resposta.get_data(as_text=True)
