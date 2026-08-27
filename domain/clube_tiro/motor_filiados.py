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
) -> None:
    """Grava o retrato. `erro` preenchido significa que a consulta falhou
    -- e nesse caso os números anteriores NÃO são apagados: um retrato
    velho e datado vale mais que nenhum, desde que a tela mostre a data."""
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
                "sincronizado_em = ?, sincronizacao_erro = NULL, atualizado_em = ? "
                "WHERE filiado_id = ? AND empresa_id = ?",
                (participacoes, ultima_participacao, agora, agora, filiado_id, empresa_id),
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


def listar_panorama(
    empresa_id: str, somente_ativos: bool = True, busca: Optional[str] = None
) -> list[dict]:
    """O panorama do clube, ordenado por quem precisa de atenção primeiro:
    nunca sincronizado, depois menos participações, depois quem está há
    mais tempo sem aparecer.

    `busca` casa com nome, CPF ou matrícula ao mesmo tempo -- mesmo padrão
    da tela de Clientes, uma caixa só em vez de um campo por coluna."""
    con = conectar()
    try:
        sql = (
            "SELECT filiado_id, nome, cpf, matricula, status_filiacao, "
            "participacoes_12m, ultima_participacao, sincronizado_em, "
            "sincronizacao_erro FROM filiado WHERE empresa_id = ?"
        )
        parametros = [empresa_id]
        if somente_ativos:
            sql += " AND status_filiacao = 'Ativo'"

        busca = (busca or "").strip()
        if busca:
            # Parênteses obrigatórios: sem eles o OR se espalharia por
            # cima do filtro de empresa, e a busca passaria a varrer o
            # banco inteiro (mesma armadilha já documentada em
            # webapp/app.py::clientes_lista).
            sql += " AND (nome LIKE ? OR cpf LIKE ? OR matricula LIKE ?)"
            curinga = f"%{busca}%"
            # O CPF é guardado só com dígitos. Sem isto, digitar
            # "123.456.789-00" -- que é como a própria tela mostra --
            # não acharia ninguém.
            digitos = re.sub(r"\D", "", busca)
            # Sem dígito nenhum na busca, usar o texto cru é seguro: ele
            # não casa com uma coluna que só tem número. Trocar por "%%"
            # aqui faria toda busca por nome devolver o clube inteiro.
            cpf_curinga = f"%{digitos}%" if digitos else curinga
            parametros += [curinga, cpf_curinga, curinga]

        sql += (
            " ORDER BY participacoes_12m IS NULL DESC, participacoes_12m ASC, "
            "ultima_participacao ASC"
        )
        return [dict(l) for l in con.execute(sql, parametros).fetchall()]
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
