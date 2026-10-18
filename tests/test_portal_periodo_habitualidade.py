"""Filtro de período da tela Habitualidade do Portal (2026-10-17).

O atirador escolhe 6, 12, 24 ou 36 meses. O que estes testes guardam:
os cartões e a lista usam o MESMO corte de data (senão o cartão diria
"1 em 6 meses" em cima de uma lista de 4 linhas), e um período fora da
lista volta para 12 em vez de virar uma janela qualquer.
"""
from datetime import date, timedelta

import pytest

import portal.app as portal_app


def _dia(dias_atras: int) -> str:
    return (date.today() - timedelta(days=dias_atras)).strftime("%d/%m/%Y")


@pytest.fixture
def habitualidade_falsa(monkeypatch):
    """Quatro participações espalhadas em 3 anos, sem chamar a API."""
    dados = {"habitualidades": {"ACLP": {"count": 4, "eventos": [
        {"data_participacao": _dia(10), "modalidade": "Mod Recente", "competicao": "TREINO"},
        {"data_participacao": _dia(300), "modalidade": "Mod Oito Meses", "competicao": "TREINO"},
        {"data_participacao": _dia(500), "modalidade": "Mod Dezesseis Meses", "competicao": "Copa X"},
        {"data_participacao": _dia(1000), "modalidade": "Mod Trinta Meses", "competicao": "TREINO"},
    ]}}}
    chamadas = []

    def consultar(cpf, data_inicio=None, data_fim=None):
        chamadas.append({"data_inicio": data_inicio, "data_fim": data_fim})
        return dados

    monkeypatch.setattr(portal_app, "consultar_habitualidade", consultar)
    monkeypatch.setattr(portal_app, "consultar_cr", lambda cpf: None)
    return chamadas


@pytest.fixture
def portal_filiado(portal):
    with portal.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = True
    return portal


@pytest.mark.parametrize("periodo, visiveis", [
    ("6", ["Mod Recente"]),
    ("12", ["Mod Recente", "Mod Oito Meses"]),
    ("24", ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses"]),
    ("36", ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses", "Mod Trinta Meses"]),
])
def test_lista_e_cartao_seguem_o_periodo(banco, portal_filiado, habitualidade_falsa, periodo, visiveis):
    html = portal_filiado.get(f"/portal/habitualidade?periodo={periodo}").get_data(as_text=True)

    todas = ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses", "Mod Trinta Meses"]
    for modalidade in todas:
        assert (modalidade in html) == (modalidade in visiveis), modalidade
    assert f"participações nos últimos {periodo} meses" in html
    assert f"{len(visiveis)} de 4 no total" in html


@pytest.mark.parametrize("periodo", ["6", "12", "36"])
def test_consulta_sempre_pede_36_meses_em_formato_iso(banco, portal_filiado, habitualidade_falsa, periodo):
    """Sem startDate a API real devolve só 12 meses -- e aí os filtros de
    24 e 36 mostrariam o mesmo número do de 12, como se não houvesse nada
    antes. DD/MM/AAAA dá HTTP 500 lá; só AAAA-MM-DD funciona."""
    portal_filiado.get(f"/portal/habitualidade?periodo={periodo}")

    assert habitualidade_falsa[-1]["data_inicio"] == (date.today() - timedelta(days=1095)).isoformat()
    assert habitualidade_falsa[-1]["data_fim"] is None


def test_sem_periodo_ou_periodo_invalido_mostra_12_meses(banco, portal_filiado, habitualidade_falsa):
    for url in ("/portal/habitualidade", "/portal/habitualidade?periodo=999"):
        html = portal_filiado.get(url).get_data(as_text=True)
        assert "participações nos últimos 12 meses" in html
        assert "Mod Oito Meses" in html
        assert "Mod Dezesseis Meses" not in html


# --------------------------------------------------------------------
# Folha timbrada para imprimir / salvar em PDF
# --------------------------------------------------------------------

def test_folha_impressa_segue_o_periodo_e_identifica_o_atirador(banco, portal_filiado, habitualidade_falsa):
    html = portal_filiado.get("/portal/habitualidade/imprimir?periodo=24").get_data(as_text=True)

    assert "Relação de habitualidade" in html
    assert "Ana Teste" in html
    assert "111.111.111-11" in html
    assert "Últimos 24 meses" in html
    assert "Mod Dezesseis Meses" in html
    assert "Mod Trinta Meses" not in html
    assert "logo_smith.png" in html
    assert 'id="botao-imprimir"' in html


def test_tela_leva_para_a_folha_do_mesmo_periodo(banco, portal_filiado, habitualidade_falsa):
    html = portal_filiado.get("/portal/habitualidade?periodo=36").get_data(as_text=True)
    assert "/portal/habitualidade/imprimir?periodo=36" in html


def test_folha_nao_sai_vazia_quando_a_consulta_falha(banco, portal_filiado, monkeypatch):
    """Papel timbrado dizendo "nenhuma participação" para quem treinou é
    o pior documento que esta rota pode emitir."""
    from integracoes.shooting_house import ShootingHouseIndisponivel

    def falha(*args, **kwargs):
        raise ShootingHouseIndisponivel("fora do ar")

    monkeypatch.setattr(portal_app, "consultar_habitualidade", falha)
    monkeypatch.setattr(portal_app, "consultar_cr", falha)

    html = portal_filiado.get("/portal/habitualidade/imprimir").get_data(as_text=True)

    assert "Não foi possível consultar" in html
    assert "Nenhuma participação" not in html
    assert 'id="botao-imprimir"' not in html


def test_folha_e_exclusiva_de_filiado_logado(banco, portal):
    # Ana logada mas sem ser filiada ativa
    assert portal.get("/portal/habitualidade/imprimir").status_code == 403

    with portal.session_transaction() as sessao:
        sessao.clear()
    resposta = portal.get("/portal/habitualidade/imprimir")
    assert resposta.status_code == 302
