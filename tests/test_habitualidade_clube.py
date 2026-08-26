"""Panorama de habitualidade do clube (camada 1).

O que esta camada faz: CONTAR participações e ordenar por quem precisa de
atenção. O que ela deliberadamente NÃO faz: dizer se alguém cumpriu o
mínimo legal. O mínimo depende do nível do CR (Decreto nº 11.615/2023,
art. 35 -- 8, ou 12+4, ou 20+6), e a API do Shooting House não expõe o
nível de ninguém. Dizer a um atirador que ele está em dia quando não está
custa o CR dele.

A outra regra que estes testes protegem: o retrato guardado nunca pode se
passar por consulta ao vivo. Toda linha carrega `sincronizado_em`, e
"nunca consultado" tem que ser distinguível de "consultei e deu zero".
"""
import sqlite3
from datetime import date

import pytest

from domain.clube_tiro import motor_filiados
from tests.conftest import EMPRESA_A, EMPRESA_B

FILIADO_A = {
    "idatirador": 101, "matricula": "F101", "nome": "Atirador Um",
    "cpf": "52998224725", "email": "um@exemplo.local", "status_filiacao": "Ativo",
}
FILIADO_B = {
    "idatirador": 102, "matricula": "F102", "nome": "Atirador Dois",
    "cpf": "11144477735", "email": None, "status_filiacao": "Ativo",
}


@pytest.fixture
def dominio(tmp_path, monkeypatch):
    """Banco de Domínio temporário, com a tabela filiado criada a partir
    do schema REAL -- nunca de uma cópia escrita à mão aqui, que sairia
    de sincronia sem ninguém perceber (mesma regra do conftest do Core)."""
    from pathlib import Path

    caminho = tmp_path / "dominio_teste.db"
    schema = (Path(__file__).resolve().parent.parent
              / "domain" / "clube_tiro" / "db" / "schema.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(caminho)
    con.executescript(schema)
    con.commit()
    con.close()

    monkeypatch.setattr(motor_filiados, "DOMAIN_DB", str(caminho))
    return caminho


# --------------------------------------------------------------------
# Contagem
# --------------------------------------------------------------------

def _habitualidade(datas):
    return {"habitualidades": {"ACLP": {
        "count": len(datas),
        "eventos": [{"data_participacao": d} for d in datas],
    }}}


def test_conta_so_o_que_esta_dentro_da_janela():
    hoje = date(2026, 8, 25)
    dados = _habitualidade([
        "01/09/2025",  # dentro (menos de 12 meses)
        "15/01/2026",  # dentro
        "20/08/2026",  # dentro
        "01/06/2025",  # FORA -- mais de 12 meses
    ])

    total, ultima = motor_filiados.contar_participacoes(dados, hoje=hoje)

    assert total == 3
    # A última participação é a mais recente de TODAS, não só das da
    # janela -- é o que responde "há quanto tempo essa pessoa não aparece".
    assert ultima == "2026-08-20"


def test_sem_evento_nenhum_conta_zero():
    total, ultima = motor_filiados.contar_participacoes({"habitualidades": {}})

    assert total == 0
    assert ultima is None


def test_data_em_formato_estranho_nao_vira_contagem_errada():
    """A API real manda "09/10/2025 16:30"; o normalizador separa a hora,
    mas se um dia vier algo que não dá pra ler, ignorar é melhor que
    contar errado -- este número orienta cobrança de gente."""
    dados = _habitualidade(["15/01/2026", "sei lá quando", ""])

    total, _ = motor_filiados.contar_participacoes(dados, hoje=date(2026, 8, 25))

    assert total == 1


# --------------------------------------------------------------------
# Guarda e leitura
# --------------------------------------------------------------------

def test_salvar_filiado_e_idempotente(dominio):
    primeiro = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    segundo = motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Nome Corrigido"))

    assert primeiro == segundo
    panorama = motor_filiados.listar_panorama(EMPRESA_A)
    assert len(panorama) == 1
    assert panorama[0]["nome"] == "Nome Corrigido"


def test_o_mesmo_cpf_pode_ser_filiado_de_duas_empresas(dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_B, FILIADO_A)

    assert len(motor_filiados.listar_panorama(EMPRESA_A)) == 1
    assert len(motor_filiados.listar_panorama(EMPRESA_B)) == 1


def test_panorama_nao_vaza_filiado_de_outra_empresa(dominio):
    """O banco de Domínio é anexado, então NÃO passa pelas views do Core
    que se filtram sozinhas -- aqui o filtro é escrito à mão, e é isso
    que este teste protege."""
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_B, FILIADO_B)

    panorama = motor_filiados.listar_panorama(EMPRESA_A)

    assert [f["cpf"] for f in panorama] == [FILIADO_A["cpf"]]


def test_nunca_sincronizado_e_diferente_de_zero_participacoes(dominio):
    """A distinção que a tela precisa: "não sei" e "sei que não teve" não
    podem parecer a mesma coisa. Nunca sincronizado é NULL, não 0."""
    nunca = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    zerado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)
    motor_filiados.registrar_habitualidade(EMPRESA_A, zerado, 0, None)

    por_id = {f["filiado_id"]: f for f in motor_filiados.listar_panorama(EMPRESA_A)}

    assert por_id[nunca]["participacoes_12m"] is None
    assert por_id[nunca]["sincronizado_em"] is None
    assert por_id[zerado]["participacoes_12m"] == 0
    assert por_id[zerado]["sincronizado_em"] is not None


def test_falha_de_consulta_nao_apaga_o_retrato_anterior(dominio):
    """Um retrato velho e datado vale mais que nenhum -- desde que a tela
    mostre a data, que é por isso que sincronizado_em é preservado."""
    filiado_id = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, filiado_id, 7, "2026-08-01")
    sincronizado_antes = motor_filiados.listar_panorama(EMPRESA_A)[0]["sincronizado_em"]

    motor_filiados.registrar_habitualidade(
        EMPRESA_A, filiado_id, None, None, erro="Shooting House respondeu HTTP 503."
    )

    linha = motor_filiados.listar_panorama(EMPRESA_A)[0]
    assert linha["participacoes_12m"] == 7
    assert linha["ultima_participacao"] == "2026-08-01"
    assert linha["sincronizado_em"] == sincronizado_antes
    assert "503" in linha["sincronizacao_erro"]


def test_fila_de_sincronizacao_comeca_por_quem_nunca_foi_consultado(dominio):
    ja_visto = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, ja_visto, 5, "2026-08-01")
    nunca = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)

    fila = motor_filiados.proximos_a_sincronizar(EMPRESA_A, limite=10)

    assert fila[0]["filiado_id"] == nunca


def test_limite_da_fila_e_respeitado(dominio):
    """É o que impede uma rodada de despejar 900 chamadas na API do
    fornecedor de uma vez."""
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)

    assert len(motor_filiados.proximos_a_sincronizar(EMPRESA_A, limite=1)) == 1


def test_panorama_ordena_por_quem_precisa_de_atencao(dominio):
    em_dia = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, em_dia, 12, "2026-08-20")
    atrasado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)
    motor_filiados.registrar_habitualidade(EMPRESA_A, atrasado, 1, "2026-02-01")

    panorama = motor_filiados.listar_panorama(EMPRESA_A)

    assert panorama[0]["filiado_id"] == atrasado


def test_paginacao_que_nao_anda_para_em_vez_de_martelar_a_api(monkeypatch):
    """`page` é suposição nossa -- a especificação do endpoint documenta
    só sortBy e status. Se ele for ignorado, a API devolve sempre a
    página 1, e um laço ingênuo pediria a mesma coisa até bater a trava:
    200 chamadas ao fornecedor e milhares de linhas repetidas."""
    from integracoes import shooting_house

    chamadas = []

    def _sempre_a_pagina_1(caminho, params=None):
        chamadas.append(params)
        return {
            "data": [{"id": 1, "name": "Fulano", "cpf": "52998224725", "status": "A"}],
            "meta": {"pagination": {"current_page": 1, "total_pages": 121}},
        }

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _sempre_a_pagina_1)

    filiados = shooting_house.listar_filiados()

    # Duas chamadas é o mínimo possível: só comparando a segunda resposta
    # com a primeira dá pra saber que a página não andou. O que não pode
    # é continuar depois disso, nem trazer a mesma pessoa duas vezes.
    assert len(chamadas) == 2, f"deveria parar na segunda; fez {len(chamadas)}"
    assert len(filiados) == 1, "trouxe gente repetida"


def test_paginacao_que_anda_percorre_todas(monkeypatch):
    """Controle positivo: sem isto, um laço que parasse sempre na
    primeira página passaria no teste acima e traria 1/121 do clube."""
    from integracoes import shooting_house

    # Uma pessoa DIFERENTE por página -- é o que paginação de verdade faz,
    # e é o que separa "percorreu as três" de "pediu três vezes a mesma".
    por_pagina = {1: "52998224725", 2: "11144477735", 3: "39053344705"}

    def _paginado(caminho, params=None):
        pagina = params["page"]
        return {
            "data": [{"id": pagina, "name": f"Filiado {pagina}",
                      "cpf": por_pagina[pagina], "status": "A"}],
            "meta": {"pagination": {"current_page": pagina, "total_pages": 3}},
        }

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _paginado)

    assert len(shooting_house.listar_filiados()) == 3


def test_cadastro_nao_grava_bairro_no_campo_cidade(monkeypatch):
    """O bloco `address` da API não tem cidade -- tem district (bairro).
    Preencher cidade com o bairro seria um erro silencioso, que só
    apareceria quando alguém filtrasse clientes por cidade."""
    from integracoes import shooting_house

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(
        shooting_house, "_chamar_api",
        lambda caminho, params=None: {
            "name": "Fulano", "cpf": "52998224725", "status": "A",
            "address": {"address": "Rua X", "district": "Centro", "zip": "17500000"},
        },
    )

    cadastro = shooting_house.consultar_cadastro("52998224725")

    assert cadastro["cidade"] is None
    assert "Centro" not in str(cadastro.values())


def test_resumo_conta_sem_dado_e_sem_participacao(dominio):
    sem_dado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)  # noqa: F841
    zerado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)
    motor_filiados.registrar_habitualidade(EMPRESA_A, zerado, 0, None)

    resumo = motor_filiados.resumo_do_clube(EMPRESA_A)

    assert resumo["total"] == 2
    assert resumo["sem_dado"] == 1
    assert resumo["sem_participacao"] == 1
