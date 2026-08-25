"""Tela de Atendimentos (CRM): agrupamento por canal, isolamento entre
empresas e roteamento da resposta pelo canal certo.

Dois riscos motivam esta suíte, nesta ordem:

1. `conversa` é tabela crua consultada pelo painel -- as views do Core
   não cobrem nada disso, então todo filtro de empresa é escrito à mão.
   O `conversa_id` é global (CON-000001…), então sem o filtro bastaria
   trocar o ID na URL para ler a conversa de outro despachante. Mesmo
   raciocínio de tests/test_isolamento_painel.py.
2. Responder pelo canal errado. Uma pergunta que chegou por WhatsApp
   sendo respondida por e-mail não é só estranho: pode ir para um
   endereço que o cliente não usa mais, e o atendimento se perde sem
   erro nenhum aparecer na tela.
"""
import sqlite3

import pytest

from core import motor_conversas
from motor_ia.conexao import CORE_DB
from tests.conftest import AGORA, EMPRESA_A, EMPRESA_B


def _inserir_conversa(
    conversa_id, empresa_id, cliente_id, canal, status=motor_conversas.STATUS_ABERTA,
    assunto=None,
):
    con = sqlite3.connect(CORE_DB)
    con.execute(
        "INSERT INTO conversa (conversa_id, empresa_id, cliente_id, canal, origem, "
        "status, assunto_principal, iniciada_em, ultima_mensagem_em, total_mensagens, "
        "criado_por, atualizado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (conversa_id, empresa_id, cliente_id, canal, "Cliente", status, assunto,
         AGORA, AGORA, 0, "Teste", "Teste"),
    )
    con.commit()
    con.close()


@pytest.fixture
def conversas(banco):
    """Ana (EMPRESA_A) falando pelos dois canais, e Carla (EMPRESA_B)
    com uma conversa que a EMPRESA_A nunca pode enxergar."""
    _inserir_conversa("CON-000001", EMPRESA_A, "CLI-000001", "Email", assunto="Renovação")
    _inserir_conversa("CON-000002", EMPRESA_A, "CLI-000001", "WhatsApp")
    _inserir_conversa("CON-000003", EMPRESA_B, "CLI-000003", "WhatsApp",
                      assunto="Assunto secreto da empresa B")
    return banco


# --------------------------------------------------------------------
# Isolamento entre empresas
# --------------------------------------------------------------------

def test_lista_so_mostra_conversas_da_propria_empresa(conversas, painel):
    dados = painel.get("/api/conversas").get_json()

    ids = [c["conversa_id"] for c in dados["conversas"]]
    assert "CON-000001" in ids
    assert "CON-000002" in ids
    assert "CON-000003" not in ids


def test_nao_abre_conversa_de_outra_empresa(conversas, painel):
    resposta = painel.get("/api/conversas/CON-000003")

    assert resposta.status_code == 404
    assert "Assunto secreto da empresa B" not in resposta.get_data(as_text=True)


def test_conversa_alheia_responde_igual_a_uma_inexistente(conversas, painel):
    """Um 404 diferente de um 403 já entregaria a informação de que
    aquela conversa existe em algum lugar -- mesma cautela do Portal."""
    alheia = painel.get("/api/conversas/CON-000003")
    inexistente = painel.get("/api/conversas/CON-999999")

    assert alheia.status_code == inexistente.status_code == 404


def test_nao_responde_em_conversa_de_outra_empresa(conversas, painel):
    resposta = painel.post(
        "/api/conversas/CON-000003/responder", json={"texto": "invadindo"}
    )

    assert resposta.status_code == 404


def test_nao_muda_status_de_conversa_de_outra_empresa(conversas, painel):
    resposta = painel.post(
        "/api/conversas/CON-000003/status", json={"status": "Encerrada"}
    )
    assert resposta.status_code == 404

    # E o dado da outra empresa continua intacto.
    assert motor_conversas.obter_conversa(EMPRESA_B, "CON-000003")["status"] == "Aberta"


def test_busca_nao_atravessa_a_empresa(conversas, painel):
    """A busca é por texto (nome/CPF/assunto), o tipo de consulta em que
    o filtro de empresa é a única trava real -- não há ID nenhum no meio
    para servir de segunda barreira."""
    dados = painel.get("/api/conversas?busca=Carla").get_json()

    assert dados["conversas"] == []


# --------------------------------------------------------------------
# Agrupamento por canal
# --------------------------------------------------------------------

def test_mesmo_cliente_tem_um_fio_por_canal(conversas):
    """E-mail e WhatsApp da mesma pessoa são conversas separadas: juntar
    os dois num fio só produz um histórico ilegível para quem atende."""
    email = motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "Email")
    whats = motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "WhatsApp")

    assert email == "CON-000001"
    assert whats == "CON-000002"


def test_reaproveita_a_conversa_aberta_em_vez_de_criar_outra(conversas):
    primeira = motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "Email")
    segunda = motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "Email")

    assert primeira == segunda


def test_conversa_encerrada_nao_e_reaproveitada(conversas):
    """Encerrar é um gesto deliberado do atendente. Reabrir a mesma
    linha faria a conversa encerrada ressuscitar sozinha semanas depois."""
    motor_conversas.atualizar_status(EMPRESA_A, "CON-000001", motor_conversas.STATUS_ENCERRADA)

    nova = motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "Email")

    assert nova != "CON-000001"


def test_canal_fora_do_catalogo_e_recusado(conversas):
    with pytest.raises(ValueError, match="Canal inválido"):
        motor_conversas.localizar_ou_criar_conversa(EMPRESA_A, "CLI-000001", "Telegram")


def test_filtro_por_canal(conversas, painel):
    dados = painel.get("/api/conversas?canal=WhatsApp").get_json()

    assert [c["conversa_id"] for c in dados["conversas"]] == ["CON-000002"]


def test_canal_invalido_no_filtro_nao_devolve_tudo(conversas, painel):
    """Um canal desconhecido tem que dar erro, não ser ignorado: ignorar
    faria o filtro devolver a lista inteira parecendo filtrada."""
    resposta = painel.get("/api/conversas?canal=Telegram")

    assert resposta.status_code == 400


# --------------------------------------------------------------------
# Resposta sai pelo canal de origem
# --------------------------------------------------------------------

def test_resposta_de_conversa_de_whatsapp_vai_para_o_telefone(conversas, painel, monkeypatch):
    enviados = []
    monkeypatch.setattr(
        "webapp.app.entregar_resposta",
        lambda canal, destino, texto, assunto=None: (
            enviados.append((canal, destino, texto)) or
            {"enviado": True, "simulado": True, "motivo": None}
        ),
    )

    resposta = painel.post(
        "/api/conversas/CON-000002/responder", json={"texto": "Bom dia!"}
    )

    assert resposta.status_code == 200
    assert len(enviados) == 1
    canal, destino, texto = enviados[0]
    assert canal == "WhatsApp"
    assert destino == "14999990000"  # telefone da Ana, não o e-mail dela
    assert texto == "Bom dia!"


def test_resposta_de_conversa_de_email_vai_para_o_email(conversas, painel, monkeypatch):
    enviados = []
    monkeypatch.setattr(
        "webapp.app.entregar_resposta",
        lambda canal, destino, texto, assunto=None: (
            enviados.append((canal, destino)) or
            {"enviado": True, "simulado": False, "motivo": None}
        ),
    )

    painel.post("/api/conversas/CON-000001/responder", json={"texto": "Bom dia!"})

    assert enviados == [("Email", "ana@example.com")]


def test_resposta_entra_na_thread_como_mensagem_da_empresa(conversas, painel, monkeypatch):
    monkeypatch.setattr(
        "webapp.app.entregar_resposta",
        lambda *a, **k: {"enviado": True, "simulado": True, "motivo": None},
    )

    painel.post("/api/conversas/CON-000002/responder", json={"texto": "Resposta manual"})

    conversa = motor_conversas.obter_conversa(EMPRESA_A, "CON-000002")
    bolhas = conversa["thread"]
    assert len(bolhas) == 1
    assert bolhas[0]["lado"] == "empresa"
    assert bolhas[0]["texto"] == "Resposta manual"


def test_responder_devolve_a_bola_para_o_cliente(conversas, painel, monkeypatch):
    """Depois de responder, a conversa sai de "Aberta" (= precisa de ação
    nossa). Sem isso a caixa de entrada mostraria como pendente algo que
    já foi respondido."""
    monkeypatch.setattr(
        "webapp.app.entregar_resposta",
        lambda *a, **k: {"enviado": True, "simulado": True, "motivo": None},
    )

    painel.post("/api/conversas/CON-000002/responder", json={"texto": "ok"})

    conversa = motor_conversas.obter_conversa(EMPRESA_A, "CON-000002")
    assert conversa["status"] == motor_conversas.STATUS_AGUARDANDO_CLIENTE


def test_falha_de_envio_nao_grava_mensagem_no_historico(conversas, painel, monkeypatch):
    """Gravar uma mensagem que não saiu faria o histórico afirmar que o
    cliente foi respondido quando ele não foi -- pior que não gravar."""
    monkeypatch.setattr(
        "webapp.app.entregar_resposta",
        lambda *a, **k: {"enviado": False, "simulado": False, "motivo": "Canal fora do ar."},
    )

    resposta = painel.post("/api/conversas/CON-000002/responder", json={"texto": "ok"})

    assert resposta.status_code == 400
    assert motor_conversas.obter_conversa(EMPRESA_A, "CON-000002")["thread"] == []


def test_nao_envia_mensagem_vazia(conversas, painel):
    assert painel.post("/api/conversas/CON-000002/responder", json={"texto": "   "}).status_code == 400
