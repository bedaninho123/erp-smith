"""Tela inicial (/api/inicio): resumo do que precisa de atenção.

O risco desta rota é específico e vale teste próprio: ela é a única do
painel que junta dado de cinco telas diferentes, e o decorator
`funcao_required` libera se QUALQUER uma das funções bater. Ou seja, o
decorator sozinho não protege bloco nenhum -- quem protege é o `_pode()`
dentro da rota. Um bloco que perca essa checagem entrega a fila de outra
tela pra quem não deveria vê-la, e nada quebra.
"""
from core.motor_tarefas import criar_tarefa
from core.motor_usuarios import atualizar_permissoes
from tests.conftest import EMPRESA_A, EMPRESA_B


def test_gestor_recebe_todos_os_blocos(banco, painel):
    dados = painel.get("/api/inicio").get_json()

    assert set(dados) == {
        "tarefas", "aprovacoes_pendentes", "documentos_a_conferir",
        "conversas_abertas", "casos",
    }


def test_atendente_so_recebe_o_bloco_da_funcao_que_tem(banco, painel_atendente):
    """USR-000003 fica só com "casos". As outras quatro áreas não podem
    aparecer no resumo -- o decorator já deixou a rota passar por causa
    de "casos", então é o _pode() de cada bloco que decide aqui."""
    atualizar_permissoes(EMPRESA_A, "USR-000003", {
        "tarefas": "Não", "atendimentos": "Não",
        "aprovacoes_pendentes": "Não", "documentos_aprovar": "Não",
    })

    dados = painel_atendente.get("/api/inicio").get_json()

    assert set(dados) == {"casos"}


def test_atendente_sem_nenhuma_das_funcoes_nao_entra(banco, painel_atendente):
    atualizar_permissoes(EMPRESA_A, "USR-000003", {
        "casos": "Não", "tarefas": "Não", "atendimentos": "Não",
        "aprovacoes_pendentes": "Não", "documentos_aprovar": "Não",
    })

    assert painel_atendente.get("/api/inicio").status_code == 403


def test_resumo_nao_conta_dado_de_outra_empresa(banco, painel):
    criar_tarefa(EMPRESA_B, "CAS-000003", tipo="Tarefa da Carla", prazo="2020-01-01")

    dados = painel.get("/api/inicio").get_json()

    assert dados["tarefas"]["abertas"] == 0
    assert dados["tarefas"]["atrasadas"] == 0
    # A empresa A tem dois casos em aberto (Ana e Bruno), a B tem um.
    assert dados["casos"]["abertos"] == 2


def test_caso_parado_e_o_que_nao_tem_movimento_ha_uma_semana(banco, painel):
    """Os casos do fixture foram atualizados em 2026-07-28, muito antes
    de hoje -- então os dois entram como parados. O que este teste trava
    é o formato: contagem, lista curta e a régua de dias explícita, que
    é o que a tela escreve no título."""
    dados = painel.get("/api/inicio").get_json()

    assert dados["casos"]["dias_parado"] == 7
    assert dados["casos"]["parados"] == 2
    assert len(dados["casos"]["lista_parados"]) <= 5
    assert {c["caso_id"] for c in dados["casos"]["lista_parados"]} == {
        "CAS-000001", "CAS-000002",
    }
    assert "CAS-000003" not in str(dados)


def test_proximas_tarefas_vem_no_maximo_cinco_e_so_em_aberto(banco, painel):
    for i in range(7):
        criar_tarefa(EMPRESA_A, "CAS-000001", tipo=f"Tarefa {i}", prazo="2026-09-01")
    concluida = criar_tarefa(EMPRESA_A, "CAS-000001", tipo="Já feita", prazo="2020-01-01")
    from core.motor_tarefas import concluir_tarefa
    concluir_tarefa(EMPRESA_A, concluida)

    dados = painel.get("/api/inicio").get_json()

    assert dados["tarefas"]["abertas"] == 7
    assert len(dados["tarefas"]["proximas"]) == 5
    assert all(t["status"] != "Concluída" for t in dados["tarefas"]["proximas"])
