"""Indicadores do clube para o Dashboard: participações por dia e por
mês, novos filiados, e quem está sumindo.

Mora no Domínio porque nada aqui existe fora de um clube de tiro -- um
escritório de advocacia não tem filiado nem habitualidade. O Core não
sabe que este arquivo existe.

**O que estes números são.** Todos saem da tabela `filiado`, que é um
RETRATO sincronizado do Shooting House, não a verdade sobre habitualidade.
Vêm sempre acompanhados de `cobertura` -- quantos filiados já entraram no
rodízio -- porque um gráfico subindo pode ser o clube treinando mais ou
simplesmente a sincronização alcançando mais gente. Sem esse número ao
lado, os dois são indistinguíveis, e a leitura errada é a otimista.

**O que eles não são.** Nenhum número daqui responde pergunta de cliente.
"Minha habitualidade está em dia?" continua sendo consulta ao vivo, e o
sistema não dá veredito sobre o mínimo legal (ver JANELA_MESES em
motor_filiados.py).
"""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from domain.clube_tiro.motor_filiados import conectar

# Quem não aparece há tanto tempo está saindo do clube, mesmo que ninguém
# tenha cancelado nada. É o sinal de evasão mais barato que existe aqui.
DIAS_SUMIDO = 90

_ROTULO_MES = ("jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez")


def _hoje() -> date:
    return date.today()


def _carregar_datas(empresa_id: str) -> tuple[list, dict]:
    """Devolve (lista de (cpf, datas), cobertura).

    Traz o lado pequeno inteiro para a memória e agrega em Python, mesmo
    padrão que o painel já usa para cruzar filiado com cliente: são ~1500
    linhas com ~20 datas cada, e a alternativa (uma tabela de eventos)
    é exatamente a cópia do registro que este projeto decidiu não manter.
    """
    con = conectar()
    try:
        linhas = con.execute(
            "SELECT cpf, participacoes_datas FROM filiado "
            "WHERE empresa_id = ? AND status_filiacao = 'Ativo'",
            (empresa_id,),
        ).fetchall()
    finally:
        con.close()

    registros, com_datas = [], 0
    for linha in linhas:
        bruto = linha["participacoes_datas"]
        if bruto is None:
            # NULL é "ainda não perguntei". Fica de fora da soma, e é
            # contado na cobertura -- nunca vira zero participações.
            continue
        com_datas += 1
        try:
            datas = json.loads(bruto)
        except (ValueError, TypeError):
            continue
        registros.append((linha["cpf"], datas))

    return registros, {"com_datas": com_datas, "ativos": len(linhas)}


def serie_por_dia(empresa_id: str, dias: int = 30, hoje: Optional[date] = None) -> dict:
    """Participações e atiradores distintos por dia, do mais antigo para o
    mais recente, sem buraco: dia sem ninguém aparece como zero.

    Um dia zerado aqui é uma afirmação legítima ("consultei todo mundo que
    tem datas, ninguém treinou") -- diferente do filiado NULL, que é
    "não perguntei". A diferença vive em `cobertura`.
    """
    hoje = hoje or _hoje()
    registros, cobertura = _carregar_datas(empresa_id)

    primeiro = hoje - timedelta(days=dias - 1)
    chaves = [(primeiro + timedelta(days=i)).isoformat() for i in range(dias)]
    contagem = {chave: 0 for chave in chaves}
    atiradores = {chave: set() for chave in chaves}

    for cpf, datas in registros:
        for data in datas:
            if data in contagem:
                contagem[data] += 1
                atiradores[data].add(cpf)

    return {
        "cobertura": cobertura,
        "dias": [
            {
                "data": chave,
                "participacoes": contagem[chave],
                "atiradores": len(atiradores[chave]),
                # O clube fecha em algum dia da semana, e a barra zerada
                # desse dia não é falta de dado. A tela precisa saber qual
                # dia é qual para não chamar de "queda" o dia fechado.
                "semana": datetime.strptime(chave, "%Y-%m-%d").weekday(),
            }
            for chave in chaves
        ],
    }


def serie_por_mes(empresa_id: str, meses: int = 12, hoje: Optional[date] = None) -> dict:
    """Participações e atiradores distintos por mês.

    A janela de habitualidade é de 12 meses, então o mês mais antigo desta
    série está sempre entrando e saindo da janela conforme o tempo passa --
    ele aparece marcado com `parcial`, senão pareceria uma queda brusca no
    começo do gráfico todo santo mês.
    """
    hoje = hoje or _hoje()
    registros, cobertura = _carregar_datas(empresa_id)

    referencia = hoje.replace(day=1)
    chaves = []
    for _ in range(meses):
        chaves.append(referencia.strftime("%Y-%m"))
        referencia = (referencia - timedelta(days=1)).replace(day=1)
    chaves.reverse()

    contagem = {chave: 0 for chave in chaves}
    atiradores = {chave: set() for chave in chaves}
    for cpf, datas in registros:
        for data in datas:
            chave = data[:7]
            if chave in contagem:
                contagem[chave] += 1
                atiradores[chave].add(cpf)

    mes_atual = hoje.strftime("%Y-%m")
    return {
        "cobertura": cobertura,
        "meses": [
            {
                "mes": chave,
                "rotulo": _ROTULO_MES[int(chave[5:7]) - 1],
                "participacoes": contagem[chave],
                "atiradores": len(atiradores[chave]),
                "em_curso": chave == mes_atual,
                "parcial": chave == chaves[0],
            }
            for chave in chaves
        ],
    }


# `novos_filiados_por_mes()` (contagem por `criado_em`) viveu aqui por um
# dia. Foi removida em 2026-08-27, quando se descobriu que a resposta da
# API traz `affiliationDate`: quem responde "quantos filiados novos por
# mês" agora é `filiacoes_por_mes()`, no fim deste arquivo, pela data
# REAL de filiação. Manter as duas seria manter duas respostas diferentes
# para a mesma pergunta -- e a pior delas ainda precisava de um remendo
# para excluir o dia da carga inicial.


def resumo(empresa_id: str, hoje: Optional[date] = None) -> dict:
    """Os números de cabeçalho do bloco do clube."""
    hoje = hoje or _hoje()
    limite_sumido = (hoje - timedelta(days=DIAS_SUMIDO)).isoformat()

    con = conectar()
    try:
        linha = con.execute(
            "SELECT COUNT(*) AS ativos, "
            "SUM(CASE WHEN participacoes_12m IS NULL THEN 1 ELSE 0 END) AS sem_retrato, "
            "SUM(CASE WHEN participacoes_12m = 0 THEN 1 ELSE 0 END) AS sem_participacao, "
            "SUM(CASE WHEN ultima_participacao IS NOT NULL "
            "         AND ultima_participacao < ? THEN 1 ELSE 0 END) AS sumidos, "
            "MIN(sincronizado_em) AS retrato_mais_antigo, "
            "MAX(sincronizado_em) AS retrato_mais_recente "
            "FROM filiado WHERE empresa_id = ? AND status_filiacao = 'Ativo'",
            (limite_sumido, empresa_id),
        ).fetchone()

        inativos = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE empresa_id = ? AND status_filiacao = 'Inativo'",
            (empresa_id,),
        ).fetchone()[0]

        sumidos_lista = [
            dict(l) for l in con.execute(
                "SELECT nome, cpf, ultima_participacao FROM filiado "
                "WHERE empresa_id = ? AND status_filiacao = 'Ativo' "
                "AND ultima_participacao IS NOT NULL AND ultima_participacao < ? "
                "ORDER BY ultima_participacao LIMIT 5",
                (empresa_id, limite_sumido),
            ).fetchall()
        ]

        # Filiação do mês NÃO é contada aqui: é `filiacoes_por_mes()`, pela
        # data real de filiação. Este resumo já teve um `novos_no_mes` por
        # `criado_em` e ele saiu junto com a descoberta do affiliationDate.
    finally:
        con.close()

    return {
        "ativos": linha["ativos"] or 0,
        "inativos": inativos,
        "sem_retrato": linha["sem_retrato"] or 0,
        "sem_participacao": linha["sem_participacao"] or 0,
        "sumidos": linha["sumidos"] or 0,
        "sumidos_lista": sumidos_lista,
        "dias_sumido": DIAS_SUMIDO,
        "retrato_mais_antigo": linha["retrato_mais_antigo"],
        "retrato_mais_recente": linha["retrato_mais_recente"],
    }


if __name__ == "__main__":
    # Só a aritmética de janela -- não abre banco, não imprime dado de
    # ninguém. As funções que leem o banco real ficam para o usuário.
    hoje = _hoje()
    print(f"Hoje: {hoje.isoformat()}")
    print(f"Janela do gráfico por dia: {(hoje - timedelta(days=29)).isoformat()} a {hoje.isoformat()}")
    print(f"Corte de 'sumido': quem não aparece desde {(hoje - timedelta(days=DIAS_SUMIDO)).isoformat()}")
    referencia = hoje.replace(day=1)
    meses = []
    for _ in range(12):
        meses.append(referencia.strftime("%Y-%m"))
        referencia = (referencia - timedelta(days=1)).replace(day=1)
    print(f"Meses do gráfico: {' '.join(reversed(meses))}")


# ---------------------------------------------------------------------
# Financeiro do clube
#
# Tudo aqui sai da MESMA resposta que espelha a lista de filiados
# (GET /registers/shooters/paginate), sincronizada com `--somente-lista`:
# ~40 chamadas paginadas para o clube inteiro, contra as ~978 consultas
# uma-a-uma da habitualidade. É por isso que o Financeiro pode ser
# atualizado várias vezes ao dia e a habitualidade não.
#
# O QUE NÃO EXISTE AQUI, e não é esquecimento: valor pago, forma de
# pagamento e histórico de faturamento. O endpoint que devolveria isso em
# massa (GET /store/orders) responde HTTP 500 no ambiente do clube, em
# qualquer combinação de parâmetros. Enquanto o fornecedor não corrigir,
# o painel mostra SITUAÇÃO (em dia, vencendo, vencida) e não DINHEIRO.
# ---------------------------------------------------------------------

# Janelas do alerta de vencimento de anuidade. 30 dias é tempo de cobrar
# sem atropelar; 90 é o horizonte que deixa o mês seguinte previsível.
DIAS_VENCE_PROXIMO = 30
DIAS_VENCE_HORIZONTE = 90


def financeiro(empresa_id: str, hoje: Optional[date] = None) -> dict:
    """Situação de anuidade e de pendência do clube.

    **Dois campos que NÃO significam a mesma coisa**, e o painel mostra os
    dois separados de propósito: `anuidade_em_dia` é o status que o
    Shooting House calcula, e `anuidade_validade` é a data até quando ela
    vale. Eles discordam para uma parte dos filiados -- há quem esteja
    marcado em dia com a validade já passada. Sem saber a regra que o
    fornecedor usa, juntar os dois num número só seria inventar uma
    interpretação e apresentá-la como fato.
    """
    hoje = hoje or _hoje()
    proximo = (hoje + timedelta(days=DIAS_VENCE_PROXIMO)).isoformat()
    horizonte = (hoje + timedelta(days=DIAS_VENCE_HORIZONTE)).isoformat()

    con = conectar()
    try:
        linha = con.execute(
            "SELECT COUNT(*) AS ativos, "
            "SUM(anuidade_em_dia = 'Sim') AS em_dia, "
            "SUM(anuidade_em_dia = 'Não') AS em_atraso, "
            "SUM(anuidade_em_dia IS NULL) AS sem_dado, "
            "SUM(financeiro_em_dia = 'Não') AS pendencia_financeira, "
            "SUM(tem_pedido_aberto = 'Sim') AS comanda_aberta, "
            "SUM(anuidade_validade IS NOT NULL AND anuidade_validade < ?) AS vencida, "
            "SUM(anuidade_validade IS NOT NULL AND anuidade_validade >= ? "
            "    AND anuidade_validade < ?) AS vence_em_30, "
            "SUM(anuidade_validade IS NOT NULL AND anuidade_validade >= ? "
            "    AND anuidade_validade < ?) AS vence_em_90, "
            "SUM(anuidade_validade IS NULL) AS sem_validade, "
            "MAX(sincronizado_em) AS sincronizado_em "
            "FROM filiado WHERE empresa_id = ? AND status_filiacao = 'Ativo'",
            (hoje.isoformat(), hoje.isoformat(), proximo,
             hoje.isoformat(), horizonte, empresa_id),
        ).fetchone()

        # Quem vence primeiro aparece primeiro: é a fila de cobrança.
        vencendo = [
            dict(l) for l in con.execute(
                "SELECT nome, cpf, anuidade_validade, anuidade_em_dia FROM filiado "
                "WHERE empresa_id = ? AND status_filiacao = 'Ativo' "
                "AND anuidade_validade IS NOT NULL AND anuidade_validade < ? "
                "ORDER BY anuidade_validade LIMIT 8",
                (empresa_id, proximo),
            ).fetchall()
        ]

        # Validade do CR -- não é financeiro, mas é a mesma resposta da
        # API e é a informação que mais gera serviço para o despachante.
        cr = con.execute(
            "SELECT SUM(cr_validade IS NOT NULL AND cr_validade < ?) AS vencido, "
            "SUM(cr_validade IS NOT NULL AND cr_validade >= ? AND cr_validade < ?) AS vence_em_90, "
            "SUM(cr_validade IS NULL) AS sem_dado "
            "FROM filiado WHERE empresa_id = ? AND status_filiacao = 'Ativo'",
            (hoje.isoformat(), hoje.isoformat(), horizonte, empresa_id),
        ).fetchone()
    finally:
        con.close()

    saida = {chave: (linha[chave] or 0) for chave in linha.keys() if chave != "sincronizado_em"}
    saida["sincronizado_em"] = linha["sincronizado_em"]
    saida["dias_proximo"] = DIAS_VENCE_PROXIMO
    saida["dias_horizonte"] = DIAS_VENCE_HORIZONTE
    saida["vencendo_lista"] = vencendo
    saida["cr"] = {chave: (cr[chave] or 0) for chave in cr.keys()}
    # Percentual só existe se houver base, e "base" é gente com
    # informação -- não só gente cadastrada. Sem filiado ativo o
    # percentual seria uma afirmação sobre um clube que não tem ninguém;
    # com filiados mas nenhum deles tendo o campo preenchido, "0% em dia"
    # seria pior ainda: leria como "ninguém pagou" quando a verdade é
    # "não sei de ninguém". Os dois viram None, e a tela mostra travessão.
    #
    # O denominador continua sendo `ativos`, e não "quem tem informação":
    # a pergunta é "do meu clube, quanto está em dia", e quem não tem
    # informação também não está confirmado em dia. O quadro mostra
    # `sem_dado` ao lado para o número não parecer mais firme do que é.
    tem_informacao = saida["em_dia"] + saida["em_atraso"]
    saida["pct_em_dia"] = (
        round(saida["em_dia"] * 100 / saida["ativos"])
        if saida["ativos"] and tem_informacao else None
    )
    return saida


def filiacoes_por_mes(empresa_id: str, meses: int = 12,
                      hoje: Optional[date] = None) -> dict:
    """Novos filiados por mês pela data REAL de filiação.

    Substitui a contagem por `criado_em` (quando o sistema viu a pessoa),
    que precisava excluir o dia da carga inicial e ainda assim só valia
    daquele dia em diante. `affiliationDate` vem na resposta da API e dá o
    histórico verdadeiro -- o clube tem filiação registrada desde 2021.

    `sem_data` conta quem não tem a data preenchida: sem esse número, um
    mês baixo poderia ser cadastro incompleto em vez de mês fraco.
    """
    hoje = hoje or _hoje()
    con = conectar()
    try:
        linhas = con.execute(
            "SELECT SUBSTR(data_filiacao, 1, 7) AS mes, COUNT(*) AS total FROM filiado "
            "WHERE empresa_id = ? AND data_filiacao IS NOT NULL GROUP BY mes",
            (empresa_id,),
        ).fetchall()
        sem_data = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE empresa_id = ? AND data_filiacao IS NULL",
            (empresa_id,),
        ).fetchone()[0]
        total = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE empresa_id = ?", (empresa_id,)
        ).fetchone()[0]
    finally:
        con.close()

    por_mes = {l["mes"]: l["total"] for l in linhas}
    referencia = hoje.replace(day=1)
    chaves = []
    for _ in range(meses):
        chaves.append(referencia.strftime("%Y-%m"))
        referencia = (referencia - timedelta(days=1)).replace(day=1)
    chaves.reverse()

    mes_atual = hoje.strftime("%Y-%m")
    return {
        "sem_data": sem_data,
        "total": total,
        "meses": [
            {
                "mes": chave,
                "rotulo": _ROTULO_MES[int(chave[5:7]) - 1],
                "total": por_mes.get(chave, 0),
                "em_curso": chave == mes_atual,
            }
            for chave in chaves
        ],
    }
