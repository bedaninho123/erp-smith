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


# --------------------------------------------------------------------
# PDF pronto para o menu de compartilhar do iPhone (2026-10-19)
# --------------------------------------------------------------------

import base64
import re
import zlib


def _texto_do_pdf(pdf: bytes) -> str:
    """Junta o texto de todas as páginas, sem biblioteca de leitura de
    PDF: o fpdf2 comprime cada página com zlib e escreve o texto como
    literal, então basta descomprimir os blocos."""
    partes = []
    for bloco in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            partes.append(zlib.decompress(bloco).decode("latin-1"))
        except zlib.error:
            pass  # imagem ou bloco não comprimido com zlib
    return "\n".join(partes)


def _pdf_da_folha(html: str) -> bytes:
    achado = re.search(r'var pdfBase64 = "([^"]+)"', html)
    assert achado, "a folha não trouxe o PDF"
    return base64.b64decode(achado.group(1))


def test_pdf_da_folha_diz_o_mesmo_que_a_folha(banco, portal_filiado, habitualidade_falsa):
    html = portal_filiado.get("/portal/habitualidade/imprimir?periodo=24").get_data(as_text=True)
    pdf = _pdf_da_folha(html)

    assert pdf.startswith(b"%PDF")
    texto = _texto_do_pdf(pdf)
    assert "Ana Teste" in texto
    assert "111.111.111-11" in texto
    assert "Mod Dezesseis Meses" in texto
    assert "Mod Trinta Meses" not in texto
    # Uma consulta só para tela e PDF -- o PDF não chama a API de novo.
    assert len(habitualidade_falsa) == 1


def test_sem_pdf_quando_a_consulta_falha(banco, portal_filiado, monkeypatch):
    from integracoes.shooting_house import ShootingHouseIndisponivel

    def falha(*args, **kwargs):
        raise ShootingHouseIndisponivel("fora do ar")

    monkeypatch.setattr(portal_app, "consultar_habitualidade", falha)
    monkeypatch.setattr(portal_app, "consultar_cr", falha)

    html = portal_filiado.get("/portal/habitualidade/imprimir").get_data(as_text=True)
    assert "var pdfBase64 = null;" in html


def test_falha_no_pdf_nao_derruba_a_folha(banco, portal_filiado, habitualidade_falsa, monkeypatch):
    def quebra(dados):
        raise RuntimeError("pdf quebrou")

    monkeypatch.setattr(portal_app, "gerar_pdf_habitualidade", quebra)
    resposta = portal_filiado.get("/portal/habitualidade/imprimir")

    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert 'id="botao-imprimir"' in html
    assert "var pdfBase64 = null;" in html


def test_pdf_aguenta_caractere_fora_da_fonte():
    """Texto vindo da API com travessão, aspas curvas ou emoji não pode
    derrubar a geração."""
    from portal.pdf_habitualidade import gerar_pdf

    eventos = [{"data_participacao": "01/10/2026", "hora_participacao": "16:30",
                "modalidade": "Tiro — Rápido “IPSC”", "grupo": "ACLP",
                "competicao": "TREINO", "arma": "Pistola 🔫 9mm", "local": "Estande"}] * 60
    pdf = gerar_pdf({
        "atirador_nome": "José da Conceição", "cpf_formatado": "111.111.111-11",
        "meses": 12, "inicio_periodo": "19/10/2025", "emitido_em": "19/10/2026 às 10:00",
        "nome_clube": "Clube Teste", "participacoes_periodo": 60,
        "treinos_provas_periodo": {"treinos": 60, "provas": 0, "total": 60},
        "ultima_participacao": "01/10/2026", "eventos": eventos,
    })
    texto = _texto_do_pdf(pdf)
    assert "Concei" in texto
    assert "Página 2 de" in texto  # 60 linhas quebram em mais de uma página
