"""Documento que o cliente envia pelo Portal fica pendente de aprovação.

Até 2026-07-29, ligar um arquivo a um item do checklist era privilégio de
quem tinha login do painel. Agora o cliente também liga -- ele escolhe o
item na hora de enviar. Isso é conveniente e é uma superfície nova: o
formulário passou a mandar `processo_id` e `documento_exigido_id`, e
quem manda é o navegador do cliente, que pode mandar qualquer coisa.

Daí os dois grupos de teste aqui:

1. **O fluxo**: enviado fica aguardando, aprovado conta como recebido,
   recusado volta a faltar com o motivo à vista do cliente.
2. **O que não pode acontecer**: um cliente anexando documento no
   processo de outro, e um funcionário decidindo sobre documento de
   outra empresa.

O grupo 2 é o que importa de verdade. O 1 quebra e alguém reclama; o 2
quebra e vaza documento de arma de fogo entre pessoas.
"""
import io
import sqlite3

import pytest

from core import motor_checklist
from core.conexao import CORE_DB, conectar

from tests.conftest import EMPRESA_A, EMPRESA_B, SERVICO_DA_EMPRESA

# Um item de checklist para o serviço de cada empresa.
ITEM_A = "DEX-000001"
ITEM_B = "DEX-000002"


@pytest.fixture
def checklist(banco):
    """Acrescenta um item exigido ao serviço de cada empresa.

    O fixture `banco` do conftest não cria checklist -- ele existe para
    os testes de isolamento, que não precisam disso. Criar aqui mantém o
    conftest enxuto e deixa explícito o que estes testes assumem.
    """
    con = sqlite3.connect(CORE_DB)
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
        "grupo, item, ordem, ativo) VALUES (?,?,?,?,?,?,?)",
        (ITEM_A, EMPRESA_A, SERVICO_DA_EMPRESA[EMPRESA_A], "Pessoais",
         "Documento de identificação", 1, "Sim"),
    )
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, "
        "grupo, item, ordem, ativo) VALUES (?,?,?,?,?,?,?)",
        (ITEM_B, EMPRESA_B, SERVICO_DA_EMPRESA[EMPRESA_B], "Pessoais",
         "Documento de identificação", 1, "Sim"),
    )
    con.commit()
    con.close()
    return banco


def _enviar_pelo_portal(portal, caso_id, processo_id, documento_exigido_id, nome="rg.pdf"):
    return portal.post(
        "/portal/documentos",
        data={
            "caso_id": caso_id,
            "tipo_documento": f"{processo_id}|{documento_exigido_id}",
            "arquivo": (io.BytesIO(b"%PDF-1.4 documento do cliente"), nome),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def _item(processo_id, empresa_id=EMPRESA_A):
    con = conectar(empresa_id)
    try:
        return motor_checklist.status_checklist(con, empresa_id, processo_id)[0]
    finally:
        con.close()


# --------------------------------------------------------------------
# 1. O fluxo
# --------------------------------------------------------------------

def test_envio_do_cliente_fica_aguardando_e_nao_conta_como_recebido(checklist, portal):
    """O ponto todo da mudança: enviar não é o mesmo que estar resolvido.

    Se `recebido` virasse True aqui, a contagem X/Y e o anel de progresso
    do Portal diriam ao cliente que o item está pronto quando ninguém da
    equipe olhou o arquivo ainda.
    """
    _enviar_pelo_portal(portal, "CAS-000001", "PRO-000001", ITEM_A)

    item = _item("PRO-000001")
    assert item["estado"] == "aguardando"
    assert item["recebido"] is False


def test_aprovar_pelo_painel_marca_como_recebido(checklist, portal, painel):
    _enviar_pelo_portal(portal, "CAS-000001", "PRO-000001", ITEM_A)
    dck = painel.get("/api/documentos-pendentes").get_json()[0]["documento_checklist_id"]

    resposta = painel.post(f"/api/checklist/{dck}/aprovar")

    assert resposta.status_code == 200
    item = _item("PRO-000001")
    assert item["estado"] == "aprovado"
    assert item["recebido"] is True


def test_recusar_devolve_o_item_para_faltando_com_o_motivo(checklist, portal, painel):
    _enviar_pelo_portal(portal, "CAS-000001", "PRO-000001", ITEM_A)
    dck = painel.get("/api/documentos-pendentes").get_json()[0]["documento_checklist_id"]

    painel.post(f"/api/checklist/{dck}/recusar", json={"motivo": "Foto ilegível."})

    item = _item("PRO-000001")
    assert item["estado"] == "faltando"
    assert item["motivo_recusa"] == "Foto ilegível."
    # O motivo tem que chegar aos olhos do cliente -- guardá-lo no banco
    # sem mostrar deixaria ele reenviando o mesmo arquivo errado.
    assert "Foto ilegível." in portal.get("/portal/casos/CAS-000001").get_data(as_text=True)


def test_recusa_sem_motivo_e_recusada(checklist, portal, painel):
    _enviar_pelo_portal(portal, "CAS-000001", "PRO-000001", ITEM_A)
    dck = painel.get("/api/documentos-pendentes").get_json()[0]["documento_checklist_id"]

    resposta = painel.post(f"/api/checklist/{dck}/recusar", json={"motivo": "   "})

    assert resposta.status_code == 400
    assert _item("PRO-000001")["estado"] == "aguardando"


def test_marcacao_feita_pelo_painel_ja_nasce_aprovada(checklist, painel):
    """Quem marca pelo painel é uma pessoa que abriu o arquivo -- a
    marcação já é a conferência. Se isso virar 'aguardando', a equipe
    cria fila de trabalho pra si mesma."""
    resposta = painel.post(
        "/api/processos/PRO-000001/checklist",
        json={"documento_exigido_id": ITEM_A, "documento_id": "DOC-000001"},
    )

    assert resposta.status_code == 200
    assert _item("PRO-000001")["estado"] == "aprovado"
    assert painel.get("/api/documentos-pendentes").get_json() == []


def _enviar_pelo_checklist_do_painel(painel, caso_id, processo_id, documento_exigido_id):
    return painel.post(
        f"/api/casos/{caso_id}/documentos",
        data={
            "processo_id": processo_id,
            "documento_exigido_id": documento_exigido_id,
            "tipo_documento": "Documento de identificação",
            "arquivo": (io.BytesIO(b"%PDF-1.4 trazido no balcao"), "rg-balcao.pdf"),
        },
        content_type="multipart/form-data",
    )


def test_arquivo_enviado_pelo_checklist_do_painel_aparece_recebido_no_portal(checklist, painel, portal):
    """O pedido de 2026-10-20: enviar no checklist e o cliente ver.

    Antes, o arquivo enviado pelo painel ficava solto no caso e o item
    seguia "faltando" no Portal até alguém marcar à mão, em outro gesto.
    """
    antes = portal.get("/portal/casos/CAS-000001").get_data(as_text=True)
    assert "faltando" in antes

    resposta = _enviar_pelo_checklist_do_painel(painel, "CAS-000001", "PRO-000001", ITEM_A)

    assert resposta.status_code == 200
    item = _item("PRO-000001")
    assert item["estado"] == "aprovado"
    assert item["documentos"][0]["nome_arquivo"] == "rg-balcao.pdf"
    depois = portal.get("/portal/casos/CAS-000001").get_data(as_text=True)
    assert "faltando" not in depois


def test_checklist_do_painel_nao_envia_para_processo_de_outro_caso(checklist, painel):
    """Caso da Ana na URL, processo do Bruno no formulário: nem o arquivo
    pode ser gravado, senão ficaria um documento da Ana pendurado no
    processo do Bruno."""
    resposta = _enviar_pelo_checklist_do_painel(painel, "CAS-000001", "PRO-000002", ITEM_A)

    assert resposta.status_code == 400
    assert _item("PRO-000002")["estado"] == "faltando"
    con = conectar(EMPRESA_A)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM documento WHERE nome_arquivo = 'rg-balcao.pdf'"
        ).fetchone()[0] == 0
    finally:
        con.close()


def test_documento_de_outro_cliente_nao_e_marcado_no_checklist(checklist, painel):
    """DOC-000002 é do Bruno, mesma empresa da Ana. Marcado no processo da
    Ana, o nome do arquivo dele apareceria no Portal dela -- o filtro de
    empresa não pega isso."""
    resposta = painel.post(
        "/api/processos/PRO-000001/checklist",
        json={"documento_exigido_id": ITEM_A, "documento_id": "DOC-000002"},
    )

    assert resposta.status_code == 400
    assert _item("PRO-000001")["estado"] == "faltando"


# --------------------------------------------------------------------
# 2. O que não pode acontecer
# --------------------------------------------------------------------

def test_cliente_nao_anexa_documento_no_processo_de_outro_cliente(checklist, portal):
    """Ana envia apontando para o processo do Bruno (mesma empresa).

    O `processo_id` vem do formulário, então trocar o valor é trivial. Os
    dois estão na mesma empresa, logo o filtro de empresa não salva
    ninguém aqui -- o que segura é a checagem de que o processo pertence
    ao caso que já sabemos ser de quem está logado.
    """
    resposta = _enviar_pelo_portal(portal, "CAS-000001", "PRO-000002", ITEM_A)

    assert resposta.status_code == 200
    assert "não encontrado" in resposta.get_data(as_text=True).lower()
    # Nada foi ligado ao processo do Bruno.
    assert _item("PRO-000002")["estado"] == "faltando"


def test_cliente_nao_anexa_usando_caso_de_outro_cliente(checklist, portal):
    """Mesma ideia, pelo outro lado: trocar o caso_id em vez do processo.

    Aqui o cliente é jogado de volta pra lista de casos, não pro caso que
    ele tentou acessar -- por isso a asserção olha o efeito no banco, e
    não o texto da página de destino.
    """
    resposta = _enviar_pelo_portal(portal, "CAS-000002", "PRO-000002", ITEM_A)

    assert resposta.status_code == 200
    assert "não encontrado" in resposta.get_data(as_text=True).lower()
    assert _item("PRO-000002")["estado"] == "faltando"
    # E o documento não chegou a existir em lugar nenhum.
    con = conectar(EMPRESA_A)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM documento WHERE nome_arquivo = 'rg.pdf'"
        ).fetchone()[0] == 0
    finally:
        con.close()


def test_fila_do_painel_so_mostra_documento_da_propria_empresa(checklist, painel):
    """Carla (EMP-000002) tem documento aguardando; o painel da EMP-000001
    não pode enxergar nem o nome do arquivo dela."""
    motor_checklist.marcar_documento(
        EMPRESA_B, "PRO-000003", ITEM_B, "DOC-000003",
        marcado_por=motor_checklist.MARCADO_POR_CLIENTE,
        status=motor_checklist.STATUS_AGUARDANDO,
    )

    fila = painel.get("/api/documentos-pendentes").get_json()

    assert fila == []


def test_funcionario_nao_aprova_documento_de_outra_empresa(checklist, painel):
    """O ID da marcação vai na URL. Sem o filtro por empresa, adivinhar um
    DCK-000001 deixaria o funcionário de um despachante decidir sobre o
    documento de um cliente de outro."""
    dck_da_outra = motor_checklist.marcar_documento(
        EMPRESA_B, "PRO-000003", ITEM_B, "DOC-000003",
        marcado_por=motor_checklist.MARCADO_POR_CLIENTE,
        status=motor_checklist.STATUS_AGUARDANDO,
    )

    aprovacao = painel.post(f"/api/checklist/{dck_da_outra}/aprovar")
    recusa = painel.post(f"/api/checklist/{dck_da_outra}/recusar", json={"motivo": "não"})

    assert aprovacao.status_code == 400
    assert recusa.status_code == 400
    # E continua intacto na empresa dele.
    con = conectar(EMPRESA_B)
    try:
        status = con.execute(
            "SELECT status FROM documento_checklist WHERE documento_checklist_id = ?",
            (dck_da_outra,),
        ).fetchone()["status"]
    finally:
        con.close()
    assert status == motor_checklist.STATUS_AGUARDANDO
