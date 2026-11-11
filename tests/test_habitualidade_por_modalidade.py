"""Habitualidade por modalidade e folha do recorte (2026-11-10).

Pedido do usuário: tocar em "20 treinos nos últimos 12 meses" abre a
lista desses 20; e mostrar quantas participações a pessoa tem em cada
modalidade ("Provas Nacionais", "Provas Especiais"...) em 6, 12, 24 e 36
meses, na tela e no relatório.

O que não pode falhar:
1. A soma de uma coluna da tabela bate com o cartão daquele período --
   senão a tela se contradiz.
2. A folha "só treinos" lista exatamente o que o cartão "N treinos" conta.
3. Recorte que vem da URL e não existe vira a folha completa, nunca uma
   folha vazia dizendo "nenhum registro".
"""
from datetime import date, timedelta

import pytest

import portal.app as portal_app
from domain.clube_tiro.motor_filiados import (
    SEM_MODALIDADE,
    contar_participacoes,
    contar_por_modalidade,
    contar_treinos_e_provas,
)
from tests.test_portal_periodo_habitualidade import _pdf_da_folha, _texto_do_pdf


def _dia(dias_atras: int) -> str:
    return (date.today() - timedelta(days=dias_atras)).strftime("%d/%m/%Y")


HABITUALIDADE = {"habitualidades": {
    "ACLP": {"eventos": [
        {"data_participacao": _dia(5), "modalidade": "Provas Nacionais", "competicao": "Copa Nacional"},
        {"data_participacao": _dia(100), "modalidade": "Provas Nacionais", "competicao": "Copa Nacional"},
        {"data_participacao": _dia(250), "modalidade": "Provas Especiais", "competicao": "Prova Especial"},
        {"data_participacao": _dia(20), "modalidade": "Treino", "competicao": "TREINO"},
        {"data_participacao": _dia(40), "modalidade": "Treino", "competicao": "TREINO"},
    ]},
    "ACLC": {"eventos": [
        {"data_participacao": _dia(500), "modalidade": "Provas Especiais", "competicao": "Prova Especial"},
        {"data_participacao": _dia(900), "modalidade": "Provas Nacionais", "competicao": "Copa Nacional"},
        {"data_participacao": _dia(60), "modalidade": None, "competicao": "TREINO"},
        {"data_participacao": "data-quebrada", "modalidade": "Treino", "competicao": "TREINO"},
    ]},
}}


# --------------------------------------------------------------------
# A contagem, sem tela
# --------------------------------------------------------------------

def test_conta_cada_modalidade_nos_quatro_periodos():
    linhas = {l["modalidade"]: l["contagens"] for l in contar_por_modalidade(HABITUALIDADE)}
    assert linhas["Provas Nacionais"] == {6: 2, 12: 2, 24: 2, 36: 3}
    assert linhas["Provas Especiais"] == {6: 0, 12: 1, 24: 2, 36: 2}
    assert linhas["Treino"] == {6: 2, 12: 2, 24: 2, 36: 2}
    # Sem modalidade não some: sumir faria a coluna somar menos que o total.
    assert linhas[SEM_MODALIDADE] == {6: 1, 12: 1, 24: 1, 36: 1}


def test_mais_frequente_primeiro():
    nomes = [l["modalidade"] for l in contar_por_modalidade(HABITUALIDADE)]
    assert nomes[0] == "Provas Nacionais"


@pytest.mark.parametrize("meses", [6, 12, 24, 36])
def test_soma_da_coluna_bate_com_o_cartao(meses):
    total, _ultima = contar_participacoes(HABITUALIDADE, meses=meses)
    soma = sum(l["contagens"][meses] for l in contar_por_modalidade(HABITUALIDADE))
    assert soma == total


# --------------------------------------------------------------------
# Tela e folha
# --------------------------------------------------------------------

@pytest.fixture
def portal_com_habitualidade(portal, monkeypatch):
    from tests.conftest import marcar_socio_conferido

    marcar_socio_conferido(portal)
    monkeypatch.setattr(portal_app, "consultar_habitualidade", lambda *a, **k: HABITUALIDADE)
    monkeypatch.setattr(portal_app, "consultar_cr", lambda cpf: None)
    return portal


def _lista(html: str, titulo: str) -> str:
    """Só a lista de registros da folha, abaixo do título dela."""
    return html.split(titulo, 1)[1]


def test_cartoes_abrem_a_folha_do_recorte(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get("/portal/habitualidade?periodo=12").get_data(as_text=True)
    assert "/portal/habitualidade/imprimir?periodo=12&amp;tipo=treinos" in html
    assert "/portal/habitualidade/imprimir?periodo=12&amp;tipo=provas" in html


def test_tela_mostra_a_tabela_por_modalidade(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get("/portal/habitualidade?periodo=12").get_data(as_text=True)
    assert "Por modalidade" in html
    assert "Provas Especiais" in html
    # Cada número abre a folha daquela modalidade naquele período.
    assert "/portal/habitualidade/imprimir?periodo=36&amp;modalidade=Provas+Nacionais" in html


def test_folha_so_de_treinos_lista_o_que_o_cartao_conta(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get(
        "/portal/habitualidade/imprimir?periodo=12&tipo=treinos").get_data(as_text=True)
    treinos = contar_treinos_e_provas(HABITUALIDADE, meses=12)["treinos"]

    assert "Treinos nos últimos 12 meses" in html
    assert f"{treinos} registros" in html
    lista = _lista(html, "Treinos nos últimos 12 meses")
    assert "Copa Nacional" not in lista
    assert lista.count("<td>Treino</td>") == treinos


def test_folha_so_de_provas(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get(
        "/portal/habitualidade/imprimir?periodo=12&tipo=provas").get_data(as_text=True)
    lista = _lista(html, "Provas nos últimos 12 meses")
    assert lista.count("<td>Prova</td>") == 3
    assert "<td>Treino</td>" not in lista


def test_folha_de_uma_modalidade(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get(
        "/portal/habitualidade/imprimir?periodo=36&modalidade=Provas+Nacionais").get_data(as_text=True)
    assert "Provas Nacionais nos últimos 36 meses" in html
    lista = _lista(html, "Provas Nacionais nos últimos 36 meses")
    assert "3 registros" in lista
    assert "Provas Especiais" not in lista


@pytest.mark.parametrize("consulta", ["tipo=tudo", "modalidade=Inventada", "tipo=", "modalidade="])
def test_recorte_que_nao_existe_vira_a_folha_completa(banco, portal_com_habitualidade, consulta):
    html = portal_com_habitualidade.get(
        f"/portal/habitualidade/imprimir?periodo=36&{consulta}").get_data(as_text=True)
    assert "Todas as participações" in html
    assert "Participações nos últimos 36 meses" in html
    assert "Nenhum registro" not in html


def test_pdf_traz_a_tabela_e_o_recorte(banco, portal_com_habitualidade):
    html = portal_com_habitualidade.get(
        "/portal/habitualidade/imprimir?periodo=12&tipo=treinos").get_data(as_text=True)
    texto = _texto_do_pdf(_pdf_da_folha(html))
    assert "Participações por modalidade" in texto
    assert "Provas Especiais" in texto
    assert "Treinos nos últimos 12 meses" in texto
    lista = texto.split("Treinos nos últimos 12 meses", 1)[1]
    assert "Copa" not in lista
