"""Item de checklist a mais, só num processo (2026-09-24).

Quem tem pistola, carabina e revólver precisa de uma capacidade técnica
para cada. PRO-000001 (Ana) e PRO-000002 (Bruno) são do MESMO serviço na
mesma empresa -- o caso perigoso: o extra da Ana não pode aparecer, nem
ser usado, no processo do Bruno.
"""
import pytest

from core import motor_checklist
from core.conexao import conectar, conectar_admin
from core.db.migrar_itens_por_processo import migrar
from core.db.revisar_checklist_cac import revisar
from tests.conftest import EMPRESA_A

BASE = "Comprovante de capacidade técnica de arma de fogo"


@pytest.fixture
def item_base(banco):
    con = conectar_admin()
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, grupo, "
        "item, ordem, ativo) VALUES ('DEX-000001', ?, 'SER-000001', NULL, ?, 1, 'Sim')",
        (EMPRESA_A, BASE),
    )
    con.execute(
        "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, servico_id, grupo, "
        "item, ordem, ativo) VALUES ('DEX-000002', ?, 'SER-000001', NULL, 'RG ou CNH', 2, 'Sim')",
        (EMPRESA_A,),
    )
    con.commit()
    con.close()


def _itens(processo_id):
    con = conectar(EMPRESA_A)
    try:
        return [i["item"] for i in motor_checklist.status_checklist(con, EMPRESA_A, processo_id)]
    finally:
        con.close()


def test_extra_aparece_logo_abaixo_e_so_neste_processo(item_base, painel):
    resposta = painel.post("/api/processos/PRO-000001/checklist/itens",
                           json={"documento_exigido_id": "DEX-000001", "complemento": "Carabina"})
    assert resposta.status_code == 200

    assert _itens("PRO-000001") == [BASE, f"{BASE} — Carabina", "RG ou CNH"]
    assert _itens("PRO-000002") == [BASE, "RG ou CNH"]


def test_sem_complemento_vira_adicional_e_copia_de_extra_nao_empilha(item_base):
    extra = motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", "DEX-000001")
    motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", extra, "Revólver")
    assert _itens("PRO-000001")[:3] == [BASE, f"{BASE} — adicional", f"{BASE} — Revólver"]


def test_extra_de_outro_processo_nao_aceita_documento(item_base):
    extra = motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", "DEX-000001", "Carabina")
    with pytest.raises(ValueError):
        motor_checklist.marcar_documento(
            EMPRESA_A, "PRO-000002", extra, "DOC-000002", marcado_por="Teste",
        )


def test_ia_nao_ve_o_extra(item_base):
    motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", "DEX-000001", "Carabina")
    con = conectar(EMPRESA_A)
    itens = [l["item"] for l in con.execute("SELECT item FROM VW_CHECKLIST_SERVICO")]
    con.close()
    assert itens == [BASE, "RG ou CNH"]


def test_remover_so_extra_e_so_sem_documento(item_base, painel):
    extra = motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", "DEX-000001", "Carabina")

    # Item da ficha não sai por aqui.
    assert painel.post("/api/processos/PRO-000001/checklist/itens/DEX-000001/remover").status_code == 400

    motor_checklist.marcar_documento(EMPRESA_A, "PRO-000001", extra, "DOC-000001", marcado_por="Teste")
    assert painel.post(f"/api/processos/PRO-000001/checklist/itens/{extra}/remover").status_code == 400

    con = conectar_admin()
    con.execute("DELETE FROM documento_checklist WHERE documento_exigido_id = ?", (extra,))
    con.commit()
    con.close()
    assert painel.post(f"/api/processos/PRO-000001/checklist/itens/{extra}/remover").status_code == 200
    assert _itens("PRO-000001") == [BASE, "RG ou CNH"]


def test_revisao_das_fichas_nunca_mexe_nos_extras(banco):
    revisar(EMPRESA_A)
    con = conectar_admin()
    primeiro = con.execute(
        "SELECT documento_exigido_id FROM documento_exigido WHERE servico_id = 'SER-000001' "
        "AND ativo = 'Sim' ORDER BY ordem LIMIT 1"
    ).fetchone()[0]
    con.close()
    extra = motor_checklist.adicionar_item_extra(EMPRESA_A, "PRO-000001", primeiro, "Carabina")

    segunda = revisar(EMPRESA_A)
    assert all(s["igual"] for s in segunda["servicos"])
    con = conectar_admin()
    ainda = con.execute(
        "SELECT ativo FROM documento_exigido WHERE documento_exigido_id = ?", (extra,)
    ).fetchone()
    con.close()
    assert ainda["ativo"] == "Sim"


def test_migracao_e_idempotente(banco):
    migrar()
    assert migrar() == {"coluna_criada": False, "view_refeita": False}
