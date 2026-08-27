"""Dashboard do Gestor: quem alcança, e se as contas fecham.

Duas famílias, por dois riscos:

1. **Acesso.** É a tela de faturamento estimado, produtividade e evasão
   do clube. Fica fora do catálogo de permissões de propósito, então
   nenhum toggle a libera para um Atendente -- e é isso que precisa
   continuar verdade depois de qualquer refatoração.

2. **Aritmética.** Comparação de mês em curso, "não sei" que não vira
   zero, e a data de encerramento que passou a ser carimbada. Cada um
   desses erra em silêncio: o painel continua desenhando, só com o
   número errado.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from core.conexao import conectar, conectar_admin
from core.motor_casos import atualizar_status
from core.motor_indicadores import _recorte_mes, resumo
from core.motor_usuarios import atualizar_permissoes
from tests.conftest import EMPRESA_A, EMPRESA_B


def _iso(quando: datetime) -> str:
    return quando.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mover_criacao(caso_id: str, quando: datetime) -> None:
    con = conectar_admin()
    con.execute("UPDATE caso SET criado_em = ? WHERE caso_id = ?", (_iso(quando), caso_id))
    con.commit()
    con.close()


# --------------------------------------------------------------------
# Acesso
# --------------------------------------------------------------------

def test_atendente_nao_alcanca_o_dashboard(banco, painel_atendente):
    assert painel_atendente.get("/api/dashboard").status_code == 403


def test_nenhuma_permissao_libera_o_dashboard_para_atendente(banco, painel_atendente):
    """O ponto central da decisão: mesmo com TODAS as funções do catálogo
    ligadas, o Atendente continua fora. Se alguém um dia trocar
    @gestor_required por @funcao_required aqui, este teste cai."""
    from core.motor_usuarios import FUNCOES_VALIDAS

    atualizar_permissoes(
        EMPRESA_A, "USR-000003", {chave: "Sim" for chave in FUNCOES_VALIDAS}
    )

    assert painel_atendente.get("/api/dashboard").status_code == 403


def test_dashboard_nao_entra_no_catalogo_de_permissoes():
    """Não pode existir toggle de 'dashboard' na tela de Usuários -- ter
    um daria a impressão de que dá para conceder, e não dá."""
    from core.motor_usuarios import FUNCOES_VALIDAS

    assert "dashboard" not in FUNCOES_VALIDAS


def test_gestor_recebe_o_dashboard_inteiro(banco, painel):
    dados = painel.get("/api/dashboard").get_json()

    assert set(dados) >= {
        "negocio", "clube", "penetracao", "habitualidade_dia",
        "habitualidade_mes", "novos_filiados", "tarefas",
    }


# --------------------------------------------------------------------
# Isolamento entre empresas
# --------------------------------------------------------------------

def test_dashboard_nao_conta_caso_de_outra_empresa(banco, painel):
    """A empresa A tem dois casos (Ana e Bruno); a B tem o da Carla."""
    dados = painel.get("/api/dashboard").get_json()

    fila = {f["status"]: f["total"] for f in dados["negocio"]["fila_por_status"]}
    assert fila.get("Aberto") == 2
    assert "Caso da Carla" not in str(dados)


def test_encerrar_caso_da_empresa_a_nao_aparece_para_a_b(banco):
    atualizar_status(EMPRESA_A, "CAS-000001", "Encerrado")

    assert resumo(EMPRESA_A)["concluidos"]["valor"] == 1
    assert resumo(EMPRESA_B)["concluidos"]["valor"] == 0


# --------------------------------------------------------------------
# Aritmética
# --------------------------------------------------------------------

def test_encerrar_carimba_a_data_e_reabrir_apaga(banco):
    """`encerrado_em` existia no schema e nunca era escrito -- sem ele
    não há 'concluídos no mês'."""
    atualizar_status(EMPRESA_A, "CAS-000001", "Encerrado")

    con = conectar_admin()
    encerrado = con.execute(
        "SELECT encerrado_em FROM caso WHERE caso_id = 'CAS-000001'"
    ).fetchone()[0]
    con.close()
    assert encerrado

    atualizar_status(EMPRESA_A, "CAS-000001", "Em andamento")
    con = conectar_admin()
    reaberto = con.execute(
        "SELECT encerrado_em FROM caso WHERE caso_id = 'CAS-000001'"
    ).fetchone()[0]
    con.close()
    assert reaberto is None, "caso reaberto continuou com data de encerramento"


def test_cancelado_nao_conta_como_concluido(banco):
    """Trabalho cancelado não é trabalho entregue -- contar inflaria a
    produtividade justamente nos meses ruins."""
    atualizar_status(EMPRESA_A, "CAS-000001", "Cancelado")

    assert resumo(EMPRESA_A)["concluidos"]["valor"] == 0


def test_compara_com_o_mesmo_pedaco_do_mes_anterior():
    """No dia 5, agosto inteiro contra julho inteiro faria agosto parecer
    um desastre todo santo mês."""
    recorte = _recorte_mes(date(2026, 8, 5))

    assert recorte["atual"] == ("2026-08-01", "2026-08-06")
    assert recorte["anterior"] == ("2026-07-01", "2026-07-06")
    assert recorte["dia_equivalente"] == 5


def test_dia_31_comparado_com_mes_curto_nao_estoura():
    """31 de março não existe em fevereiro. Sem o min(), isto era um
    ValueError -- ou seja, o Dashboard fora do ar em três dias do ano."""
    recorte = _recorte_mes(date(2026, 3, 31))

    assert recorte["anterior"] == ("2026-02-01", "2026-03-01")
    assert recorte["dia_equivalente"] == 28


def test_tempo_medio_sem_encerramento_e_none_e_nao_zero(banco):
    """Zero dias leria como 'concluo na hora'. A ausência tem que doer na
    tela como travessão, não como recorde."""
    indicadores = resumo(EMPRESA_A)

    assert indicadores["tempo_medio_dias"]["valor"] is None


def test_tempo_medio_conta_da_abertura_ao_encerramento(banco):
    hoje = datetime.now(timezone.utc)
    _mover_criacao("CAS-000001", hoje - timedelta(days=10))
    atualizar_status(EMPRESA_A, "CAS-000001", "Encerrado")

    medio = resumo(EMPRESA_A)["tempo_medio_dias"]["valor"]

    assert medio is not None
    assert 9.5 <= medio <= 10.5


def test_serie_de_meses_nao_pula_mes_vazio(banco):
    """GROUP BY não devolve linha para mês sem caso, e o gráfico fecharia
    o buraco -- mostrando uma sequência que não aconteceu."""
    serie = resumo(EMPRESA_A)["casos_por_mes"]

    assert len(serie) == 12
    assert serie[-1]["em_curso"] is True
    assert all("abertos" in m and "concluidos" in m for m in serie)


def test_percentual_de_autonomia_sem_mensagem_e_none(banco):
    indicadores = resumo(EMPRESA_A)

    assert indicadores["atendimento"]["total"] == 0
    assert indicadores["atendimento"]["pct_sozinha"] is None


def test_valor_em_andamento_avisa_quando_o_catalogo_esta_vazio(banco):
    """O fixture cria serviço sem valor_referencia. Um total de R$ 0 sem
    o aviso pareceria 'nenhum dinheiro em jogo'."""
    valor = resumo(EMPRESA_A)["em_andamento"]

    assert valor["estimativa"] is True
    assert valor["processos"] == 2      # Ana e Bruno
    assert valor["sem_valor"] == 2


# --------------------------------------------------------------------
# Clube: as duas armadilhas que apareceram rodando de verdade
# --------------------------------------------------------------------

def _semear_filiado(cpf: str, nome: str, datas, criado_em: str, ativo: str = "Ativo") -> None:
    import json
    import sqlite3

    from motor_ia.conexao import DOMAIN_DB

    con = sqlite3.connect(DOMAIN_DB)
    con.execute(
        "INSERT INTO filiado (filiado_id, empresa_id, nome, cpf, status_filiacao, "
        "participacoes_12m, ultima_participacao, participacoes_datas, sincronizado_em, "
        "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (f"FIL-{cpf}", EMPRESA_A, nome, cpf, ativo,
         None if datas is None else len(datas),
         None if not datas else max(datas),
         None if datas is None else json.dumps(datas),
         None if datas is None else "2026-08-27T08:00:00Z",
         criado_em, criado_em),
    )
    con.commit()
    con.close()


def test_carga_inicial_nao_conta_como_novo_filiado_do_mes(banco):
    """A importação trouxe o clube inteiro num dia. Contar esse dia diria
    '1.525 novos filiados este mês' -- o número que mais interessa ao dono
    virando o mais errado da tela."""
    from domain.clube_tiro.motor_indicadores_clube import resumo as resumo_clube

    hoje = date.today()
    dia_carga = hoje.replace(day=1).isoformat()
    for i in range(5):
        _semear_filiado(f"1000000000{i}", f"Carga {i}", [], f"{dia_carga}T09:00:00Z")
    _semear_filiado("20000000001", "Entrou depois", [], f"{hoje.isoformat()}T09:00:00Z")

    saida = resumo_clube(EMPRESA_A, hoje=hoje)

    assert saida["novos_no_mes"] == 1, "a carga inicial entrou na contagem do mês"
    assert saida["carga_no_mes"] == 5
    assert saida["dia_da_carga"] == dia_carga


def test_filiado_nunca_consultado_nao_vira_zero_participacao(banco):
    """NULL é 'não perguntei'; [] é 'perguntei e não teve'. Se os dois
    virassem a mesma barra baixa, a tela pararia de distinguir clube
    parado de sincronização atrasada."""
    from domain.clube_tiro.motor_indicadores_clube import serie_por_dia

    _semear_filiado("30000000001", "Nunca consultado", None, "2026-08-01T09:00:00Z")
    _semear_filiado("30000000002", "Consultado, sem treino", [], "2026-08-01T09:00:00Z")

    serie = serie_por_dia(EMPRESA_A)

    assert serie["cobertura"] == {"com_datas": 1, "ativos": 2}
    assert sum(d["participacoes"] for d in serie["dias"]) == 0


def test_serie_por_dia_soma_repeticao_e_conta_atirador_uma_vez(banco):
    """Duas participações no mesmo dia são dois eventos, mas um atirador
    só -- é essa diferença que separa 'movimento' de 'gente'."""
    from domain.clube_tiro.motor_indicadores_clube import serie_por_dia

    hoje = date.today()
    ontem = (hoje - timedelta(days=1)).isoformat()
    _semear_filiado("40000000001", "Treinou duas vezes", [ontem, ontem], "2026-08-01T09:00:00Z")
    _semear_filiado("40000000002", "Treinou uma vez", [ontem], "2026-08-01T09:00:00Z")

    dia = next(d for d in serie_por_dia(EMPRESA_A, hoje=hoje)["dias"] if d["data"] == ontem)

    assert dia["participacoes"] == 3
    assert dia["atiradores"] == 2


def test_sincronizar_reescreve_as_datas_em_vez_de_somar(banco):
    """Cada rodada do rodízio reescreve a lista da pessoa. Acumular
    duplicaria a mesma participação a cada sincronização, e o gráfico
    subiria sozinho sem ninguém treinar."""
    import json
    import sqlite3

    from domain.clube_tiro import motor_filiados
    from motor_ia.conexao import DOMAIN_DB

    _semear_filiado("50000000001", "Atirador", ["2026-08-20"], "2026-08-01T09:00:00Z")

    con = sqlite3.connect(DOMAIN_DB)
    filiado_id = con.execute(
        "SELECT filiado_id FROM filiado WHERE cpf = '50000000001'"
    ).fetchone()[0]
    con.close()

    motor_filiados.registrar_habitualidade(
        EMPRESA_A, filiado_id, 1, "2026-08-20", datas=["2026-08-20"]
    )

    con = sqlite3.connect(DOMAIN_DB)
    guardado = con.execute(
        "SELECT participacoes_datas FROM filiado WHERE filiado_id = ?", (filiado_id,)
    ).fetchone()[0]
    con.close()

    assert json.loads(guardado) == ["2026-08-20"]
