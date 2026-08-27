"""Abrir caso à mão pelo painel.

Até 2026-08-27 todo caso nascia da IA ou da migração. O caminho mais
óbvio de um despachante -- o cliente ligou -- não existia.

O que os testes protegem: que a rota nova usa o MESMO `criar_caso` do
orquestrador (mesmo histórico, mesmas validações) e que ela não afrouxou
nenhuma das travas de empresa que o resto do Core tem.
"""
import pytest

from core.conexao import conectar_admin
from core.motor_casos import criar_caso
from tests.conftest import EMPRESA_A, EMPRESA_B


def _abrir(painel, **campos):
    corpo = {
        "cliente_id": "CLI-000001",
        "titulo": "Renovação de CR",
        "categoria": "Regularização documental",
    }
    corpo.update(campos)
    return painel.post("/api/casos", json=corpo)


def test_abre_caso_pelo_painel(banco, painel):
    resposta = _abrir(painel)

    assert resposta.status_code == 200
    caso_id = resposta.get_json()["caso_id"]

    con = conectar_admin()
    caso = con.execute("SELECT * FROM caso WHERE caso_id = ?", (caso_id,)).fetchone()
    con.close()
    assert caso["titulo"] == "Renovação de CR"
    assert caso["status"] == "Aberto"
    assert caso["origem"] == "Painel"
    # Quem abriu fica registrado -- é o que separa o caso aberto à mão do
    # que a IA abriu sozinha.
    assert caso["criado_por"] == "Gestor Teste"


def test_caso_aberto_a_mao_entra_no_historico(banco, painel):
    """Mesmo caminho do orquestrador significa mesmo histórico. Um caso
    sem evento de criação seria um buraco na linha do tempo."""
    caso_id = _abrir(painel).get_json()["caso_id"]

    con = conectar_admin()
    eventos = con.execute(
        "SELECT tipo_evento, criado_por FROM historico WHERE caso_id = ?", (caso_id,)
    ).fetchall()
    con.close()

    assert [e["tipo_evento"] for e in eventos] == ["criacao"]
    assert eventos[0]["criado_por"] == "Gestor Teste"


def test_nao_abre_caso_para_cliente_de_outra_empresa(banco, painel):
    """CLI-000003 é da EMPRESA_B. Sem a trava, o caso nasceria amarrando
    dado de duas empresas na mesma linha."""
    resposta = _abrir(painel, cliente_id="CLI-000003")

    assert resposta.status_code == 400
    con = conectar_admin()
    total = con.execute(
        "SELECT COUNT(*) FROM caso WHERE cliente_id = 'CLI-000003'"
    ).fetchone()[0]
    con.close()
    assert total == 1  # só o que o fixture já trazia


def test_responsavel_de_outra_empresa_e_recusado(banco, painel):
    resposta = _abrir(painel, responsavel_id="USR-000002")  # da EMPRESA_B

    assert resposta.status_code == 400


def test_titulo_e_categoria_sao_obrigatorios(banco, painel):
    assert _abrir(painel, titulo="   ").status_code == 400
    assert _abrir(painel, categoria="").status_code == 400


def test_prioridade_fora_da_lista_e_recusada(banco, painel):
    assert _abrir(painel, prioridade="Urgentíssima").status_code == 400


def test_canal_fora_da_lista_e_recusado(banco, painel):
    """`canal_origem` alimenta o gráfico 'por onde o cliente chega'.
    Texto livre ali criaria uma fatia nova a cada digitação diferente."""
    assert _abrir(painel, canal_origem="Pombo-correio").status_code == 400


def test_presencial_e_telefone_sao_canais_validos(banco, painel):
    """São justamente os que a IA nunca usa -- e os mais comuns no caso
    aberto à mão."""
    assert _abrir(painel, canal_origem="Presencial").status_code == 200
    assert _abrir(painel, canal_origem="Telefone").status_code == 200


def test_opcoes_do_formulario_nao_vazam_entre_empresas(banco, painel):
    dados = painel.get("/api/casos/novo").get_json()

    nomes = [c["nome"] for c in dados["clientes"]]
    assert "Ana Teste" in nomes
    assert "Carla Outra" not in nomes
    assert all(u["nome"] != "Atendente da Outra" for u in dados["usuarios"])


def test_categorias_vem_do_catalogo_de_servicos(banco, painel):
    """Uma lista fixa aqui divergiria do catálogo na primeira vez que
    alguém cadastrasse um serviço novo."""
    dados = painel.get("/api/casos/novo").get_json()

    assert dados["categorias"] == ["Transferência"]  # o serviço do fixture


def test_atendente_sem_a_funcao_nao_abre_caso(banco, painel_atendente):
    from core.motor_usuarios import atualizar_permissoes

    atualizar_permissoes(EMPRESA_A, "USR-000003", {"casos": "Não"})

    assert _abrir(painel_atendente).status_code == 403
    assert painel_atendente.get("/api/casos/novo").status_code == 403


def test_prioridade_do_caso_usa_a_mesma_escala_da_tarefa(banco):
    """As duas aparecem lado a lado na mesma tela. Escalas diferentes
    fariam a pessoa traduzir de cabeça."""
    from core.motor_casos import PRIORIDADES_VALIDAS as caso
    from core.motor_tarefas import PRIORIDADES_VALIDAS as tarefa

    assert caso == tarefa


def test_criar_caso_direto_no_motor_continua_funcionando(banco):
    """O orquestrador chama sem prioridade nem responsável -- os padrões
    não podem ter mudado junto."""
    caso_id = criar_caso(EMPRESA_A, "CLI-000001", "Dúvida", "Transferência")

    con = conectar_admin()
    caso = con.execute("SELECT * FROM caso WHERE caso_id = ?", (caso_id,)).fetchone()
    con.close()
    assert caso["prioridade"] == "Normal"
    assert caso["responsavel_id"] is None
    assert caso["origem"] == "Atendimento"
