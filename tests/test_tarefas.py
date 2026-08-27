"""Tarefas e prazos: isolamento entre empresas e as regras do motor.

Duas famílias de teste, por dois riscos diferentes:

1. **Vazamento entre empresas.** Tarefa carrega nome de cliente e título
   de caso -- listar sem filtro mostraria o cliente de um despachante
   para o outro, e criar sem filtro penduraria uma tarefa no caso alheio.

2. **Regra que a tela não pode reimplementar.** Data de conclusão,
   "atrasada", e o cliente_id vir do caso e não de quem chamou. Se
   qualquer uma dessas migrar pro webapp/, o próximo canal (Portal, um
   app de celular) vai errar sozinho.
"""
from datetime import date, timedelta

import pytest

from core.conexao import conectar_admin
from core.motor_tarefas import (
    atualizar_tarefa, concluir_tarefa, contar_tarefas, criar_tarefa,
    listar_tarefas, normalizar_prazo,
)
from tests.conftest import EMPRESA_A, EMPRESA_B


def _dia(deslocamento: int) -> str:
    return (date.today() + timedelta(days=deslocamento)).isoformat()


# --------------------------------------------------------------------
# Isolamento entre empresas
# --------------------------------------------------------------------

def test_nao_cria_tarefa_em_caso_de_outra_empresa(banco):
    """CAS-000003 é da EMPRESA_B. Sem o filtro de empresa no SELECT do
    caso, a tarefa nasceria com empresa_id de A apontando pro caso de B
    -- dado das duas empresas amarrado na mesma linha."""
    with pytest.raises(ValueError, match="Caso não encontrado"):
        criar_tarefa(EMPRESA_A, "CAS-000003", tipo="Cobrar documento")


def test_lista_nao_mostra_tarefa_de_outra_empresa(banco):
    criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Ligar para o cliente")
    criar_tarefa(EMPRESA_B, "CAS-000003", tipo="Tarefa da Carla")

    da_empresa_a = listar_tarefas(EMPRESA_A)

    assert [t["tipo"] for t in da_empresa_a] == ["Ligar para o cliente"]
    assert not any("Carla" in (t["cliente_nome"] or "") for t in da_empresa_a)


def test_nao_atualiza_tarefa_de_outra_empresa(banco):
    alheia = criar_tarefa(EMPRESA_B, "CAS-000003", tipo="Tarefa da Carla")

    with pytest.raises(ValueError, match="não encontrada"):
        atualizar_tarefa(
            EMPRESA_A, alheia, tipo="Sequestrada", descricao=None,
            responsavel_id=None, prazo=None, prioridade="Normal",
            status="Cancelada", observacoes=None,
        )

    con = conectar_admin()
    tipo = con.execute(
        "SELECT tipo FROM tarefas WHERE tarefa_id = ?", (alheia,)
    ).fetchone()[0]
    con.close()
    assert tipo == "Tarefa da Carla"


def test_responsavel_de_outra_empresa_e_recusado(banco):
    """USR-000002 é da EMPRESA_B. Aceitar seria pendurar o nome de um
    funcionário do outro despachante na fila deste."""
    with pytest.raises(ValueError, match="não encontrado ou inativo"):
        criar_tarefa(
            EMPRESA_A, "CAS-000001", tipo="Protocolar", responsavel_id="USR-000002"
        )


def test_rota_do_painel_nao_lista_tarefa_de_outra_empresa(banco, painel):
    criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Conferir documento")
    criar_tarefa(EMPRESA_B, "CAS-000003", tipo="Tarefa da Carla")

    corpo = painel.get("/api/tarefas").get_data(as_text=True)

    assert "Conferir documento" in corpo
    assert "Tarefa da Carla" not in corpo
    assert "Carla Outra" not in corpo


def test_rota_do_painel_nao_conclui_tarefa_de_outra_empresa(banco, painel):
    alheia = criar_tarefa(EMPRESA_B, "CAS-000003", tipo="Tarefa da Carla")

    resposta = painel.post(f"/api/tarefas/{alheia}/concluir")

    assert resposta.status_code == 400
    con = conectar_admin()
    status = con.execute(
        "SELECT status FROM tarefas WHERE tarefa_id = ?", (alheia,)
    ).fetchone()[0]
    con.close()
    assert status == "Pendente"


def test_seletor_de_caso_da_tela_nao_oferece_caso_alheio(banco, painel):
    """O <select> de "nova tarefa" é preenchido por esta rota. Um caso da
    outra empresa ali seria vazamento antes de qualquer clique."""
    dados = painel.get("/api/tarefas").get_json()

    ids = [c["caso_id"] for c in dados["casos_abertos"]]
    assert "CAS-000001" in ids
    assert "CAS-000003" not in ids


# --------------------------------------------------------------------
# Regras do motor
# --------------------------------------------------------------------

def test_cliente_vem_do_caso_e_nao_de_quem_chamou(banco):
    tarefa_id = criar_tarefa(EMPRESA_A, "CAS-000002", tipo="Cobrar documento")

    con = conectar_admin()
    linha = con.execute(
        "SELECT cliente_id, status FROM tarefas WHERE tarefa_id = ?", (tarefa_id,)
    ).fetchone()
    con.close()

    # CAS-000002 é do Bruno (CLI-000002) -- ver tests/conftest.py.
    assert linha["cliente_id"] == "CLI-000002"
    assert linha["status"] == "Pendente"


def test_processo_de_outro_caso_e_recusado(banco):
    """PRO-000002 é do caso do Bruno; CAS-000001 é da Ana. Os dois são da
    MESMA empresa -- é justamente o cruzamento que o filtro de empresa
    não pega."""
    with pytest.raises(ValueError, match="não pertence a este caso"):
        criar_tarefa(
            EMPRESA_A, "CAS-000001", tipo="Protocolar", processo_id="PRO-000002"
        )


def test_concluir_carimba_a_data_e_reabrir_apaga(banco):
    tarefa_id = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Protocolar")

    concluir_tarefa(EMPRESA_A, tarefa_id)
    con = conectar_admin()
    concluida = con.execute(
        "SELECT status, data_conclusao FROM tarefas WHERE tarefa_id = ?", (tarefa_id,)
    ).fetchone()
    con.close()
    assert concluida["status"] == "Concluída"
    assert concluida["data_conclusao"]

    atualizar_tarefa(
        EMPRESA_A, tarefa_id, tipo="Protocolar", descricao=None, responsavel_id=None,
        prazo=None, prioridade="Normal", status="Pendente", observacoes=None,
    )
    con = conectar_admin()
    reaberta = con.execute(
        "SELECT status, data_conclusao FROM tarefas WHERE tarefa_id = ?", (tarefa_id,)
    ).fetchone()
    con.close()
    assert reaberta["status"] == "Pendente"
    assert reaberta["data_conclusao"] is None, (
        "tarefa reaberta continuou 'concluída em' uma data que já não significa nada"
    )


def test_atrasada_so_vale_pra_tarefa_em_aberto(banco):
    vencida = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Cobrar documento", prazo=_dia(-3))
    feita = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Consultar andamento", prazo=_dia(-3))
    concluir_tarefa(EMPRESA_A, feita)

    por_id = {t["tarefa_id"]: t for t in listar_tarefas(EMPRESA_A)}

    assert por_id[vencida]["atrasada"] is True
    assert por_id[feita]["atrasada"] is False, (
        "trabalho feito ontem com prazo de anteontem não é pendência atrasada"
    )
    assert [t["tarefa_id"] for t in listar_tarefas(EMPRESA_A, vencimento="atrasadas")] == [vencida]


def test_prazo_em_iso_completo_nao_some_do_filtro_de_hoje(banco):
    """As linhas migradas da planilha guardam '...T00:00:00Z'. Comparado
    como texto, isso é MAIOR que '2026-08-27' -- a tarefa não apareceria
    nem em 'hoje' nem em 'atrasadas', e ninguém notaria a ausência."""
    tarefa_id = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Ligar para o cliente")
    con = conectar_admin()
    con.execute(
        "UPDATE tarefas SET prazo = ? WHERE tarefa_id = ?",
        (f"{_dia(0)}T00:00:00Z", tarefa_id),
    )
    con.commit()
    con.close()

    de_hoje = listar_tarefas(EMPRESA_A, vencimento="hoje")

    assert [t["tarefa_id"] for t in de_hoje] == [tarefa_id]
    assert de_hoje[0]["prazo"] == _dia(0), "o prazo devia sair da API já como dia"
    assert de_hoje[0]["vence_hoje"] is True


def test_contagem_concorda_com_a_lista(banco):
    """Uma segunda implementação da regra de atraso divergiria da lista
    mais cedo ou mais tarde -- e o painel mostraria 3 atrasadas numa
    lista com 2 linhas."""
    criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Cobrar documento", prazo=_dia(-1))
    criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Protocolar", prazo=_dia(0))
    criar_tarefa(EMPRESA_A, "CAS-000002", tipo="Agendar", prazo=_dia(5))
    feita = criar_tarefa(EMPRESA_A, "CAS-000002", tipo="Conferir documento", prazo=_dia(-9))
    concluir_tarefa(EMPRESA_A, feita)

    contagem = contar_tarefas(EMPRESA_A)

    assert contagem["abertas"] == 3
    assert contagem["atrasadas"] == len(listar_tarefas(EMPRESA_A, vencimento="atrasadas")) == 1
    assert contagem["hoje"] == len(listar_tarefas(EMPRESA_A, vencimento="hoje")) == 1


def test_prioridade_e_status_fora_da_lista_sao_recusados(banco):
    with pytest.raises(ValueError, match="Prioridade inválida"):
        criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Protocolar", prioridade="Urgentíssima")

    tarefa_id = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Protocolar")
    with pytest.raises(ValueError, match="Status inválido"):
        atualizar_tarefa(
            EMPRESA_A, tarefa_id, tipo="Protocolar", descricao=None, responsavel_id=None,
            prazo=None, prioridade="Normal", status="Feita", observacoes=None,
        )


def test_prazo_em_formato_brasileiro_e_recusado(banco):
    """31/08/2026 cortado em 10 caracteres continuaria "válido" e entraria
    no banco como lixo que nunca casa com data nenhuma."""
    with pytest.raises(ValueError, match="Prazo inválido"):
        normalizar_prazo("31/08/2026")


def test_mudanca_de_status_entra_no_historico_do_caso(banco):
    """O histórico do Caso é o que reconstitui o atendimento depois. Uma
    tarefa concluída sem rastro ali deixa um buraco na linha do tempo."""
    tarefa_id = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Protocolar",
                             criado_por="Gestor Teste")
    concluir_tarefa(EMPRESA_A, tarefa_id, alterado_por="Gestor Teste")

    con = conectar_admin()
    eventos = [
        dict(r) for r in con.execute(
            "SELECT tipo_evento, descricao FROM historico WHERE caso_id = ? "
            "ORDER BY historico_id", ("CAS-000001",),
        ).fetchall()
    ]
    con.close()

    textos = [e["descricao"] for e in eventos]
    assert any(tarefa_id in t and "criada" in t for t in textos)
    assert any(tarefa_id in t and "Concluída" in t for t in textos)
    # 'outro' é o único tipo honesto: os outros quatro do CHECK falam do
    # Caso, e um 'mudanca_status' aqui seria lido como o status DO CASO.
    assert {e["tipo_evento"] for e in eventos} == {"outro"}
