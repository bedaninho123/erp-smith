"""Papéis e permissões do painel (core/motor_usuarios.py): Gestor tem
acesso total, Atendente opera casos/clientes/documentos sem acesso
administrativo.

Cuidado ao estender este arquivo: campeonatos e resultados são domínio
(motor_ia/conexao.py anexa domain/clube_tiro/db/dominio_clube_tiro.db de
verdade quando ERP_DOMAIN_DB não está definido -- e não está aqui). O
decorator @gestor_required roda ANTES do corpo da rota, então o teste de
403 do Atendente nunca chega a tocar nesse banco. Não escrever um teste
"Gestor consegue remover campeonato/resultado" aqui sem antes dar ao
banco de domínio o mesmo isolamento que tests/conftest.py já dá ao Core
(regra número um do arquivo: nenhum teste toca o banco real).
"""


def test_atendente_nao_acessa_configuracoes(painel_atendente):
    assert painel_atendente.get("/api/configuracoes").status_code == 403
    resposta = painel_atendente.post("/api/configuracoes/CFG-000001", json={"valor": "x", "ativo": "Sim"})
    assert resposta.status_code == 403


def test_atendente_nao_remove_campeonato_resultado_checklist(painel_atendente):
    # IDs inexistentes de propósito: o alvo é confirmar que o decorator
    # barra ANTES de qualquer consulta ao banco (de domínio, no caso dos
    # dois primeiros) -- ver aviso no topo do arquivo.
    assert painel_atendente.post("/api/campeonatos/CAMP-999999/remover").status_code == 403
    assert painel_atendente.post("/api/resultados/RES-999999/remover").status_code == 403
    assert painel_atendente.post("/api/checklist/DCK-999999/remover").status_code == 403


def test_atendente_nao_acessa_usuarios(painel_atendente):
    assert painel_atendente.get("/api/usuarios").status_code == 403
    resposta = painel_atendente.post(
        "/api/usuarios", json={"nome": "Novo", "email": "novo@example.com", "papel": "Atendente"}
    )
    assert resposta.status_code == 403


def test_gestor_acessa_configuracoes(painel):
    assert painel.get("/api/configuracoes").status_code == 200


def test_gestor_passa_do_gate_em_checklist_remover(painel):
    # ID inexistente: o motor (Core, sem domínio) responde 400 -- o que
    # importa aqui é que NÃO veio 403, ou seja, o Gestor passou do gate.
    resposta = painel.post("/api/checklist/DCK-999999/remover")
    assert resposta.status_code == 400


def test_gestor_lista_usuarios(painel):
    resposta = painel.get("/api/usuarios")
    assert resposta.status_code == 200
    ids = {u["usuario_id"] for u in resposta.get_json()}
    assert "USR-000001" in ids
    assert "USR-000003" in ids


def test_gestor_cria_usuario(painel):
    resposta = painel.post(
        "/api/usuarios", json={"nome": "Novo Atendente", "email": "novo@example.com", "papel": "Atendente"}
    )
    assert resposta.status_code == 201
    corpo = resposta.get_json()
    assert corpo["papel"] == "Atendente"

    listagem = painel.get("/api/usuarios").get_json()
    assert any(u["usuario_id"] == corpo["usuario_id"] for u in listagem)


def test_criar_usuario_papel_invalido(painel):
    resposta = painel.post(
        "/api/usuarios", json={"nome": "X", "email": "x@example.com", "papel": "Dono"}
    )
    assert resposta.status_code == 400


def test_criar_usuario_email_duplicado_na_empresa(painel):
    resposta = painel.post(
        # gestor@example.com já é USR-000001, na mesma empresa (EMPRESA_A).
        "/api/usuarios", json={"nome": "Duplicado", "email": "gestor@example.com", "papel": "Gestor"}
    )
    assert resposta.status_code == 400


def test_gestor_troca_papel_de_atendente(painel):
    resposta = painel.post("/api/usuarios/USR-000003", json={"papel": "Gestor"})
    assert resposta.status_code == 200
    listagem = painel.get("/api/usuarios").get_json()
    usuario = next(u for u in listagem if u["usuario_id"] == "USR-000003")
    assert usuario["papel"] == "Gestor"


def test_gestor_nao_altera_o_proprio_acesso(painel):
    resposta = painel.post("/api/usuarios/USR-000001", json={"papel": "Atendente"})
    assert resposta.status_code == 400
