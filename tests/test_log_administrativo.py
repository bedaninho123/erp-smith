"""Log administrativo (core/motor_log_administrativo.py): mudança de
papel, ativo e permissão de usuário, e de configuração da empresa,
precisa deixar rastro de quem mudou, quando e qual era o valor antes --
achado na auditoria de riscos de 2026-07-30 (antes, essas mudanças eram
silenciosas).
"""
from core.configuracoes import atualizar_configuracao
from core.motor_log_administrativo import listar
from core.motor_usuarios import atualizar_ativo, atualizar_papel, atualizar_permissoes


def test_troca_de_papel_fica_no_log(banco):
    atualizar_papel("EMP-000001", "USR-000003", "Gestor", alterado_por="Felipe")

    entradas = listar("EMP-000001")
    entrada = next(e for e in entradas if e["tipo_evento"] == "papel_alterado")
    assert entrada["alvo"] == "USR-000003"
    assert entrada["valor_anterior"] == "Atendente"
    assert entrada["valor_novo"] == "Gestor"
    assert entrada["criado_por"] == "Felipe"


def test_desativar_usuario_fica_no_log(banco):
    atualizar_ativo("EMP-000001", "USR-000003", "Não", alterado_por="Felipe")

    entrada = next(e for e in listar("EMP-000001") if e["tipo_evento"] == "ativo_alterado")
    assert entrada["valor_anterior"] == "Sim"
    assert entrada["valor_novo"] == "Não"


def test_permissao_alterada_fica_no_log(banco):
    atualizar_permissoes("EMP-000001", "USR-000003", {"casos": "Não"}, alterado_por="Felipe")

    entrada = next(e for e in listar("EMP-000001") if e["tipo_evento"] == "permissao_alterada")
    assert entrada["alvo"] == "USR-000003"
    assert "casos" in entrada["descricao"]
    assert entrada["valor_anterior"] == "Sim"  # padrão quando não havia linha
    assert entrada["valor_novo"] == "Não"


def test_configuracao_alterada_fica_no_log(banco):
    con_id = _criar_configuracao_de_teste("EMP-000001")
    atualizar_configuracao("EMP-000001", con_id, "Novo valor", "Sim", alterado_por="Felipe")

    entrada = next(e for e in listar("EMP-000001") if e["tipo_evento"] == "configuracao_alterada")
    assert entrada["alvo"] == con_id
    assert entrada["criado_por"] == "Felipe"


def test_nao_muda_nada_nao_gera_log(banco):
    # Salvar sem alterar o valor de verdade não deveria poluir o log --
    # só o que realmente mudou vira rastro.
    atualizar_papel("EMP-000001", "USR-000003", "Atendente")
    assert not listar("EMP-000001")


def test_log_de_uma_empresa_nao_aparece_na_outra(banco):
    atualizar_papel("EMP-000001", "USR-000003", "Gestor")
    atualizar_ativo("EMP-000002", "USR-000002", "Não")

    log_a = listar("EMP-000001")
    log_b = listar("EMP-000002")
    assert all(e["empresa_id"] == "EMP-000001" for e in log_a)
    assert all(e["empresa_id"] == "EMP-000002" for e in log_b)
    assert len(log_a) == 1
    assert len(log_b) == 1


# --------------------------------------------------------------------
# Tela Auditoria (2026-08-27): o registro passou a ser lido por gente
# --------------------------------------------------------------------

def test_atendente_nao_ve_a_auditoria(banco, painel_atendente):
    """Área administrativa, como Configurações -- fica fora do catálogo
    de permissões de propósito. Um Atendente poder ver (e ainda mais
    ganhar/perder essa visão num toggle) esvaziaria o sentido do
    registro, já que é o comportamento dele que está sendo registrado."""
    assert painel_atendente.get("/api/auditoria").status_code == 403


def test_gestor_le_a_auditoria_com_nome_de_gente(banco, painel):
    atualizar_papel("EMP-000001", "USR-000003", "Gestor", alterado_por="Felipe")

    dados = painel.get("/api/auditoria").get_json()

    registro = next(r for r in dados["registros"] if r["tipo_evento"] == "papel_alterado")
    assert registro["alvo"] == "USR-000003"
    # O ID continua sendo o dado; o nome é tradução de exibição.
    assert registro["alvo_nome"] == "Atendente Teste"
    assert "papel_alterado" in dados["tipos"]


def test_auditoria_nao_mostra_registro_de_outra_empresa(banco, painel):
    atualizar_ativo("EMP-000002", "USR-000002", "Não", alterado_por="Gestor da Outra")

    dados = painel.get("/api/auditoria").get_json()

    assert dados["registros"] == []


def test_busca_nao_atravessa_a_empresa(banco, painel):
    """A busca monta um OR de três colunas. Sem parênteses em volta desse
    OR ele passaria por cima do filtro de empresa -- mesmo erro que já
    aconteceu uma vez na busca de clientes."""
    atualizar_ativo("EMP-000002", "USR-000002", "Não", alterado_por="Gestor da Outra")
    atualizar_papel("EMP-000001", "USR-000003", "Gestor", alterado_por="Felipe")

    corpo = painel.get("/api/auditoria?busca=Gestor da Outra").get_data(as_text=True)

    assert "Gestor da Outra" not in corpo


def test_conta_so_os_acessos_negados_e_so_dessa_empresa(banco):
    from core.conexao import conectar
    from core.motor_log_administrativo import contar_acessos_negados, registrar

    def _acesso(empresa_id: str, resultado: str) -> None:
        con = conectar(empresa_id)
        registrar(con, empresa_id, "ACESSO_DADO_SENSIVEL", "CLI-000001",
                  "CONSULTA_HABITUALIDADE por Email", None, resultado, "sistema/atendimento")
        con.commit()
        con.close()

    _acesso("EMP-000001", "negado: CPF não confere")
    _acesso("EMP-000001", "negado: CPF não confere")
    _acesso("EMP-000001", "liberado")
    _acesso("EMP-000002", "negado: CPF não confere")

    assert contar_acessos_negados("EMP-000001", dias=7) == 2
    assert contar_acessos_negados("EMP-000002", dias=7) == 1


def _criar_configuracao_de_teste(empresa_id: str) -> str:
    # tests/conftest.py não semeia a tabela configuracoes -- este teste
    # cria a própria linha, isolado dos outros.
    from core.conexao import conectar
    con = conectar(empresa_id)
    try:
        con.execute(
            "INSERT INTO configuracoes (config_id, empresa_id, chave, valor, categoria, ativo) "
            "VALUES ('CFG-TESTE', ?, 'chave_teste', 'valor original', 'Teste', 'Sim')",
            (empresa_id,),
        )
        con.commit()
        return "CFG-TESTE"
    finally:
        con.close()
