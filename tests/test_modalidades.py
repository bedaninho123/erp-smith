"""Catálogo de modalidades espelhado do Shooting House.

É catálogo, não dado de pessoa -- o que muda o que precisa ser
protegido. Não há CPF nem nome aqui; o que erra em silêncio é outra
coisa: modalidade que some do clube apagando resultado antigo, e
catálogo de uma empresa aparecendo na outra.
"""
import sqlite3

from domain.clube_tiro import motor_modalidades
from motor_ia.conexao import DOMAIN_DB
from tests.conftest import EMPRESA_A, EMPRESA_B

CATALOGO = [
    {"grupo_id": 1, "grupo": "Tiro ao Prato",
     "modalidades": [{"id": 1, "nome": "Trap Americano"}, {"id": 2, "nome": "Skeet"}]},
    {"grupo_id": 4, "grupo": "Tiro de Precisão",
     "modalidades": [{"id": 30, "nome": "Saque Rápido"}, {"id": 31, "nome": "Pistola"}]},
]


def test_espelha_o_catalogo_inteiro(banco):
    saida = motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    assert saida["novas"] == 4
    assert saida["atualizadas"] == 0
    assert saida["desativadas"] == 0
    assert len(motor_modalidades.listar(EMPRESA_A)) == 4


def test_sincronizar_de_novo_atualiza_em_vez_de_duplicar(banco):
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)
    saida = motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    assert saida["novas"] == 0
    assert saida["atualizadas"] == 4
    assert len(motor_modalidades.listar(EMPRESA_A)) == 4


def test_modalidade_que_sai_do_catalogo_e_desativada_e_nao_apagada(banco):
    """Pode haver resultado antigo mencionando aquela modalidade --
    apagar deixaria a tela sem como explicar de onde veio o texto."""
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    menor = [dict(CATALOGO[0])]
    menor[0]["modalidades"] = [{"id": 1, "nome": "Trap Americano"}]
    saida = motor_modalidades.salvar_catalogo(EMPRESA_A, menor)

    assert saida["desativadas"] == 3
    assert len(motor_modalidades.listar(EMPRESA_A)) == 1
    assert len(motor_modalidades.listar(EMPRESA_A, somente_ativas=False)) == 4


def test_modalidade_volta_a_ficar_ativa_se_reaparecer(banco):
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)
    motor_modalidades.salvar_catalogo(EMPRESA_A, [])
    assert motor_modalidades.listar(EMPRESA_A) == []

    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)
    assert len(motor_modalidades.listar(EMPRESA_A)) == 4


def test_catalogo_de_uma_empresa_nao_aparece_na_outra(banco):
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    assert len(motor_modalidades.listar(EMPRESA_A)) == 4
    assert motor_modalidades.listar(EMPRESA_B) == []
    assert motor_modalidades.agrupado(EMPRESA_B)["total"] == 0


def test_busca_nao_atravessa_a_empresa(banco):
    """A busca monta um OR de duas colunas. Sem parênteses em volta dele,
    o OR passaria por cima do filtro de empresa."""
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    assert motor_modalidades.listar(EMPRESA_B, busca="Skeet") == []
    assert len(motor_modalidades.listar(EMPRESA_A, busca="Skeet")) == 1


def test_nomes_nao_repete_modalidade_de_grupos_diferentes(banco):
    """"Pistola" existe em vários grupos do clube real. Repetida três
    vezes na lista de sugestões, só atrapalha quem está digitando."""
    catalogo = CATALOGO + [
        {"grupo_id": 8, "grupo": "Time Plus",
         "modalidades": [{"id": 90, "nome": "Pistola"}]},
    ]
    motor_modalidades.salvar_catalogo(EMPRESA_A, catalogo)

    nomes = motor_modalidades.nomes(EMPRESA_A)

    assert nomes.count("Pistola") == 1
    assert len(nomes) == len(set(nomes))


def test_agrupado_devolve_a_forma_que_a_tela_desenha(banco):
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    saida = motor_modalidades.agrupado(EMPRESA_A)

    assert saida["total"] == 4
    assert {g["grupo"] for g in saida["grupos"]} == {"Tiro ao Prato", "Tiro de Precisão"}
    assert saida["sincronizado_em"]


def test_rota_do_painel_entrega_o_catalogo(banco, painel):
    motor_modalidades.salvar_catalogo(EMPRESA_A, CATALOGO)

    dados = painel.get("/api/modalidades").get_json()

    assert dados["total"] == 4
    assert any(g["grupo"] == "Tiro ao Prato" for g in dados["grupos"])


def test_rota_do_painel_nao_mostra_catalogo_de_outra_empresa(banco, painel):
    motor_modalidades.salvar_catalogo(EMPRESA_B, CATALOGO)

    dados = painel.get("/api/modalidades").get_json()

    assert dados["total"] == 0
    assert "Trap Americano" not in str(dados)


def test_grupo_sem_nome_ganha_rotulo(banco):
    """O clube tem um grupo com nome vazio (id 1000, onde ficam as
    modalidades criadas por eles). Sem rótulo, a tela mostraria um
    cabeçalho em branco com 36 itens embaixo."""
    from integracoes.shooting_house import listar_modalidades

    # A conversão acontece em listar_modalidades, antes de chegar aqui.
    # Este teste exercita o caminho simulado, que é o que a suíte alcança.
    grupos = listar_modalidades()
    assert all((g["grupo"] or "").strip() for g in grupos)
