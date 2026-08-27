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


def novos_filiados_por_mes(empresa_id: str, meses: int = 12,
                           hoje: Optional[date] = None) -> dict:
    """Quantos filiados apareceram pela primeira vez em cada mês.

    RESSALVA que precisa viajar junto com o número, e por isso vem no
    retorno: `criado_em` é quando NÓS vimos a pessoa pela primeira vez,
    não quando ela se filiou ao clube -- a API não devolve data de
    filiação. A carga inicial trouxe o clube inteiro num dia só, e esse
    dia aparece como `dia_da_carga`: é um pico de importação, não de
    crescimento. A partir dele o número é honesto, com defasagem de
    algumas horas (o tempo até a próxima rodada do rodízio).
    """
    hoje = hoje or _hoje()
    con = conectar()
    try:
        # O dia com mais primeiras aparições de toda a base é a carga
        # inicial. Detectado, não chutado: assim continua certo mesmo que
        # a base seja recriada em outra data.
        carga = con.execute(
            "SELECT SUBSTR(criado_em, 1, 10) AS dia, COUNT(*) AS total FROM filiado "
            "WHERE empresa_id = ? GROUP BY dia ORDER BY total DESC LIMIT 1",
            (empresa_id,),
        ).fetchone()

        linhas = con.execute(
            "SELECT SUBSTR(criado_em, 1, 7) AS mes, COUNT(*) AS total FROM filiado "
            "WHERE empresa_id = ? GROUP BY mes",
            (empresa_id,),
        ).fetchall()
    finally:
        con.close()

    por_mes = {l["mes"]: l["total"] for l in linhas}

    referencia = hoje.replace(day=1)
    chaves = []
    for _ in range(meses):
        chaves.append(referencia.strftime("%Y-%m"))
        referencia = (referencia - timedelta(days=1)).replace(day=1)
    chaves.reverse()

    dia_carga = carga["dia"] if carga else None
    mes_carga = dia_carga[:7] if dia_carga else None
    mes_atual = hoje.strftime("%Y-%m")

    return {
        "dia_da_carga": dia_carga,
        "total_da_carga": carga["total"] if carga else 0,
        "meses": [
            {
                "mes": chave,
                "rotulo": _ROTULO_MES[int(chave[5:7]) - 1],
                "total": por_mes.get(chave, 0),
                "em_curso": chave == mes_atual,
                # O mês da carga inicial não é crescimento do clube, é o
                # dia em que o sistema conheceu todo mundo de uma vez.
                "carga_inicial": chave == mes_carga,
            }
            for chave in chaves
        ],
    }


def _dia_da_carga(con, empresa_id: str) -> Optional[str]:
    """O dia em que mais gente apareceu pela primeira vez -- a carga
    inicial. Detectado, não chutado, para continuar certo se a base for
    recriada em outra data."""
    linha = con.execute(
        "SELECT SUBSTR(criado_em, 1, 10) AS dia, COUNT(*) AS total FROM filiado "
        "WHERE empresa_id = ? GROUP BY dia ORDER BY total DESC LIMIT 1",
        (empresa_id,),
    ).fetchone()
    return linha["dia"] if linha else None


def resumo(empresa_id: str, hoje: Optional[date] = None) -> dict:
    """Os números de cabeçalho do bloco do clube."""
    hoje = hoje or _hoje()
    limite_sumido = (hoje - timedelta(days=DIAS_SUMIDO)).isoformat()
    inicio_mes = hoje.replace(day=1).isoformat()

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

        # A carga inicial trouxe o clube inteiro num dia só. Se esse dia
        # cai no mês corrente, contá-lo aqui diria "1.525 novos filiados
        # este mês" -- e o número que mais interessa ao dono viraria o
        # mais errado da tela. Fica de fora, e a tela diz que ficou.
        dia_carga = _dia_da_carga(con, empresa_id)
        novos_no_mes = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE empresa_id = ? "
            "AND SUBSTR(criado_em, 1, 10) >= ? AND SUBSTR(criado_em, 1, 10) != ?",
            (empresa_id, inicio_mes, dia_carga or ""),
        ).fetchone()[0]
        carga_no_mes = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE empresa_id = ? "
            "AND SUBSTR(criado_em, 1, 10) = ? AND SUBSTR(criado_em, 1, 10) >= ?",
            (empresa_id, dia_carga or "", inicio_mes),
        ).fetchone()[0]
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
        "novos_no_mes": novos_no_mes,
        # Quantos do mês vieram da carga inicial e por isso NÃO entraram
        # na contagem acima -- a tela precisa poder explicar o buraco.
        "carga_no_mes": carga_no_mes,
        "dia_da_carga": dia_carga,
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
