"""Documento pronto do processo: o despachante entrega, o cliente baixa.

Pedido de 2026-10-20: ao terminar a renovação do CRAF (ou qualquer
serviço), subir o documento que o cliente pagou para receber, marcar o
processo como concluído, e o cliente ver os dois juntos no Portal.

O que importa aqui é o segundo grupo: o arquivo é o resultado de um
serviço regulado de arma de fogo, e o único jeito de dar errado de
verdade é ele aparecer para a pessoa errada.
"""
import io

from core.conexao import conectar
from core.db import migrar_documento_final

from tests.conftest import EMPRESA_A, EMPRESA_B


def _concluir(painel, processo_id, nome="craf-novo.pdf", tipo="CRAF — Certificado de Registro de Arma de Fogo"):
    return painel.post(
        f"/api/processos/{processo_id}/concluir",
        data={
            "tipo_documento": tipo,
            "data_validade": "2036-10-20",
            "referencia": "Pistola Taurus G2C",
            "finalidade": "Tiro",
            "arquivo": (io.BytesIO(b"%PDF-1.4 craf renovado"), nome),
        },
        content_type="multipart/form-data",
    )


def _processo(processo_id, empresa_id=EMPRESA_A):
    con = conectar(empresa_id)
    try:
        return dict(con.execute(
            "SELECT * FROM processo WHERE processo_id = ?", (processo_id,)
        ).fetchone())
    finally:
        con.close()


# --------------------------------------------------------------------
# 1. O fluxo
# --------------------------------------------------------------------

def test_concluir_entrega_o_documento_no_dossie_e_conclui(painel):
    resposta = _concluir(painel, "PRO-000001")

    assert resposta.status_code == 200
    documento_id = resposta.get_json()["documento_id"]
    processo = _processo("PRO-000001")
    assert processo["status"] == "Concluído"
    assert processo["documento_final_id"] == documento_id

    con = conectar(EMPRESA_A)
    try:
        doc = dict(con.execute("SELECT * FROM documento WHERE documento_id = ?", (documento_id,)).fetchone())
    finally:
        con.close()
    # Do dono do processo, e permanente: aparece em "Minha conta" também.
    assert doc["cliente_id"] == "CLI-000001"
    assert doc["categoria"] == "Dossiê"
    assert doc["data_validade"].startswith("2036-10-20")


def test_cliente_ve_concluido_com_o_documento_e_consegue_baixar(painel, portal):
    documento_id = _concluir(painel, "PRO-000001").get_json()["documento_id"]

    pagina = portal.get("/portal/casos/CAS-000001").get_data(as_text=True)
    assert "Concluído" in pagina
    assert "Seu documento está pronto" in pagina
    assert f"/portal/documentos/{documento_id}/arquivo" in pagina

    arquivo = portal.get(f"/portal/documentos/{documento_id}/arquivo")
    assert arquivo.status_code == 200
    assert arquivo.data == b"%PDF-1.4 craf renovado"
    # E está em "Minha conta", junto do resto do dossiê.
    assert "CRAF" in portal.get("/portal/minha-conta").get_data(as_text=True)


def test_processo_concluido_nao_pede_mais_documento_ao_cliente(painel, portal):
    """Achado conferindo na demonstração: o CRAF pronto aparecia e, logo
    abaixo, o checklist inteiro como "faltando" -- e a tela inicial
    contava esses itens como pendência de quem já tinha recebido tudo."""
    con = conectar(EMPRESA_A)
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
        "grupo, item, ordem, ativo) VALUES ('DEX-000001', ?, 'SER-000001', 'Pessoais', "
        "'Documento de identificação', 1, 'Sim')",
        (EMPRESA_A,),
    )
    con.commit()
    con.close()
    assert "faltando" in portal.get("/portal/casos/CAS-000001").get_data(as_text=True)

    _concluir(painel, "PRO-000001")

    assert "faltando" not in portal.get("/portal/casos/CAS-000001").get_data(as_text=True)
    assert "Documento de identificação" not in portal.get("/portal/casos/CAS-000001").get_data(as_text=True)


def test_ficha_do_caso_no_painel_mostra_o_que_foi_entregue(painel):
    _concluir(painel, "PRO-000001")

    processo = painel.get("/api/casos/CAS-000001").get_json()["processos"][0]

    assert processo["documento_final_tipo"].startswith("CRAF")
    assert processo["documento_final_nome"] == "craf-novo.pdf"


def test_tirar_do_dossie_desfaz_a_entrega(painel):
    """Sem soltar o vínculo antes, apagar o documento esbarraria na chave
    estrangeira do processo -- erro 500 no botão de remover."""
    documento_id = _concluir(painel, "PRO-000001").get_json()["documento_id"]

    resposta = painel.post(f"/api/dossie/{documento_id}/remover")

    assert resposta.status_code == 200
    assert _processo("PRO-000001")["documento_final_id"] is None


def test_concluir_sem_arquivo_e_recusado(painel):
    resposta = painel.post("/api/processos/PRO-000001/concluir", data={"tipo_documento": "CRAF"})

    assert resposta.status_code == 400
    assert _processo("PRO-000001")["status"] != "Concluído"


def test_migracao_e_idempotente(banco):
    assert migrar_documento_final.migrar() == {"coluna_criada": False}


# --------------------------------------------------------------------
# 2. O que não pode acontecer
# --------------------------------------------------------------------

def test_documento_de_um_cliente_nunca_baixa_pelo_outro(painel, portal):
    """O CRAF do Bruno (mesma empresa da Ana). O filtro de empresa não
    separa os dois -- quem separa é a checagem de dono do download."""
    documento_do_bruno = _concluir(painel, "PRO-000002").get_json()["documento_id"]

    assert portal.get(f"/portal/documentos/{documento_do_bruno}/arquivo").status_code == 404


def test_portal_nao_mostra_documento_final_que_nao_e_do_dono_do_processo(banco, portal):
    """Vínculo errado gravado no banco (bug futuro, edição manual): o
    processo da Ana apontando para o documento do Bruno. O Portal não pode
    oferecer esse arquivo para a Ana, nem pelo nome."""
    con = conectar(EMPRESA_A)
    con.execute("UPDATE processo SET documento_final_id = 'DOC-000002' WHERE processo_id = 'PRO-000001'")
    con.commit()
    con.close()

    pagina = portal.get("/portal/casos/CAS-000001").get_data(as_text=True)

    assert "Seu documento está pronto" not in pagina
    assert "DOC-000002" not in pagina


def test_painel_nao_conclui_processo_de_outra_empresa(painel):
    resposta = _concluir(painel, "PRO-000003")

    assert resposta.status_code == 400
    processo = _processo("PRO-000003", EMPRESA_B)
    assert processo["status"] != "Concluído"
    assert processo["documento_final_id"] is None
    con = conectar(EMPRESA_B)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM documento WHERE nome_arquivo = 'craf-novo.pdf'"
        ).fetchone()[0] == 0
    finally:
        con.close()
