"""Dossiê do cliente: documento que pertence à PESSOA, não a um caso.

O risco aqui é o mais sério do projeto. O dossiê guarda CR, CRAF e laudo
de gente real, e é servido no PORTAL -- a única superfície pública do
sistema. Um erro não dá tela branca: entrega o documento de identidade de
uma pessoa para outra.

Por isso o teste mais importante deste arquivo não é o que confere se o
dossiê aparece, e sim o que confere que ele NÃO aparece para quem não é
dono -- inclusive entre dois clientes da MESMA empresa, que é o caso que
o filtro de empresa_id não cobre.
"""
import sqlite3
from datetime import date, timedelta

import pytest

from core import motor_documentos
from core.conexao import conectar_admin
from tests.conftest import EMPRESA_A, EMPRESA_B


def _guardar(cliente_id, tipo, empresa_id=EMPRESA_A, **campos):
    return motor_documentos.salvar_no_dossie(
        empresa_id, cliente_id, b"%PDF-1.4 conteudo do documento",
        f"{tipo}.pdf", tipo_documento=tipo, **campos
    )


# --------------------------------------------------------------------
# O que o banco garante
# --------------------------------------------------------------------

def test_dossie_nasce_sem_caso_e_sem_processo(banco):
    """É a diferença que justifica a categoria existir: o CR da pessoa
    não pertence a atendimento nenhum."""
    documento_id = _guardar("CLI-000001", "CR — Certificado de Registro")

    guardado = motor_documentos.obter_documento(EMPRESA_A, documento_id)

    assert guardado["categoria"] == "Dossiê"
    assert guardado["caso_id"] is None
    assert guardado["processo_id"] is None


def test_cliente_de_outra_empresa_e_recusado_antes_de_gravar_arquivo(banco):
    """A checagem vem ANTES do disco -- gravar e conferir depois deixaria
    arquivo órfão na pasta da empresa errada."""
    with pytest.raises(ValueError, match="Cliente não encontrado"):
        _guardar("CLI-000003", "CR — Certificado de Registro")  # cliente da EMPRESA_B

    # Nenhum documento de dossiê criado, e nenhum arquivo em disco: o
    # fixture já traz 3 documentos de CASO, então contar a tabela inteira
    # não diria nada.
    con = conectar_admin()
    dossies = con.execute(
        "SELECT COUNT(*) FROM documento WHERE categoria = 'Dossiê'"
    ).fetchone()[0]
    con.close()
    assert dossies == 0
    assert not (motor_documentos.PASTA_DOCUMENTOS / EMPRESA_A / "CLI-000003").exists()


def test_tipo_vazio_e_recusado(banco):
    with pytest.raises(ValueError, match="tipo do documento"):
        _guardar("CLI-000001", "   ")


# --------------------------------------------------------------------
# Validade -- é dela que sai o serviço do despachante
# --------------------------------------------------------------------

def test_sem_data_de_validade_nao_e_valido_e_nem_vencido(banco):
    """`None` não é 'valido'. Documento sem data é documento cuja
    validade ninguém sabe, e pintar de verde afirmaria o que não se
    consultou -- a mesma regra que vale no Dashboard inteiro."""
    _guardar("CLI-000001", "CPF")

    documento = motor_documentos.listar_dossie(EMPRESA_A, "CLI-000001")[0]

    assert documento["situacao_validade"] is None


def test_tres_situacoes_de_validade(banco):
    hoje = date.today()
    _guardar("CLI-000001", "Certidão vencida",
             data_validade=(hoje - timedelta(days=1)).isoformat())
    _guardar("CLI-000001", "Laudo vencendo",
             data_validade=(hoje + timedelta(days=10)).isoformat())
    _guardar("CLI-000001", "CR novo",
             data_validade=(hoje + timedelta(days=400)).isoformat())

    por_tipo = {
        d["tipo_documento"]: d["situacao_validade"]
        for d in motor_documentos.listar_dossie(EMPRESA_A, "CLI-000001", hoje=hoje.isoformat())
    }

    assert por_tipo["Certidão vencida"] == "vencido"
    assert por_tipo["Laudo vencendo"] == "vencendo"
    assert por_tipo["CR novo"] == "valido"


def test_referencia_guarda_de_qual_arma_e_o_craf(banco):
    """Pedido explícito do usuário: "CRAF de tal arma". Sem isso, três
    CRAFs no dossiê ficam indistinguíveis."""
    documento_id = _guardar(
        "CLI-000001", "CRAF — Certificado de Registro de Arma de Fogo",
        referencia="Pistola .380 TH380 — série ABA212416",
    )

    guardado = motor_documentos.obter_documento(EMPRESA_A, documento_id)

    assert "TH380" in guardado["observacoes"]


# --------------------------------------------------------------------
# Isolamento -- a parte que não pode falhar
# --------------------------------------------------------------------

def test_dossie_de_um_cliente_nao_aparece_no_do_outro(banco):
    """Ana e Bruno são da MESMA empresa. O filtro de empresa_id não
    separa os dois -- quem separa é o cliente_id."""
    _guardar("CLI-000001", "CR da Ana")
    _guardar("CLI-000002", "CR do Bruno")

    da_ana = motor_documentos.listar_dossie(EMPRESA_A, "CLI-000001")

    assert [d["tipo_documento"] for d in da_ana] == ["CR da Ana"]


def test_dossie_nao_atravessa_empresa(banco):
    _guardar("CLI-000001", "CR da Ana")
    _guardar("CLI-000003", "CR da Carla", empresa_id=EMPRESA_B)

    assert len(motor_documentos.listar_dossie(EMPRESA_A, "CLI-000001")) == 1
    assert motor_documentos.listar_dossie(EMPRESA_A, "CLI-000003") == []


def test_painel_nao_lista_dossie_de_cliente_de_outra_empresa(banco, painel):
    _guardar("CLI-000003", "CR da Carla", empresa_id=EMPRESA_B)

    resposta = painel.get("/api/clientes/CLI-000003/dossie")

    assert resposta.status_code == 404
    assert "Carla" not in resposta.get_data(as_text=True)


def test_painel_nao_remove_dossie_de_outra_empresa(banco, painel):
    documento_id = _guardar("CLI-000003", "CR da Carla", empresa_id=EMPRESA_B)

    resposta = painel.post(f"/api/dossie/{documento_id}/remover")

    assert resposta.status_code == 404
    assert motor_documentos.obter_documento(EMPRESA_B, documento_id) is not None


def test_painel_nao_remove_documento_de_caso_por_esta_rota(banco, painel):
    """Documento de caso tem outras consequências (checklist marcado,
    histórico do processo). Uma rota que apagasse os dois convidaria ao
    engano."""
    resposta = painel.post("/api/dossie/DOC-000001/remover")

    assert resposta.status_code == 404
    assert motor_documentos.obter_documento(EMPRESA_A, "DOC-000001") is not None


# --------------------------------------------------------------------
# Portal -- superfície pública
# --------------------------------------------------------------------

def test_portal_mostra_so_o_dossie_do_proprio_cliente(banco, portal):
    """`portal` está logado como Ana (CLI-000001)."""
    _guardar("CLI-000001", "Laudo de aptidão psicológica")
    _guardar("CLI-000002", "CR do Bruno")

    corpo = portal.get("/portal/minha-conta").get_data(as_text=True)

    assert "Laudo de aptidão psicológica" in corpo
    assert "CR do Bruno" not in corpo


def test_portal_nao_serve_arquivo_de_dossie_alheio(banco, portal):
    """O ID é sequencial e fácil de adivinhar. É a checagem de DONO que
    segura isso, não a obscuridade do identificador."""
    documento_id = _guardar("CLI-000002", "CR do Bruno")

    resposta = portal.get(f"/portal/documentos/{documento_id}/arquivo")

    assert resposta.status_code == 404
    assert b"conteudo do documento" not in resposta.data


def test_portal_serve_inline_e_como_download_o_mesmo_arquivo(banco, portal):
    """Ver dentro da plataforma e salvar são o MESMO arquivo e a MESMA
    checagem de posse -- só muda o cabeçalho de disposição."""
    documento_id = _guardar("CLI-000001", "CR — Certificado de Registro")

    inline = portal.get(f"/portal/documentos/{documento_id}/arquivo?inline=1")
    baixando = portal.get(f"/portal/documentos/{documento_id}/arquivo")

    assert inline.status_code == baixando.status_code == 200
    assert inline.data == baixando.data
    assert "attachment" not in inline.headers.get("Content-Disposition", "")
    assert "attachment" in baixando.headers.get("Content-Disposition", "")


def test_portal_nao_serve_inline_documento_alheio(banco, portal):
    """O parâmetro inline não pode ter virado um caminho paralelo sem a
    checagem de dono."""
    documento_id = _guardar("CLI-000002", "CR do Bruno")

    resposta = portal.get(f"/portal/documentos/{documento_id}/arquivo?inline=1")

    assert resposta.status_code == 404


def test_portal_avisa_documento_vencido(banco, portal):
    _guardar("CLI-000001", "Certidão negativa — Justiça Federal",
             data_validade=(date.today() - timedelta(days=5)).isoformat())

    corpo = portal.get("/portal/minha-conta").get_data(as_text=True)

    assert "validade vencida" in corpo
