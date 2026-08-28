"""Motor de Indicadores: os números do Dashboard, calculados aqui e não
na tela.

Regra que vale para o arquivo inteiro: **nenhum número é inventado.**
Onde o banco não sabe responder, a função devolve `None` -- nunca zero.
Zero significa "consultei e não teve"; `None` significa "não sei". Num
gráfico os dois viram a mesma barra baixinha, e é assim que um painel
começa a mentir. Mesma regra que já vale para `filiado.participacoes_12m`
e para o Consultor do Motor IA.

Duas decisões de leitura que valem para todo o módulo:

1. **Mês em curso não se compara com mês fechado.** No dia 5, agosto
   sempre pareceria um desastre contra julho inteiro. Toda comparação é
   contra o MESMO PEDAÇO do mês anterior (dia 1 até o mesmo dia do mês),
   e é por isso que `_recorte_mes` existe.
2. **As duas pontas falam relógios diferentes.** O banco grava instante
   em UTC (`_agora_iso()` em todo motor do Core); quem olha a tela pensa
   em dia LOCAL. Todo recorte por dia ou por mês converte a coluna com
   `_dia_local()` / `_mes_local()` antes de comparar -- comparar direto
   fazia o caso encerrado às 21h de Brasília cair no dia seguinte, e
   sumir de "concluídos neste mês" justamente no fim do expediente, que
   é quando se encerra caso. Pelo mesmo motivo não se usa `date('now')`
   do SQLite, que também é UTC.

Este módulo é genérico de propósito -- lê só tabela do Core (caso,
processo, servico, mensagem, log_ia). Número de clube de tiro (filiado,
habitualidade) vive em `domain/clube_tiro/motor_indicadores_clube.py`,
porque um escritório de advocacia nunca vai ter um.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from core.conexao import conectar

# Um caso "parado" é o que está esperando o cliente há tempo demais. 15
# dias é o padrão porque é mais que o tempo de uma pessoa juntar
# documento e menos que o tempo de ela esquecer que contratou.
DIAS_PARA_PARADO = 15

# Janela do alerta de prazo: o que vence dentro de uma semana ainda dá
# para resolver; o que vence hoje já é tarde.
DIAS_PRAZO_PROXIMO = 7

# Status que tiram o caso da fila viva. Mesma lista usada pelas telas.
STATUS_FORA_DA_FILA = ("Encerrado", "Cancelado")


def _hoje() -> date:
    """A data local da máquina -- é ela que decide o que é "este mês"
    para quem está olhando a tela."""
    return date.today()


def _fuso_local() -> str:
    """O deslocamento desta máquina no formato de modificador do SQLite
    (ex.: '-180 minutes'), para traduzir instante UTC em dia local dentro
    da própria consulta.

    Em minutos, e não em horas, porque existe fuso de meia hora -- e vem
    do relógio da máquina, nunca de um número fixo no código: um '-3
    horas' escrito aqui seria uma decisão de fuso horário escondida
    dentro de um motor de indicadores.
    """
    minutos = int(datetime.now().astimezone().utcoffset().total_seconds() // 60)
    return f"{minutos} minutes"


def _dia_local(coluna: str) -> str:
    """Trecho de SQL com o DIA local de uma coluna que guarda instante
    UTC. Consome um `?` -- o chamador põe `_fuso_local()` na tupla, na
    mesma posição."""
    return f"SUBSTR(datetime({coluna}, ?), 1, 10)"


def _mes_local(coluna: str) -> str:
    """Como `_dia_local`, mas o MÊS (AAAA-MM). Sem isto o caso encerrado
    às 21h30 do dia 31 entraria no mês seguinte do gráfico."""
    return f"SUBSTR(datetime({coluna}, ?), 1, 7)"


def _iso(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dias_atras(dias: int) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=dias))


def _recorte_mes(hoje: date) -> dict:
    """Os dois recortes que toda comparação usa: o mês em curso até hoje,
    e o mesmo número de dias do mês anterior.

    Devolve limites em texto ISO já prontos para o WHERE, e o rótulo de
    cada um para a tela poder dizer contra o que está comparando.
    """
    inicio_atual = hoje.replace(day=1)
    fim_atual = hoje + timedelta(days=1)  # exclusivo, inclui o dia de hoje

    ultimo_do_anterior = inicio_atual - timedelta(days=1)
    inicio_anterior = ultimo_do_anterior.replace(day=1)
    # O mesmo dia do mês anterior, sem estourar em mês curto: dia 31 de
    # março comparado com fevereiro vira o fim de fevereiro, não um erro.
    dia_equivalente = min(hoje.day, ultimo_do_anterior.day)
    fim_anterior = inicio_anterior.replace(day=dia_equivalente) + timedelta(days=1)

    return {
        "atual": (inicio_atual.isoformat(), fim_atual.isoformat()),
        "anterior": (inicio_anterior.isoformat(), fim_anterior.isoformat()),
        "rotulo_atual": inicio_atual.strftime("%m/%Y"),
        "rotulo_anterior": inicio_anterior.strftime("%m/%Y"),
        "dias_corridos": hoje.day,
        "dia_equivalente": dia_equivalente,
    }


def _contar_no_periodo(con, empresa_id: str, coluna: str, de: str, ate: str,
                       extra: str = "") -> int:
    """O recorte é por DIA e a coluna guarda instante ISO completo, então
    os dois lados precisam ter o mesmo comprimento -- daí o SUBSTR de
    `_dia_local`, que de quebra traz o instante UTC para o dia de quem
    está olhando a tela."""
    fuso = _fuso_local()
    return con.execute(
        f"SELECT COUNT(*) FROM caso WHERE empresa_id = ? AND ativo = 'Sim' "
        f"AND {coluna} IS NOT NULL AND {_dia_local(coluna)} >= ? "
        f"AND {_dia_local(coluna)} < ? {extra}",
        (empresa_id, fuso, de, fuso, ate),
    ).fetchone()[0]


def resumo(empresa_id: str, hoje: Optional[date] = None) -> dict:
    """Tudo que o Dashboard mostra do lado do despachante, numa conexão só."""
    hoje = hoje or _hoje()
    recorte = _recorte_mes(hoje)
    de_atual, ate_atual = recorte["atual"]
    de_anterior, ate_anterior = recorte["anterior"]

    con = conectar(empresa_id)
    try:
        concluidos = _contar_no_periodo(con, empresa_id, "encerrado_em", de_atual, ate_atual)
        concluidos_antes = _contar_no_periodo(
            con, empresa_id, "encerrado_em", de_anterior, ate_anterior
        )
        abertos_periodo = _contar_no_periodo(con, empresa_id, "criado_em", de_atual, ate_atual)
        abertos_antes = _contar_no_periodo(
            con, empresa_id, "criado_em", de_anterior, ate_anterior
        )

        return {
            "periodo": recorte,
            "concluidos": {"valor": concluidos, "anterior": concluidos_antes},
            "abertos": {"valor": abertos_periodo, "anterior": abertos_antes},
            "tempo_medio_dias": _tempo_medio(con, empresa_id, recorte),
            "encerrados_sem_data": _encerrados_sem_data(con, empresa_id),
            "em_andamento": _valor_em_andamento(con, empresa_id),
            "atendimento": _atendimento(con, empresa_id, de_atual, ate_atual),
            "casos_por_mes": _casos_por_mes(con, empresa_id, hoje),
            "fila_por_status": _fila_por_status(con, empresa_id),
            "valor_por_servico": _valor_por_servico(con, empresa_id),
            "origem": _origem(con, empresa_id, de_atual, ate_atual),
            "ia": _consumo_ia(con, empresa_id, de_atual, ate_atual),
            "alertas": _alertas(con, empresa_id, hoje),
        }
    finally:
        con.close()


def _tempo_medio(con, empresa_id: str, recorte: dict) -> dict:
    """Dias entre abrir e encerrar, média dos casos encerrados no período.

    Devolve None quando não houve encerramento no recorte -- média de
    conjunto vazio não é zero, e "0 dias" leria como instantâneo.
    """
    fuso = _fuso_local()

    def _media(de: str, ate: str) -> Optional[float]:
        valor = con.execute(
            "SELECT AVG(julianday(encerrado_em) - julianday(criado_em)) FROM caso "
            "WHERE empresa_id = ? AND ativo = 'Sim' AND encerrado_em IS NOT NULL "
            f"AND {_dia_local('encerrado_em')} >= ? AND {_dia_local('encerrado_em')} < ?",
            (empresa_id, fuso, de, fuso, ate),
        ).fetchone()[0]
        return round(valor, 1) if valor is not None else None

    return {
        "valor": _media(*recorte["atual"]),
        "anterior": _media(*recorte["anterior"]),
    }


def _encerrados_sem_data(con, empresa_id: str) -> int:
    """Casos encerrados antes de `encerrado_em` passar a ser preenchido e
    sem rastro no histórico para a migração recuperar. Ficam de fora de
    toda contagem por período, e a tela avisa em vez de fingir que não
    existem (ver core/db/migrar_encerrado_em.py)."""
    return con.execute(
        "SELECT COUNT(*) FROM caso WHERE empresa_id = ? AND ativo = 'Sim' "
        "AND status = 'Encerrado' AND encerrado_em IS NULL",
        (empresa_id,),
    ).fetchone()[0]


def _valor_em_andamento(con, empresa_id: str) -> dict:
    """Soma de `servico.valor_referencia` dos processos que ainda correm.

    É VALOR DE TABELA, não receita: o sistema não registra o que foi
    cobrado nem o que foi pago. Por isso vem com `estimativa: True` e a
    contagem de processos sem valor cadastrado -- sem ela, um catálogo
    meio preenchido devolveria um total baixo com cara de exato.
    """
    linha = con.execute(
        "SELECT COUNT(*) AS processos, "
        "SUM(CASE WHEN s.valor_referencia IS NULL THEN 1 ELSE 0 END) AS sem_valor, "
        "COALESCE(SUM(s.valor_referencia), 0) AS total "
        "FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = p.empresa_id "
        "WHERE p.empresa_id = ? AND p.status NOT IN ('Concluído', 'Cancelado')",
        (empresa_id,),
    ).fetchone()
    return {
        "estimativa": True,
        "total": linha["total"] or 0,
        "processos": linha["processos"] or 0,
        "sem_valor": linha["sem_valor"] or 0,
    }


def _atendimento(con, empresa_id: str, de: str, ate: str) -> dict:
    """Quanto o assistente deu conta sozinho.

    `precisa_humano` é o campo certo para isso, e não `status_processamento`:
    com a revisão humana ligada TODA resposta passa por aprovação, então
    contar 'Enviado' misturaria "a IA resolveu" com "você aprovou". O
    campo diz o que o pipeline decidiu na hora, independente do freio.
    """
    fuso = _fuso_local()
    linha = con.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN precisa_humano = 'Não' THEN 1 ELSE 0 END) AS sozinha, "
        "SUM(CASE WHEN precisa_humano = 'Sim' THEN 1 ELSE 0 END) AS com_humano, "
        "SUM(CASE WHEN status_processamento = 'Aguardando Revisão' THEN 1 ELSE 0 END) AS na_fila "
        "FROM mensagem WHERE empresa_id = ? "
        f"AND {_dia_local('data_hora')} >= ? AND {_dia_local('data_hora')} < ?",
        (empresa_id, fuso, de, fuso, ate),
    ).fetchone()

    total = linha["total"] or 0
    sozinha = linha["sozinha"] or 0
    return {
        "total": total,
        "sozinha": sozinha,
        "com_humano": linha["com_humano"] or 0,
        "na_fila": linha["na_fila"] or 0,
        # Sem mensagem no período não existe percentual -- 0% leria como
        # "a IA não resolveu nada", que é uma afirmação diferente.
        "pct_sozinha": round(sozinha * 100 / total) if total else None,
    }


def _casos_por_mes(con, empresa_id: str, hoje: date, meses: int = 12) -> list[dict]:
    """Série de 12 meses, com o mês em curso marcado.

    Os meses saem de uma lista montada em Python, não de um GROUP BY: mês
    sem nenhum caso precisa aparecer como barra zerada, e o GROUP BY
    simplesmente não devolveria a linha -- o gráfico fecharia o buraco e
    mostraria uma sequência que não aconteceu.
    """
    referencia = hoje.replace(day=1)
    chaves = []
    for _ in range(meses):
        chaves.append(referencia.strftime("%Y-%m"))
        referencia = (referencia - timedelta(days=1)).replace(day=1)
    chaves.reverse()

    fuso = _fuso_local()

    def _por_mes(coluna: str) -> dict:
        return {
            r["mes"]: r["total"] for r in con.execute(
                f"SELECT {_mes_local(coluna)} AS mes, COUNT(*) AS total FROM caso "
                f"WHERE empresa_id = ? AND ativo = 'Sim' AND {coluna} IS NOT NULL "
                f"AND {_mes_local(coluna)} >= ? GROUP BY mes",
                (fuso, empresa_id, fuso, chaves[0]),
            ).fetchall()
        }

    abertos, concluidos = _por_mes("criado_em"), _por_mes("encerrado_em")
    mes_atual = hoje.strftime("%Y-%m")
    return [
        {
            "mes": chave,
            "rotulo": _ROTULO_MES[int(chave[5:7]) - 1],
            "abertos": abertos.get(chave, 0),
            "concluidos": concluidos.get(chave, 0),
            "em_curso": chave == mes_atual,
        }
        for chave in chaves
    ]


_ROTULO_MES = ("jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez")


def _fila_por_status(con, empresa_id: str) -> list[dict]:
    """A fila viva, do maior para o menor, com quantos estão parados há
    mais de DIAS_PARA_PARADO dias dentro de cada status."""
    limite = _dias_atras(DIAS_PARA_PARADO)
    linhas = con.execute(
        "SELECT status, COUNT(*) AS total, "
        "SUM(CASE WHEN atualizado_em < ? THEN 1 ELSE 0 END) AS parados "
        "FROM caso WHERE empresa_id = ? AND ativo = 'Sim' "
        f"AND status NOT IN ({','.join('?' * len(STATUS_FORA_DA_FILA))}) "
        "GROUP BY status ORDER BY total DESC",
        (limite, empresa_id, *STATUS_FORA_DA_FILA),
    ).fetchall()
    return [dict(l) for l in linhas]


def _valor_por_servico(con, empresa_id: str) -> list[dict]:
    """Onde está o valor de tabela dos processos em andamento."""
    linhas = con.execute(
        "SELECT s.nome_servico, COUNT(*) AS processos, "
        "COALESCE(SUM(s.valor_referencia), 0) AS total, "
        "(s.valor_referencia IS NULL) AS sem_valor "
        "FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = p.empresa_id "
        "WHERE p.empresa_id = ? AND p.status NOT IN ('Concluído', 'Cancelado') "
        "GROUP BY s.service_id ORDER BY total DESC, processos DESC",
        (empresa_id,),
    ).fetchall()
    return [dict(l) for l in linhas]


def _origem(con, empresa_id: str, de: str, ate: str) -> list[dict]:
    """Por onde a mensagem chegou no período."""
    fuso = _fuso_local()
    linhas = con.execute(
        "SELECT canal, COUNT(*) AS total FROM mensagem WHERE empresa_id = ? "
        f"AND {_dia_local('data_hora')} >= ? AND {_dia_local('data_hora')} < ? "
        "GROUP BY canal ORDER BY total DESC",
        (empresa_id, fuso, de, fuso, ate),
    ).fetchall()
    total = sum(l["total"] for l in linhas)
    return [
        {"canal": l["canal"], "total": l["total"],
         "pct": round(l["total"] * 100 / total) if total else 0}
        for l in linhas
    ]


def _consumo_ia(con, empresa_id: str, de: str, ate: str) -> dict:
    """Chamadas e tokens no período.

    Deliberadamente SEM valor em reais: o preço por token é do
    fornecedor, muda sem avisar e não está cadastrado em lugar nenhum do
    sistema. Um "R$ 47" com preço chutado dentro do código seria o tipo
    de número que ninguém confere e todo mundo repete.
    """
    fuso = _fuso_local()
    linha = con.execute(
        "SELECT COUNT(*) AS chamadas, "
        "COALESCE(SUM(tokens_entrada), 0) AS tokens_entrada, "
        "COALESCE(SUM(tokens_saida), 0) AS tokens_saida, "
        "SUM(CASE WHEN resultado = 'Erro' THEN 1 ELSE 0 END) AS erros "
        "FROM log_ia WHERE empresa_id = ? "
        f"AND {_dia_local('criado_em')} >= ? AND {_dia_local('criado_em')} < ?",
        (empresa_id, fuso, de, fuso, ate),
    ).fetchone()
    return {
        "chamadas": linha["chamadas"] or 0,
        "tokens_entrada": linha["tokens_entrada"] or 0,
        "tokens_saida": linha["tokens_saida"] or 0,
        "erros": linha["erros"] or 0,
    }


def _alertas(con, empresa_id: str, hoje: date) -> dict:
    """O que o painel deveria estar cutucando. Cada alerta traz a lista
    curta junto do total -- número sozinho não diz por onde começar."""
    limite_parado = _dias_atras(DIAS_PARA_PARADO)
    parados = con.execute(
        "SELECT c.caso_id, c.titulo, c.atualizado_em, cl.nome AS cliente_nome "
        "FROM caso c "
        "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = c.empresa_id "
        "WHERE c.empresa_id = ? AND c.ativo = 'Sim' AND c.status = 'Aguardando cliente' "
        "AND c.atualizado_em < ? ORDER BY c.atualizado_em",
        (empresa_id, limite_parado),
    ).fetchall()

    # Valor de tabela preso nesses casos -- é o que transforma "19 casos
    # parados" em uma decisão.
    valor_parado = con.execute(
        "SELECT COALESCE(SUM(s.valor_referencia), 0) FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = p.empresa_id "
        "JOIN caso c ON c.caso_id = p.caso_id AND c.empresa_id = p.empresa_id "
        "WHERE p.empresa_id = ? AND p.status NOT IN ('Concluído', 'Cancelado') "
        "AND c.status = 'Aguardando cliente' AND c.atualizado_em < ?",
        (empresa_id, limite_parado),
    ).fetchone()[0]

    prazo = con.execute(
        "SELECT p.processo_id, p.prazo_estimado, p.caso_id, s.nome_servico, "
        "cl.nome AS cliente_nome FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id AND s.empresa_id = p.empresa_id "
        "JOIN cliente cl ON cl.cliente_id = p.cliente_id AND cl.empresa_id = p.empresa_id "
        "WHERE p.empresa_id = ? AND p.status NOT IN ('Concluído', 'Cancelado') "
        "AND p.prazo_estimado IS NOT NULL AND SUBSTR(p.prazo_estimado, 1, 10) < ? "
        "ORDER BY p.prazo_estimado",
        (empresa_id, (hoje + timedelta(days=DIAS_PRAZO_PROXIMO)).isoformat()),
    ).fetchall()

    return {
        "dias_para_parado": DIAS_PARA_PARADO,
        "dias_prazo": DIAS_PRAZO_PROXIMO,
        "parados": {
            "total": len(parados),
            "valor": valor_parado or 0,
            "lista": [dict(l) for l in parados[:5]],
        },
        "prazo": {
            "total": len(prazo),
            "lista": [dict(l) for l in prazo[:5]],
        },
    }


if __name__ == "__main__":
    # Só a aritmética de recorte -- não abre banco, não imprime dado de
    # ninguém. O resumo() completo lê o banco real e fica para o usuário.
    hoje = _hoje()
    recorte = _recorte_mes(hoje)
    print(f"Hoje: {hoje.isoformat()}")
    print(f"  Mês em curso : {recorte['atual'][0]} até {recorte['atual'][1]} (exclusivo)")
    print(f"  Comparação   : {recorte['anterior'][0]} até {recorte['anterior'][1]} (exclusivo)")
    print(f"  Ou seja: {recorte['dias_corridos']} dias de {recorte['rotulo_atual']} "
          f"contra os {recorte['dia_equivalente']} primeiros dias de {recorte['rotulo_anterior']}.")
    print()
    for teste in [date(2026, 3, 31), date(2026, 1, 5), date(2026, 12, 31)]:
        r = _recorte_mes(teste)
        print(f"  {teste} -> compara com {r['anterior'][0]}..{r['anterior'][1]}")
