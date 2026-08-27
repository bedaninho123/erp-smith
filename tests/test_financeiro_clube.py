"""Financeiro do clube: situação de anuidade espelhada do Shooting House.

O que estes testes protegem é uma distinção que custa caro errar: o
sistema pode acusar alguém de estar devendo. Três estados diferentes
precisam continuar diferentes:

    'Sim'  = o Shooting House diz que está em dia
    'Não'  = o Shooting House diz que está em atraso
    None   = o campo não veio na resposta

Transformar `None` em `'Não'` faria o painel apontar como inadimplente
quem só tem cadastro incompleto -- e essa é a lista que vira cobrança.

O outro alvo é a separação entre `anuidade_em_dia` (status calculado pelo
fornecedor) e `anuidade_validade` (a data). Os dois discordam para parte
dos filiados reais, e o painel mostra os dois em vez de escolher um.
"""
import sqlite3
from datetime import date, timedelta

import pytest

from domain.clube_tiro import motor_filiados
from domain.clube_tiro.motor_indicadores_clube import filiacoes_por_mes, financeiro
from integracoes.shooting_house import _data_iso, _dentro, _sim_nao
from motor_ia.conexao import DOMAIN_DB
from tests.conftest import EMPRESA_A, EMPRESA_B


def _salvar(cpf, nome, **campos):
    dados = {"cpf": cpf, "nome": nome, "status_filiacao": "Ativo"}
    dados.update(campos)
    return motor_filiados.salvar_filiado(campos.pop("empresa_id", EMPRESA_A), dados)


# --------------------------------------------------------------------
# Conversão do que vem da API
# --------------------------------------------------------------------

def test_ausencia_nao_vira_inadimplencia():
    """O teste mais importante do arquivo: `None` não pode virar 'Não'."""
    assert _sim_nao(None) is None
    assert _sim_nao(True) == "Sim"
    assert _sim_nao(False) == "Não"


def test_bloco_faltando_nao_derruba_a_sincronizacao():
    """A resposta traz `monthly`/`financial`/`documents` às vezes vazios.
    Um cadastro incompleto não pode derrubar uma rodada de 40 páginas."""
    assert _dentro({}, "monthly", "status") is None
    assert _dentro({"monthly": None}, "monthly", "status") is None
    assert _dentro({"monthly": {}}, "monthly", "status") is None
    assert _dentro({"monthly": {"status": True}}, "monthly", "status") is True
    assert _dentro({"documents": {"cr": {"number": "X"}}}, "documents", "cr", "number") == "X"


def test_data_ilegivel_vira_ausencia_e_nunca_data_errada():
    """Os dois formatos aparecem na MESMA resposta. O que não for
    reconhecido vira None -- data errada num campo de validade viraria
    cobrança na pessoa errada."""
    assert _data_iso("2026-12-31T00:00:00") == "2026-12-31"
    assert _data_iso("31/12/2026") == "2026-12-31"
    assert _data_iso("") is None
    assert _data_iso(None) is None
    assert _data_iso("dezembro de 2026") is None


# --------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------

def test_campos_financeiros_entram_no_insert_e_no_update(banco):
    """Os dois caminhos de salvar_filiado precisam gravar os mesmos
    campos. Um deles esquecer uma coluna é a coluna parar de atualizar em
    silêncio para quem já existe."""
    _salvar("11111111111", "Atirador", anuidade_em_dia="Sim", anuidade_validade="2026-12-31")

    con = sqlite3.connect(DOMAIN_DB)
    con.row_factory = sqlite3.Row
    inserido = con.execute("SELECT * FROM filiado WHERE cpf = '11111111111'").fetchone()
    assert inserido["anuidade_em_dia"] == "Sim"
    assert inserido["anuidade_validade"] == "2026-12-31"

    # Mesma pessoa de novo, agora em atraso -- caminho do UPDATE.
    _salvar("11111111111", "Atirador", anuidade_em_dia="Não", anuidade_validade="2026-01-31")
    atualizado = con.execute("SELECT * FROM filiado WHERE cpf = '11111111111'").fetchone()
    con.close()
    assert atualizado["anuidade_em_dia"] == "Não"
    assert atualizado["anuidade_validade"] == "2026-01-31"


def test_sincronizar_lista_nao_apaga_habitualidade(banco):
    """As duas rodadas são separadas, e a da lista roda muito mais vezes.
    Se ela zerasse o retrato, o gráfico por dia esvaziaria sozinho."""
    filiado_id = _salvar("22222222222", "Atirador", anuidade_em_dia="Sim")
    motor_filiados.registrar_habitualidade(
        EMPRESA_A, filiado_id, 5, "2026-08-20", datas=["2026-08-20"]
    )

    _salvar("22222222222", "Atirador", anuidade_em_dia="Não")

    con = sqlite3.connect(DOMAIN_DB)
    con.row_factory = sqlite3.Row
    linha = con.execute("SELECT * FROM filiado WHERE cpf = '22222222222'").fetchone()
    con.close()
    assert linha["participacoes_12m"] == 5
    assert linha["participacoes_datas"] is not None
    assert linha["anuidade_em_dia"] == "Não"


# --------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------

def test_sem_dado_nao_entra_em_dia_nem_em_atraso(banco):
    _salvar("33333333331", "Em dia", anuidade_em_dia="Sim")
    _salvar("33333333332", "Em atraso", anuidade_em_dia="Não")
    _salvar("33333333333", "Sem informação")

    f = financeiro(EMPRESA_A)

    assert f["ativos"] == 3
    assert f["em_dia"] == 1
    assert f["em_atraso"] == 1
    assert f["sem_dado"] == 1
    # 1 de 3, e não 1 de 2: quem não tem dado continua sendo filiado.
    assert f["pct_em_dia"] == 33


def test_percentual_sem_filiado_e_none_e_nao_zero(banco):
    """'0% em dia' seria uma afirmação sobre um clube que não tem ninguém."""
    assert financeiro(EMPRESA_A)["pct_em_dia"] is None


def test_janelas_de_vencimento(banco):
    hoje = date.today()
    _salvar("44444444441", "Vencida", anuidade_validade=(hoje - timedelta(days=5)).isoformat())
    _salvar("44444444442", "Vence em 10", anuidade_validade=(hoje + timedelta(days=10)).isoformat())
    _salvar("44444444443", "Vence em 60", anuidade_validade=(hoje + timedelta(days=60)).isoformat())
    _salvar("44444444444", "Vence em 200", anuidade_validade=(hoje + timedelta(days=200)).isoformat())
    _salvar("44444444445", "Sem validade")

    f = financeiro(EMPRESA_A, hoje=hoje)

    assert f["vencida"] == 1
    assert f["vence_em_30"] == 1
    assert f["vence_em_90"] == 2      # a de 10 e a de 60 dias
    assert f["sem_validade"] == 1
    # A fila de cobrança traz vencidas e a vencer, mais antiga primeiro.
    assert [x["nome"] for x in f["vencendo_lista"]] == ["Vencida", "Vence em 10"]


def test_financeiro_de_uma_empresa_nao_conta_a_outra(banco):
    _salvar("55555555551", "Da empresa A", anuidade_em_dia="Sim")
    motor_filiados.salvar_filiado(EMPRESA_B, {
        "cpf": "55555555552", "nome": "Da empresa B",
        "status_filiacao": "Ativo", "anuidade_em_dia": "Não",
    })

    assert financeiro(EMPRESA_A)["ativos"] == 1
    assert financeiro(EMPRESA_A)["em_atraso"] == 0
    assert financeiro(EMPRESA_B)["em_atraso"] == 1


def test_filiacoes_por_mes_usa_a_data_real_e_conta_quem_nao_tem(banco):
    """Substituiu a contagem por `criado_em`, que era 'quando o sistema
    viu a pessoa' e obrigava a excluir o dia da carga inicial."""
    hoje = date.today()
    este_mes = hoje.replace(day=1).isoformat()
    _salvar("66666666661", "Filiou este mês", data_filiacao=este_mes)
    _salvar("66666666662", "Filiou há muito tempo", data_filiacao="2021-03-15")
    _salvar("66666666663", "Sem data de filiação")

    saida = filiacoes_por_mes(EMPRESA_A, hoje=hoje)

    assert len(saida["meses"]) == 12
    assert saida["meses"][-1]["em_curso"] is True
    assert saida["meses"][-1]["total"] == 1
    assert saida["sem_data"] == 1
    assert saida["total"] == 3


def test_rota_do_dashboard_entrega_o_financeiro(banco, painel):
    _salvar("77777777771", "Atirador", anuidade_em_dia="Sim", anuidade_validade="2026-12-31")

    dados = painel.get("/api/dashboard").get_json()

    assert dados["financeiro"]["ativos"] == 1
    assert dados["financeiro"]["em_dia"] == 1
    assert "vencendo_lista" in dados["financeiro"]
    assert "cr" in dados["financeiro"]


def test_atendente_nao_ve_o_financeiro(banco, painel_atendente):
    """Mesma trava do resto do Dashboard: situação financeira de filiado
    é do dono, não da equipe."""
    assert painel_atendente.get("/api/dashboard").status_code == 403
