"""Permissões granulares por função (core/motor_usuarios.py:
tem_permissao/listar_permissoes/atualizar_permissoes), só valem para
usuario.papel = 'Atendente' -- Gestor tem acesso total e intocável.

Regra central, testada explicitamente: ausência de linha em
usuario_permissao significa PERMITIDO. A tabela só ganha linha quando o
Gestor desliga ou religa algo pela tela de Usuários.
"""
from core.motor_usuarios import atualizar_permissoes


def test_atendente_sem_linha_acessa_normalmente(painel_atendente):
    # USR-000003 nunca teve usuario_permissao tocada -- toda função
    # operacional continua acessível por padrão.
    assert painel_atendente.get("/api/casos").status_code == 200
    assert painel_atendente.get("/api/clientes/lista").status_code == 200
    assert painel_atendente.get("/api/status").status_code == 200
    assert painel_atendente.get("/api/pendentes").status_code == 200
    assert painel_atendente.get("/api/documentos-pendentes").status_code == 200


def test_desligar_uma_funcao_bloqueia_so_ela(painel, painel_atendente):
    atualizar_permissoes("EMP-000001", "USR-000003", {"casos": "Não"})

    bloqueado = painel_atendente.get("/api/casos")
    assert bloqueado.status_code == 403

    # Clientes nunca foi tocado -- continua permitido.
    ainda_permitido = painel_atendente.get("/api/clientes/lista")
    assert ainda_permitido.status_code == 200


def test_religar_a_funcao_libera_de_novo(painel_atendente):
    atualizar_permissoes("EMP-000001", "USR-000003", {"clientes": "Não"})
    assert painel_atendente.get("/api/clientes/lista").status_code == 403

    atualizar_permissoes("EMP-000001", "USR-000003", {"clientes": "Sim"})
    assert painel_atendente.get("/api/clientes/lista").status_code == 200


def test_listar_campeonatos_aceita_campeonatos_ou_resultados(painel_atendente):
    # GET /api/campeonatos é pré-requisito de duas telas: a lista da
    # própria tela Campeonatos e o seletor de campeonato dentro de
    # Resultados. Achado testando como a Ana no navegador: travar só em
    # "campeonatos" quebrava o seletor de quem tem só "resultados".
    atualizar_permissoes("EMP-000001", "USR-000003", {"campeonatos": "Não"})

    ainda_ve_a_lista = painel_atendente.get("/api/campeonatos")
    assert ainda_ve_a_lista.status_code == 200

    # Mas continua sem poder criar/editar campeonato -- isso é
    # exclusivo da função "campeonatos", não vaza pela lista.
    assert painel_atendente.post(
        "/api/campeonatos", json={"nome": "X", "data_inicio": "2026-01-01"}
    ).status_code == 403

    # Desligando as duas, a lista também fecha.
    atualizar_permissoes("EMP-000001", "USR-000003", {"resultados": "Não"})
    assert painel_atendente.get("/api/campeonatos").status_code == 403


def test_gestor_sempre_passa_mesmo_com_tudo_desligado(painel):
    # USR-000001 é Gestor -- o decorator nem chega a consultar a tabela,
    # mas o teste confere o resultado, não a implementação.
    atualizar_permissoes("EMP-000001", "USR-000001", {"casos": "Não"})
    assert painel.get("/api/casos").status_code == 200


def test_atualizar_permissoes_funcao_invalida():
    import pytest
    with pytest.raises(ValueError):
        atualizar_permissoes("EMP-000001", "USR-000003", {"voar": "Sim"})


def test_atualizar_permissoes_valor_invalido():
    import pytest
    with pytest.raises(ValueError):
        atualizar_permissoes("EMP-000001", "USR-000003", {"casos": "Talvez"})


def test_atendente_nao_acessa_rotas_de_permissao(painel_atendente):
    assert painel_atendente.get("/api/usuarios/USR-000003/permissoes").status_code == 403
    resposta = painel_atendente.post(
        "/api/usuarios/USR-000003/permissoes", json={"casos": "Não"}
    )
    assert resposta.status_code == 403


def test_gestor_le_e_atualiza_permissoes_pela_rota(painel):
    listagem = painel.get("/api/usuarios/USR-000003/permissoes").get_json()
    # Lista escrita à mão de propósito, não lida de FUNCOES_VALIDAS:
    # comparar o catálogo com ele mesmo não provaria nada. Assim, mexer
    # no catálogo quebra este teste e obriga uma decisão consciente --
    # uma função que some sem querer é acesso perdido em silêncio, uma
    # que aparece sem querer é acesso concedido em silêncio.
    assert {p["funcao"] for p in listagem} == {
        "atendimentos", "casos", "tarefas", "clientes", "aprovacoes_pendentes",
        "documentos_aprovar", "campeonatos", "resultados", "habitualidade",
        "testar_pipeline", "status_projeto",
    }
    assert all(p["ativo"] == "Sim" for p in listagem)

    resposta = painel.post(
        "/api/usuarios/USR-000003/permissoes", json={"campeonatos": "Não"}
    )
    assert resposta.status_code == 200

    listagem2 = painel.get("/api/usuarios/USR-000003/permissoes").get_json()
    campeonatos = next(p for p in listagem2 if p["funcao"] == "campeonatos")
    assert campeonatos["ativo"] == "Não"


def test_permissao_de_uma_empresa_nao_afeta_a_outra(banco):
    # USR-000002 é da EMPRESA_B (ver tests/conftest.py). Desligar uma
    # função para ele não pode existir/afetar USR-000003 (EMPRESA_A).
    atualizar_permissoes("EMP-000002", "USR-000002", {"casos": "Não"})

    from core.motor_usuarios import tem_permissao
    assert tem_permissao("EMP-000002", "USR-000002", "casos") is False
    assert tem_permissao("EMP-000001", "USR-000003", "casos") is True
