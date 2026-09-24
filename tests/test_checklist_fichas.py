"""Troca das listas de documento pelas fichas do clube (2026-09-24).

O que não pode falhar é o que acontece com processo que JÁ ESTÁ
andando: um item antigo com documento marcado não pode sumir apagado --
a marcação ficaria apontando para item inexistente. E a troca roda em
produção, onde o banco é de verdade, então a simulação não pode gravar
nada e rodar duas vezes não pode desfazer a primeira.
"""
from core.conexao import conectar_admin
from core.db.revisar_checklist_cac import CHECKLISTS, revisar
from tests.conftest import AGORA, EMPRESA_A, EMPRESA_B


def _item_antigo_marcado():
    """A transferência da EMPRESA_A (SER-000001, service_key
    transferencia_arma) com um item antigo que tem o DOC-000001 marcado
    no PRO-000001."""
    con = conectar_admin()
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
        "grupo, item, ordem, ativo) VALUES ('DEX-000001', ?, 'SER-000001', NULL, "
        "'Item antigo marcado', 1, 'Sim')", (EMPRESA_A,),
    )
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
        "grupo, item, ordem, ativo) VALUES ('DEX-000002', ?, 'SER-000001', NULL, "
        "'Item antigo sem nada', 2, 'Sim')", (EMPRESA_A,),
    )
    con.execute(
        "INSERT INTO documento_checklist (documento_checklist_id, empresa_id, processo_id, "
        "documento_exigido_id, documento_id, marcado_em, marcado_por) "
        "VALUES ('DCK-000001', ?, 'PRO-000001', 'DEX-000001', 'DOC-000001', ?, 'Teste')",
        (EMPRESA_A, AGORA),
    )
    con.commit()
    con.close()


def _itens_ativos(servico_id):
    con = conectar_admin()
    linhas = con.execute(
        "SELECT grupo, item FROM documento_exigido WHERE servico_id = ? AND ativo = 'Sim' "
        "ORDER BY ordem", (servico_id,),
    ).fetchall()
    con.close()
    return [(l["grupo"], l["item"]) for l in linhas]


def test_simulacao_nao_grava_nada(banco):
    _item_antigo_marcado()
    saida = revisar(EMPRESA_A, aplicar=False)

    assert saida["aplicado"] is False
    con = conectar_admin()
    servicos = con.execute("SELECT COUNT(*) FROM servico WHERE empresa_id = ?", (EMPRESA_A,)).fetchone()[0]
    con.close()
    assert servicos == 1
    assert _itens_ativos("SER-000001") == [(None, "Item antigo marcado"), (None, "Item antigo sem nada")]


def test_item_marcado_e_desativado_nunca_apagado(banco):
    _item_antigo_marcado()
    saida = revisar(EMPRESA_A)

    transferencia = next(s for s in saida["servicos"] if s["chave"] == "transferencia_arma")
    assert (transferencia["desativados"], transferencia["apagados"]) == (1, 1)
    assert transferencia["processos_afetados"] == ["PRO-000001"]

    con = conectar_admin()
    antigo = con.execute(
        "SELECT ativo FROM documento_exigido WHERE documento_exigido_id = 'DEX-000001'"
    ).fetchone()
    marca = con.execute("SELECT 1 FROM documento_checklist WHERE documento_checklist_id = 'DCK-000001'").fetchone()
    sem_nada = con.execute(
        "SELECT 1 FROM documento_exigido WHERE documento_exigido_id = 'DEX-000002'"
    ).fetchone()
    con.close()
    assert antigo["ativo"] == "Não"
    assert marca is not None
    assert sem_nada is None

    assert _itens_ativos("SER-000001") == CHECKLISTS["transferencia_arma"][2]


def test_cria_servicos_novos_e_renomeia(banco):
    revisar(EMPRESA_A)
    con = conectar_admin()
    nomes = {
        l["service_key"]: l["nome_servico"]
        for l in con.execute("SELECT service_key, nome_servico FROM servico WHERE empresa_id = ?", (EMPRESA_A,))
    }
    outra = con.execute("SELECT COUNT(*) FROM servico WHERE empresa_id = ?", (EMPRESA_B,)).fetchone()[0]
    con.close()
    assert nomes["transferencia_arma"] == "Transferência de CAC para CAC"
    assert nomes["progressao_nivel_3"] == "Progressão de Nível III"
    assert nomes["transferencia_acervo"] == "Transferência entre Acervos"
    assert nomes["craf"] == "Renovação de CRAF"
    # A outra empresa não é tocada.
    assert outra == 1


def test_certidao_com_quantidade_vira_um_item_por_certidao():
    itens = [i for _, i in CHECKLISTS["primeiro_cr"][2]]
    assert [i for i in itens if i.startswith("Certidão Federal")] == [
        "Certidão Federal — 1 de 3", "Certidão Federal — 2 de 3", "Certidão Federal — 3 de 3",
    ]
    assert "Certidão Militar" in itens


def test_rodar_duas_vezes_nao_mexe_em_nada(banco):
    revisar(EMPRESA_A)
    segunda = revisar(EMPRESA_A)
    assert all(s["igual"] for s in segunda["servicos"])
