"""Pedidos de 2026-09-24: o que o despachante anota sobre o filiado, os
documentos dele, o botão "Ver filiado" no Caso -- e o status de caso que
"não mudava".

O que estes testes protegem:

- Falha do Gmail NUNCA desfaz, nem esconde, uma mudança de status. Era a
  causa provável do "não está mudando o status dos casos": o banco
  mudava e a rota devolvia 500.
- Datas do CR, SIGMA e acervo só se gravam para filiado da PRÓPRIA
  empresa -- a URL leva um CPF, e sem a trava qualquer CPF digitado
  viraria anotação.
- Documento do filiado vai para o MESMO dossiê do cliente, e quem ainda
  não é cliente ganha cadastro no primeiro documento (sem duplicar).
"""
import io
import sqlite3

from core.conexao import conectar_admin
from domain.clube_tiro import motor_anotacoes_filiado
from motor_ia.conexao import DOMAIN_DB
from tests.conftest import AGORA, EMPRESA_A, EMPRESA_B

CPF_FILIADO = "52998224725"   # válido, e não é cliente de ninguém no fixture
CPF_DA_ANA = "11111111111"    # CLI-000001, cliente da EMPRESA_A


def _filiado(empresa_id, cpf, nome="Filiado Teste", filiado_id="FIL-000001"):
    con = sqlite3.connect(DOMAIN_DB)
    con.execute(
        "INSERT INTO filiado (filiado_id, empresa_id, nome, cpf, email, status_filiacao, "
        "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?)",
        (filiado_id, empresa_id, nome, cpf, "filiado@example.com", "Ativo", AGORA, AGORA),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------
# Status do caso
# ---------------------------------------------------------------------

def test_status_muda_mesmo_com_gmail_quebrado(banco, painel, monkeypatch):
    """Token do Gmail revogado (invalid_grant) não pode virar 500 depois
    de o status já estar gravado."""
    import webapp.app as app_mod

    def _gmail_quebrado(*args, **kwargs):
        raise RuntimeError("invalid_grant")

    monkeypatch.setattr(app_mod, "_enviar_notificacao_mudanca_status", _gmail_quebrado)

    resposta = painel.post("/api/casos/CAS-000001/status", json={"status": "Em andamento"})
    assert resposta.status_code == 200

    con = conectar_admin()
    status = con.execute("SELECT status FROM caso WHERE caso_id = 'CAS-000001'").fetchone()[0]
    con.close()
    assert status == "Em andamento"


# ---------------------------------------------------------------------
# Botão "Ver filiado" no Caso
# ---------------------------------------------------------------------

def test_caso_de_filiado_traz_cpf_para_o_botao(banco, painel):
    _filiado(EMPRESA_A, CPF_DA_ANA, nome="Ana Teste")
    d = painel.get("/api/casos/CAS-000001").get_json()
    assert d["filiado_cpf"] == CPF_DA_ANA


def test_caso_de_quem_nao_e_filiado_nao_tem_botao(banco, painel):
    d = painel.get("/api/casos/CAS-000001").get_json()
    assert d["filiado_cpf"] is None


def test_filiado_de_outra_empresa_nao_liga_o_botao(banco, painel):
    """Mesmo CPF filiado a OUTRO clube não é filiado deste."""
    _filiado(EMPRESA_B, CPF_DA_ANA, nome="Carla Outra")
    d = painel.get("/api/casos/CAS-000001").get_json()
    assert d["filiado_cpf"] is None


# ---------------------------------------------------------------------
# Datas do CR
# ---------------------------------------------------------------------

def test_salva_datas_do_cr(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)
    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/cr", json={
        "data_expedicao": "2024-03-10", "data_vencimento": "2034-03-10",
    })
    assert resposta.status_code == 200
    cr = motor_anotacoes_filiado.obter_cr(EMPRESA_A, CPF_FILIADO)
    assert (cr["data_expedicao"], cr["data_vencimento"]) == ("2024-03-10", "2034-03-10")
    assert cr["atualizado_por"] == "Gestor Teste"


def test_vencimento_antes_da_expedicao_e_recusado(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)
    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/cr", json={
        "data_expedicao": "2024-03-10", "data_vencimento": "2020-01-01",
    })
    assert resposta.status_code == 400


def test_nao_anota_cr_de_filiado_de_outra_empresa(banco, painel):
    _filiado(EMPRESA_B, CPF_FILIADO)
    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/cr", json={"data_vencimento": "2030-01-01"})
    assert resposta.status_code == 404
    assert motor_anotacoes_filiado.obter_cr(EMPRESA_B, CPF_FILIADO)["data_vencimento"] is None


def test_vencimento_cadastrado_aparece_na_lista(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)
    painel.post(f"/api/filiados/{CPF_FILIADO}/cr", json={"data_vencimento": "2031-05-20"})
    d = painel.get("/api/filiados/panorama?situacao=").get_json()
    linha = next(f for f in d["filiados"] if f["cpf"] == CPF_FILIADO)
    assert linha["cr_vencimento"] == "2031-05-20"
    assert linha["cr_vencimento_origem"] == "manual"


# ---------------------------------------------------------------------
# SIGMA e acervo
# ---------------------------------------------------------------------

def test_salva_sigma_e_acervo_da_arma(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)
    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/armas/1020",
                           json={"sigma": "651561", "acervo": "Caça"})
    assert resposta.status_code == 200
    assert motor_anotacoes_filiado.anotacoes_armas(EMPRESA_A, CPF_FILIADO) == {
        "1020": {"sigma": "651561", "acervo": "Caça"},
    }


def test_acervo_fora_da_lista_e_recusado(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)
    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/armas/1020", json={"acervo": "tiro esportivo"})
    assert resposta.status_code == 400


def test_sigma_do_shooting_house_ganha_do_digitado():
    """A fonte oficial não pode ser escondida por uma digitação velha."""
    armas = [{"id": 1, "sigma": "OFICIAL"}, {"id": 2, "sigma": None}]
    notas = {"1": {"sigma": "DIGITADO", "acervo": "Tiro"}, "2": {"sigma": "DIGITADO2", "acervo": None}}
    a1, a2 = motor_anotacoes_filiado.mesclar_armas(armas, notas)
    assert (a1["sigma"], a1["sigma_origem"], a1["acervo"]) == ("OFICIAL", "api", "Tiro")
    assert (a2["sigma"], a2["sigma_origem"]) == ("DIGITADO2", "manual")


# ---------------------------------------------------------------------
# Documentos do filiado
# ---------------------------------------------------------------------

def _enviar(painel, cpf, tipo="CRAF — Certificado de Registro de Arma de Fogo"):
    return painel.post(
        f"/api/filiados/{cpf}/dossie",
        data={"tipo_documento": tipo, "arquivo": (io.BytesIO(b"%PDF-1.4 craf"), "craf.pdf")},
        content_type="multipart/form-data",
    )


def test_primeiro_documento_cria_cadastro_e_o_segundo_reaproveita(banco, painel):
    _filiado(EMPRESA_A, CPF_FILIADO)

    primeiro = _enviar(painel, CPF_FILIADO).get_json()
    assert primeiro["cadastro_criado"] is True
    segundo = _enviar(painel, CPF_FILIADO, tipo="Guia de Tráfego").get_json()
    assert segundo["cadastro_criado"] is False
    assert segundo["cliente_id"] == primeiro["cliente_id"]

    d = painel.get(f"/api/filiados/{CPF_FILIADO}/dossie").get_json()
    assert len(d["documentos"]) == 2
    # É o MESMO dossiê da ficha do cliente, não um depósito paralelo.
    pela_ficha = painel.get(f"/api/clientes/{primeiro['cliente_id']}/dossie").get_json()
    assert len(pela_ficha["documentos"]) == 2


def test_documento_de_filiado_que_ja_e_cliente_vai_para_o_cadastro_dele(banco, painel):
    _filiado(EMPRESA_A, CPF_DA_ANA, nome="Ana Teste")
    resposta = _enviar(painel, CPF_DA_ANA).get_json()
    assert resposta["cliente_id"] == "CLI-000001"
    assert resposta["cadastro_criado"] is False


def test_nao_guarda_documento_para_filiado_de_outra_empresa(banco, painel):
    _filiado(EMPRESA_B, CPF_FILIADO)
    assert _enviar(painel, CPF_FILIADO).status_code == 404
    assert painel.get(f"/api/filiados/{CPF_FILIADO}/dossie").status_code == 404


def test_tipo_segundo_endereco_de_acervo_no_catalogo():
    from domain.clube_tiro.documentos_cac import nomes
    assert "Comprovante do segundo endereço de acervo" in nomes()
