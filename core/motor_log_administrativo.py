"""Log administrativo: registro append-only de mudança de papel,
permissão e ativo de usuário, e de configuração da empresa. Mesmo
espírito de core/motor_casos.py::_registrar_historico (evento de negócio
do Caso), mas pra ação de gestão -- sem isso, "quem desligou a revisão
humana" ou "quem tirou a permissão da Ana" não tinha resposta nenhuma
(achado na auditoria de riscos de 2026-07-30).

`registrar()` recebe a conexão já aberta pelo chamador (como
_registrar_historico) -- o registro do log entra na MESMA transação da
mudança em si, então os dois sempre acontecem juntos ou nenhum dos dois
acontece.

Desde 2026-08-27 alimenta a tela "Auditoria" do painel (só Gestor, sem
entrada no catálogo de permissões -- é área administrativa, como
Configurações). Antes disso só dava pra ler com SELECT na mão, o que na
prática significa que ninguém lia: o registro existia e não respondia
pergunta nenhuma.

**Ninguém edita nem apaga daqui.** Registro que a própria pessoa
auditada pode alterar não audita nada -- por isso a tela é só leitura, e
não existe rota de escrita neste módulo além de `registrar()`.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def registrar(
    con, empresa_id: str, tipo_evento: str, alvo: str, descricao: str,
    valor_anterior: Optional[str], valor_novo: Optional[str], criado_por: str,
) -> None:
    novo_id = _proximo_id(con, "log_administrativo", "log_administrativo_id", "ADM")
    con.execute(
        "INSERT INTO log_administrativo (log_administrativo_id, empresa_id, "
        "tipo_evento, alvo, descricao, valor_anterior, valor_novo, criado_em, criado_por) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (novo_id, empresa_id, tipo_evento, alvo, descricao,
         valor_anterior, valor_novo, _agora_iso(), criado_por),
    )


def listar(
    empresa_id: str, limite: int = 200,
    tipo_evento: Optional[str] = None, busca: Optional[str] = None,
) -> list[dict]:
    """Do mais recente pro mais antigo -- num registro append-only, o que
    acabou de acontecer é sempre o que se está procurando.

    `busca` varre alvo, descrição e autor de uma vez: quem abre esta tela
    normalmente sabe UMA coisa (o nome de quem mexeu, ou o cliente
    afetado) e não em qual coluna ela está guardada.
    """
    query = "SELECT * FROM log_administrativo WHERE empresa_id = ?"
    params: list = [empresa_id]
    if tipo_evento:
        query += " AND tipo_evento = ?"
        params.append(tipo_evento)
    if busca:
        # Os parênteses em volta do OR não são estilo: sem eles o OR
        # passaria por cima do filtro de empresa e a busca traria linha
        # da empresa vizinha (o mesmo erro que tests/test_isolamento_painel
        # já pegou uma vez na busca de clientes).
        query += " AND (alvo LIKE ? OR descricao LIKE ? OR criado_por LIKE ?)"
        curinga = f"%{busca}%"
        params.extend([curinga, curinga, curinga])
    query += " ORDER BY criado_em DESC LIMIT ?"
    params.append(limite)

    con = conectar(empresa_id)
    try:
        return [dict(l) for l in con.execute(query, params).fetchall()]
    finally:
        con.close()


def tipos_registrados(empresa_id: str) -> list[str]:
    """Só os tipos que a empresa realmente tem no registro -- uma lista
    fixa em código ofereceria filtro que não devolve nada, e esconderia
    um tipo novo que alguém acrescentar depois."""
    con = conectar(empresa_id)
    try:
        return [
            r[0] for r in con.execute(
                "SELECT DISTINCT tipo_evento FROM log_administrativo "
                "WHERE empresa_id = ? ORDER BY tipo_evento",
                (empresa_id,),
            ).fetchall()
        ]
    finally:
        con.close()


def contar_acessos_negados(empresa_id: str, dias: int = 7) -> int:
    """Quantas vezes o portão de identidade recusou uma consulta a dado
    sensível na janela recente.

    É o número que dá motivo pra alguém abrir esta tela. Um acesso negado
    isolado é rotina (cliente errou o CPF); uma sequência deles é o sinal
    mais visível de alguém tentando adivinhar CPF de outra pessoa
    (CLAUDE.md, portão de identidade).
    """
    con = conectar(empresa_id)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM log_administrativo WHERE empresa_id = ? "
            "AND tipo_evento = 'ACESSO_DADO_SENSIVEL' AND valor_novo LIKE 'negado%' "
            # strftime com o MESMO formato de _agora_iso(), não datetime():
            # datetime() devolve "2026-08-20 14:00:00" (espaço), criado_em
            # guarda "2026-08-20T14:00:00Z" (T e Z), e comparar os dois como
            # texto erra no limite da janela -- 'T' é maior que ' '.
            # 'now' aqui é UTC, que é o mesmo fuso de criado_em.
            "AND criado_em >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (empresa_id, f"-{int(dias)} day"),
        ).fetchone()[0]
    finally:
        con.close()
