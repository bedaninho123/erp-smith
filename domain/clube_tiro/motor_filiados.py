"""Motor de Filiados: a lista de quem passou pelo clube, espelhada do
Shooting House, com o retrato de habitualidade de cada um.

Serve ao panorama do clube -- "quem está atrasado, e há quanto tempo".
NÃO serve para afirmar nada: os números aqui são uma cópia com data de
validade, e quem responde "sua habitualidade está em dia?" continua sendo
a consulta ao vivo (o Portal já faz isso). Ver o comentário da tabela
`filiado` em domain/clube_tiro/db/schema.sql.

Como o banco de Domínio é anexado, ele não passa pelas views do Core que
se filtram sozinhas: **todo WHERE aqui leva empresa_id escrito à mão.**
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor_ia.conexao import DOMAIN_DB

# Janela usada para contar participações. Doze meses corridos, contados
# de hoje para trás -- é a leitura mais conservadora de "a cada 12 meses"
# e a única que não depende de saber a data do CR de cada pessoa.
#
# É contagem, não veredito: o sistema NÃO diz se alguém cumpriu o mínimo
# legal. Isso depende do nível do CR (Decreto nº 11.615/2023, art. 35 --
# 8, ou 12+4, ou 20+6), e a API do Shooting House não expõe o nível de
# ninguém. Inventar um critério aqui poderia dizer a um atirador que ele
# está em dia quando não está, e isso custa o CR dele.
JANELA_MESES = 12

# Ordenações oferecidas na tela. Lista controlada em código, nunca texto
# vindo da requisição: `ORDER BY` não aceita parâmetro do SQLite, então o
# valor entra por interpolação -- e interpolar o que o navegador mandou
# seria injeção de SQL. Quem pedir uma chave que não está aqui recebe o
# padrão.
#
# "IS NULL" antes do campo é o que decide de que lado os vazios caem. Em
# SQLite, NULL ordena antes de tudo por padrão, e sem isso "quem nunca
# participou" apareceria misturado com "quem participou ontem".
ORDENACOES = {
    # Padrão: quem participou mais recentemente primeiro. Quem nunca
    # participou vai pro fim (é o que "mais atualizados" quer dizer).
    "recentes": "ultima_participacao IS NULL, ultima_participacao DESC",
    "antigos": "ultima_participacao IS NULL DESC, ultima_participacao ASC",
    # A ordenação original da tela: quem precisa de atenção primeiro.
    "atencao": (
        "participacoes_12m IS NULL DESC, participacoes_12m ASC, "
        "ultima_participacao ASC"
    ),
    "mais_participacoes": "participacoes_12m IS NULL, participacoes_12m DESC",
    "nome": "nome COLLATE NOCASE ASC",
    # Retrato mais velho primeiro -- útil pra saber se a sincronização
    # está dando conta do rodízio.
    "retrato_antigo": "sincronizado_em IS NULL DESC, sincronizado_em ASC",
}
ORDENACAO_PADRAO = "recentes"

# Faixas de participação oferecidas como filtro. Também lista controlada:
# vira um trecho de SQL, então não pode vir do navegador.
FAIXAS_PARTICIPACAO = {
    "sem_nenhuma": "participacoes_12m = 0",
    "1_a_7": "participacoes_12m BETWEEN 1 AND 7",
    "8_a_11": "participacoes_12m BETWEEN 8 AND 11",
    "12_a_19": "participacoes_12m BETWEEN 12 AND 19",
    "20_ou_mais": "participacoes_12m >= 20",
    # Diferente de "sem nenhuma": aqui ninguém consultou, então não se
    # sabe. É a distinção que a tela inteira protege.
    "nao_consultado": "participacoes_12m IS NULL",
}


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conectar():
    con = sqlite3.connect(DOMAIN_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(filiado_id, 5) AS INTEGER)) FROM filiado"
    ).fetchone()[0] or 0
    return f"FIL-{maior + 1:06d}"


def salvar_filiado(empresa_id: str, dados: dict) -> str:
    """Insere ou atualiza pelo par (empresa_id, cpf).

    Atualiza só os campos de identificação -- nunca zera o retrato de
    habitualidade. Sincronizar a lista de filiados e sincronizar a
    habitualidade são rodadas separadas, e a primeira não pode apagar o
    trabalho da segunda.
    """
    con = conectar()
    try:
        agora = _agora_iso()
        existente = con.execute(
            "SELECT filiado_id FROM filiado WHERE empresa_id = ? AND cpf = ?",
            (empresa_id, dados["cpf"]),
        ).fetchone()

        if existente:
            con.execute(
                "UPDATE filiado SET idatirador = ?, matricula = ?, nome = ?, "
                "email = ?, status_filiacao = ?, atualizado_em = ? "
                "WHERE filiado_id = ? AND empresa_id = ?",
                (dados.get("idatirador"), dados.get("matricula"), dados["nome"],
                 dados.get("email"), dados.get("status_filiacao"), agora,
                 existente["filiado_id"], empresa_id),
            )
            con.commit()
            return existente["filiado_id"]

        filiado_id = _proximo_id(con)
        con.execute(
            "INSERT INTO filiado (filiado_id, empresa_id, idatirador, matricula, "
            "nome, cpf, email, status_filiacao, criado_em, atualizado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (filiado_id, empresa_id, dados.get("idatirador"), dados.get("matricula"),
             dados["nome"], dados["cpf"], dados.get("email"),
             dados.get("status_filiacao"), agora, agora),
        )
        con.commit()
        return filiado_id
    finally:
        con.close()


def registrar_habitualidade(
    empresa_id: str, filiado_id: str, participacoes: Optional[int],
    ultima_participacao: Optional[str], erro: Optional[str] = None,
    datas: Optional[list] = None,
) -> None:
    """Grava o retrato. `erro` preenchido significa que a consulta falhou
    -- e nesse caso os números anteriores NÃO são apagados: um retrato
    velho e datado vale mais que nenhum, desde que a tela mostre a data.

    `datas` REESCREVE a lista da pessoa por inteiro, nunca soma na que
    estava lá. É isso que faz o gráfico por dia se corrigir sozinho a
    cada passagem do rodízio (ver o comentário da coluna no schema);
    acumular duplicaria a mesma participação a cada sincronização.
    """
    con = conectar()
    try:
        if erro:
            con.execute(
                "UPDATE filiado SET sincronizacao_erro = ?, atualizado_em = ? "
                "WHERE filiado_id = ? AND empresa_id = ?",
                (erro, _agora_iso(), filiado_id, empresa_id),
            )
        else:
            agora = _agora_iso()
            con.execute(
                "UPDATE filiado SET participacoes_12m = ?, ultima_participacao = ?, "
                "participacoes_datas = ?, sincronizado_em = ?, sincronizacao_erro = NULL, "
                "atualizado_em = ? WHERE filiado_id = ? AND empresa_id = ?",
                (participacoes, ultima_participacao,
                 json.dumps(datas) if datas is not None else None,
                 agora, agora, filiado_id, empresa_id),
            )
        con.commit()
    finally:
        con.close()


def proximos_a_sincronizar(empresa_id: str, limite: int) -> list[dict]:
    """Quem está há mais tempo sem sincronizar vem primeiro (NULL antes de
    tudo). É o que faz uma rodada limitada rodar por todo mundo com o
    tempo, em vez de reprocessar sempre os mesmos."""
    con = conectar()
    try:
        linhas = con.execute(
            "SELECT filiado_id, cpf, nome FROM filiado "
            "WHERE empresa_id = ? AND status_filiacao = 'Ativo' "
            "ORDER BY sincronizado_em IS NOT NULL, sincronizado_em ASC LIMIT ?",
            (empresa_id, limite),
        ).fetchall()
        return [dict(l) for l in linhas]
    finally:
        con.close()


def contar_participacoes(habitualidade: dict, hoje=None) -> tuple[int, Optional[str]]:
    """Conta participações dentro da janela e devolve a data da última.

    Conta em Python, nunca na IA -- data é aritmética. O formato de
    entrada é o normalizado por integracoes/shooting_house.py
    (dd/mm/aaaa, já sem a hora).
    """
    hoje = hoje or datetime.now().date()
    limite = hoje - timedelta(days=365 * JANELA_MESES // 12)

    datas = []
    for grupo in (habitualidade.get("habitualidades") or {}).values():
        for evento in grupo.get("eventos", []):
            bruto = evento.get("data_participacao")
            if not bruto:
                continue
            try:
                datas.append(datetime.strptime(bruto, "%d/%m/%Y").date())
            except ValueError:
                # Data em formato inesperado não vira contagem errada:
                # é ignorada, e a divergência aparece no total.
                continue

    if not datas:
        return 0, None
    dentro = [d for d in datas if d >= limite]
    return len(dentro), max(datas).strftime("%Y-%m-%d")


def datas_participacao(habitualidade: dict, hoje=None) -> list:
    """As datas das participações dentro da janela, em 'AAAA-MM-DD'.

    Função irmã de `contar_participacoes` de propósito, em vez de mudar o
    retorno daquela: ela é chamada em outros lugares e tem teste próprio,
    e trocar a assinatura de uma função de contagem para devolver mais
    coisa é como bugs entram em código que já funcionava.

    Devolve a lista COM repetição -- duas participações no mesmo dia são
    dois eventos, e é isso que o gráfico por dia precisa somar. Quem quer
    "em quantos dias distintos essa pessoa apareceu" usa set() em cima.
    """
    hoje = hoje or datetime.now().date()
    limite = hoje - timedelta(days=365 * JANELA_MESES // 12)

    datas = []
    for grupo in (habitualidade.get("habitualidades") or {}).values():
        for evento in grupo.get("eventos", []):
            bruto = evento.get("data_participacao")
            if not bruto:
                continue
            try:
                data = datetime.strptime(bruto, "%d/%m/%Y").date()
            except ValueError:
                # Mesma escolha de contar_participacoes: data em formato
                # inesperado é ignorada, nunca vira data errada no gráfico.
                continue
            if data >= limite:
                datas.append(data.strftime("%Y-%m-%d"))
    return sorted(datas)


def listar_panorama(
    empresa_id: str,
    somente_ativos: bool = True,
    busca: Optional[str] = None,
    situacao: Optional[str] = None,
    faixa: Optional[str] = None,
    participou_de: Optional[str] = None,
    participou_ate: Optional[str] = None,
    ordenar_por: Optional[str] = None,
) -> list[dict]:
    """O panorama do clube, com os filtros da tela.

    `busca` casa com nome, CPF ou matrícula ao mesmo tempo -- mesmo padrão
    da tela de Clientes, uma caixa só em vez de um campo por coluna.

    `situacao` ('Ativo'/'Inativo'/None) substitui `somente_ativos` quando
    vem preenchida; `somente_ativos` continua existindo porque a rota e os
    testes antigos usam, e mudá-lo seria quebrar chamada de fora à toa.

    `participou_de`/`participou_ate` são ISO (YYYY-MM-DD) e comparam com
    `ultima_participacao`, que é guardada no mesmo formato -- comparação
    de texto funciona porque ISO ordena igual à data.
    """
    con = conectar()
    try:
        sql = (
            "SELECT filiado_id, nome, cpf, matricula, status_filiacao, "
            "participacoes_12m, ultima_participacao, sincronizado_em, "
            "sincronizacao_erro FROM filiado WHERE empresa_id = ?"
        )
        parametros = [empresa_id]

        if situacao in ("Ativo", "Inativo"):
            sql += " AND status_filiacao = ?"
            parametros.append(situacao)
        elif situacao is None and somente_ativos:
            sql += " AND status_filiacao = 'Ativo'"

        if faixa in FAIXAS_PARTICIPACAO:
            sql += f" AND {FAIXAS_PARTICIPACAO[faixa]}"

        # Quem nunca participou tem ultima_participacao NULL e some de
        # qualquer filtro por período -- o que é o certo: ele não
        # participou DENTRO do período pedido.
        if participou_de:
            sql += " AND ultima_participacao >= ?"
            parametros.append(participou_de)
        if participou_ate:
            sql += " AND ultima_participacao <= ?"
            parametros.append(participou_ate)

        # Cada PALAVRA vira uma condição, e todas precisam casar. Sem
        # isso, "felipe b" procurava esse texto como um bloco só e não
        # achava "Felipe de Moura Bedani" -- que é como nome de gente é
        # cadastrado de verdade, com preposição no meio.
        #
        # Palavras somam (AND) em vez de alternarem (OR) porque cada
        # palavra digitada é um pedaço a mais de certeza: quem escreve
        # "felipe b" quer estreitar, não alargar.
        for palavra in (busca or "").split():
            # Parênteses obrigatórios: sem eles o OR se espalharia por
            # cima do filtro de empresa, e a busca passaria a varrer o
            # banco inteiro (mesma armadilha já documentada em
            # webapp/app.py::clientes_lista).
            sql += " AND (nome LIKE ? OR cpf LIKE ? OR matricula LIKE ?)"
            curinga = f"%{palavra}%"
            # O CPF é guardado só com dígitos. Sem isto, digitar
            # "123.456.789-00" -- que é como a própria tela mostra --
            # não acharia ninguém.
            digitos = re.sub(r"\D", "", palavra)
            # Sem dígito nenhum na palavra, usar o texto cru é seguro:
            # ele não casa com uma coluna que só tem número. Trocar por
            # "%%" faria toda busca por nome devolver o clube inteiro.
            cpf_curinga = f"%{digitos}%" if digitos else curinga
            parametros += [curinga, cpf_curinga, curinga]

        ordem = ORDENACOES.get(ordenar_por or "", ORDENACOES[ORDENACAO_PADRAO])
        sql += f" ORDER BY {ordem}"
        return [dict(l) for l in con.execute(sql, parametros).fetchall()]
    finally:
        con.close()


def obter_por_cpf(empresa_id: str, cpf: Optional[str]) -> Optional[dict]:
    """O filiado com este CPF, ou None se a pessoa nunca passou pelo clube.

    É a ponte entre as duas populações: `core.cliente` (quem o despachante
    atende) e `dominio.filiado` (quem passou pelo clube). Não há FK ligando
    os dois -- são bancos diferentes -- então a ligação é feita aqui, pelo
    CPF, que é a única chave que os dois lados têm em comum.

    None é resposta normal, não erro: cliente do despachante que nunca foi
    filiado do clube é caso corriqueiro (transferência de arma, por
    exemplo)."""
    digitos = re.sub(r"\D", "", cpf or "")
    if len(digitos) != 11:
        return None
    con = conectar()
    try:
        linha = con.execute(
            "SELECT * FROM filiado WHERE empresa_id = ? AND cpf = ?",
            (empresa_id, digitos),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def cpfs_de_filiados(empresa_id: str, somente_ativos: bool = False) -> set:
    """Só os CPFs, para marcar em lote quem é filiado sem uma consulta por
    linha. Usado ao montar a lista de clientes do despachante.

    O padrão inclui INATIVO de propósito: na lista de clientes, quem
    saiu do clube continua sendo alguém que passou por lá, e a etiqueta
    tem que aparecer. O Dashboard pede `somente_ativos=True` porque lá a
    pergunta é outra -- "de quem está no clube HOJE, quantos eu atendo?"
    -- e misturar ex-filiado afundaria o percentual sem motivo.
    """
    con = conectar()
    try:
        query = "SELECT cpf FROM filiado WHERE empresa_id = ?"
        if somente_ativos:
            query += " AND status_filiacao = 'Ativo'"
        return {l[0] for l in con.execute(query, (empresa_id,))}
    finally:
        con.close()


def resumo_do_clube(empresa_id: str) -> dict:
    """Números de cabeçalho da tela. `sincronizado_em` mais antigo entra
    de propósito: é ele que diz o quanto o panorama pode estar velho."""
    con = conectar()
    try:
        linha = con.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN participacoes_12m IS NULL THEN 1 ELSE 0 END) AS sem_dado, "
            "SUM(CASE WHEN participacoes_12m = 0 THEN 1 ELSE 0 END) AS sem_participacao, "
            "MIN(sincronizado_em) AS mais_antigo, MAX(sincronizado_em) AS mais_recente "
            "FROM filiado WHERE empresa_id = ? AND status_filiacao = 'Ativo'",
            (empresa_id,),
        ).fetchone()
        return dict(linha)
    finally:
        con.close()
