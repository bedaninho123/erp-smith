"""Isolamento de dado entre empresas no painel administrativo.

O Portal já tinha suíte própria porque é a superfície pública. O painel
não é público, mas com multi-tenant ele passa a ser multi-inquilino: um
funcionário legítimo da empresa A, logado normalmente, não pode alcançar
dado da empresa B trocando um ID na URL.

Aqui o painel é mais perigoso que o Portal num ponto específico: ele
consulta tabela crua o tempo todo (as views do Core não cobrem nada
disso), então cada filtro é escrito à mão -- e o que não tem teste é
exatamente o que fica de fora numa refatoração futura.

Todo teste roda logado na EMPRESA_A tentando alcançar dado da
EMPRESA_B (Carla, CLI-000003 / CAS-000003 / DOC-000003).
"""
from tests.conftest import EMPRESA_A


# --------------------------------------------------------------------
# Negativos
# --------------------------------------------------------------------

def test_lista_de_casos_so_mostra_a_propria_empresa(banco, painel):
    dados = painel.get("/api/casos").get_json()

    ids = [c["caso_id"] for c in dados["casos"]]
    assert "CAS-000001" in ids
    assert "CAS-000002" in ids
    assert "CAS-000003" not in ids


def test_nao_abre_caso_de_outra_empresa(banco, painel):
    resposta = painel.get("/api/casos/CAS-000003")

    assert resposta.status_code == 404
    assert "Caso da Carla" not in resposta.get_data(as_text=True)


def test_caso_de_outra_empresa_responde_igual_a_um_inexistente(banco, painel):
    alheio = painel.get("/api/casos/CAS-000003")
    inexistente = painel.get("/api/casos/CAS-999999")

    assert alheio.status_code == inexistente.status_code == 404


def test_nao_baixa_documento_de_outra_empresa(banco, painel):
    resposta = painel.get("/api/documentos/DOC-000003/arquivo")

    assert resposta.status_code == 404
    assert b"conteudo secreto da empresa B" not in resposta.data


def test_busca_por_cpf_nao_atravessa_a_empresa(banco, painel):
    """Ana e Carla têm o mesmo CPF. Esta rota alimenta o formulário de
    resultados de campeonato: devolver o cliente_id da empresa errada
    gravaria a pessoa errada no resultado -- sem erro nenhum aparecer."""
    dados = painel.get("/api/clientes/buscar-cpf/11111111111").get_json()

    assert dados["cliente_id"] == "CLI-000001"


def test_lista_de_clientes_nao_mostra_cliente_de_outra_empresa(banco, painel):
    corpo = painel.get("/api/clientes/lista").get_data(as_text=True)

    assert "Ana Teste" in corpo
    assert "Carla Outra" not in corpo


def test_busca_de_cliente_nao_vaza_pelo_filtro_de_texto(banco, painel):
    """A busca por texto monta um OR de três colunas. Sem parênteses em
    volta desse OR, ele passaria por cima do filtro de empresa -- é um
    erro fácil de cometer e invisível a olho nu."""
    corpo = painel.get("/api/clientes/lista?busca=Carla").get_data(as_text=True)

    assert "Carla Outra" not in corpo


def test_nao_altera_status_de_caso_de_outra_empresa(banco, painel):
    resposta = painel.post("/api/casos/CAS-000003/status", json={"status": "Encerrado"})

    assert resposta.status_code == 400

    # E o caso da outra empresa continua como estava.
    from core.conexao import conectar_admin
    con = conectar_admin()
    status = con.execute(
        "SELECT status FROM caso WHERE caso_id = ?", ("CAS-000003",)
    ).fetchone()[0]
    con.close()
    assert status == "Aberto"


def test_sessao_sem_empresa_nao_entra(banco):
    """Sessão criada antes do multi-tenant tem usuario_id mas não tem
    empresa_id -- precisa ser recusada, não atendida pela metade."""
    from webapp.app import app

    app.config.update(TESTING=True)
    antigo = app.test_client()
    with antigo.session_transaction() as sessao:
        sessao["usuario_id"] = "USR-000001"
        sessao["usuario_nome"] = "Atendente Teste"

    assert antigo.get("/api/casos").status_code == 401


# --------------------------------------------------------------------
# Controles positivos -- um painel que negasse tudo passaria acima
# --------------------------------------------------------------------

def test_abre_o_caso_da_propria_empresa(banco, painel):
    resposta = painel.get("/api/casos/CAS-000001")

    assert resposta.status_code == 200
    assert resposta.get_json()["caso"]["titulo"] == "Caso da Ana"


def test_baixa_documento_da_propria_empresa(banco, painel):
    resposta = painel.get("/api/documentos/DOC-000001/arquivo")

    assert resposta.status_code == 200
    assert b"conteudo secreto do cliente A" in resposta.data


def test_altera_status_de_caso_da_propria_empresa(banco, painel):
    resposta = painel.post("/api/casos/CAS-000001/status", json={"status": "Encerrado"})

    assert resposta.status_code == 200

    from core.conexao import conectar
    con = conectar(EMPRESA_A)
    status = con.execute(
        "SELECT status FROM caso WHERE caso_id = ?", ("CAS-000001",)
    ).fetchone()[0]
    con.close()
    assert status == "Encerrado"
