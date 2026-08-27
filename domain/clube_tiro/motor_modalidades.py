"""Motor de Modalidades: o catálogo do clube, espelhado do Shooting House.

Catálogo, não dado de pessoa -- é a única leitura da integração que não
traz nome, CPF ou histórico de ninguém. Por isso pode ser sincronizado à
vontade e exibido inteiro na tela.

Serve a `resultado_campeonato.modalidade`, que continua sendo TEXTO: os
resultados já cadastrados foram digitados à mão, e transformar a coluna
em FK quebraria todos eles. O catálogo vira sugestão, não obrigação.

Como o banco de Domínio é anexado, ele não passa pelas views do Core:
**todo WHERE aqui leva empresa_id escrito à mão.**
"""
from datetime import datetime, timezone
from typing import Optional

from domain.clube_tiro.motor_filiados import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(modalidade_id, 5) AS INTEGER)) FROM modalidade"
    ).fetchone()[0] or 0
    return f"MOD-{maior + 1:06d}"


def salvar_catalogo(empresa_id: str, grupos: list) -> dict:
    """Espelha o catálogo inteiro numa transação.

    O que sai do catálogo do clube vira `ativo='Não'`, nunca DELETE: pode
    haver resultado antigo mencionando aquela modalidade, e apagar
    deixaria a tela sem como explicar de onde veio o texto. É a mesma
    escolha de `sincronizar_lista`, que também não apaga filiado.
    """
    agora = _agora_iso()
    con = conectar()
    try:
        vistas = set()
        novas = atualizadas = 0
        for grupo in grupos:
            for modalidade in grupo.get("modalidades") or []:
                chave = (grupo.get("grupo_id"), modalidade["id"])
                vistas.add(chave)
                existente = con.execute(
                    "SELECT modalidade_id FROM modalidade WHERE empresa_id = ? "
                    "AND grupo_id_sh IS ? AND modalidade_id_sh = ?",
                    (empresa_id, grupo.get("grupo_id"), modalidade["id"]),
                ).fetchone()
                if existente:
                    con.execute(
                        "UPDATE modalidade SET grupo = ?, nome = ?, ativo = 'Sim', "
                        "sincronizado_em = ? WHERE modalidade_id = ? AND empresa_id = ?",
                        (grupo["grupo"], modalidade["nome"], agora,
                         existente["modalidade_id"], empresa_id),
                    )
                    atualizadas += 1
                else:
                    con.execute(
                        "INSERT INTO modalidade (modalidade_id, empresa_id, grupo_id_sh, "
                        "grupo, modalidade_id_sh, nome, ativo, sincronizado_em) "
                        "VALUES (?,?,?,?,?,?,'Sim',?)",
                        (_proximo_id(con), empresa_id, grupo.get("grupo_id"),
                         grupo["grupo"], modalidade["id"], modalidade["nome"], agora),
                    )
                    novas += 1

        desativadas = 0
        for linha in con.execute(
            "SELECT modalidade_id, grupo_id_sh, modalidade_id_sh FROM modalidade "
            "WHERE empresa_id = ? AND ativo = 'Sim'", (empresa_id,),
        ).fetchall():
            if (linha["grupo_id_sh"], linha["modalidade_id_sh"]) not in vistas:
                con.execute(
                    "UPDATE modalidade SET ativo = 'Não', sincronizado_em = ? "
                    "WHERE modalidade_id = ? AND empresa_id = ?",
                    (agora, linha["modalidade_id"], empresa_id),
                )
                desativadas += 1

        con.commit()
        return {"novas": novas, "atualizadas": atualizadas,
                "desativadas": desativadas, "sincronizado_em": agora}
    finally:
        con.close()


def listar(empresa_id: str, somente_ativas: bool = True,
           busca: Optional[str] = None) -> list[dict]:
    """O catálogo em ordem de grupo e nome, pronto para a tela."""
    query = "SELECT * FROM modalidade WHERE empresa_id = ?"
    params: list = [empresa_id]
    if somente_ativas:
        query += " AND ativo = 'Sim'"
    if busca:
        # Parênteses em volta do OR: sem eles o OR passaria por cima do
        # filtro de empresa (o mesmo erro que a busca de clientes já teve).
        query += " AND (nome LIKE ? OR grupo LIKE ?)"
        curinga = f"%{busca}%"
        params.extend([curinga, curinga])
    query += " ORDER BY grupo COLLATE NOCASE, nome COLLATE NOCASE"

    con = conectar()
    try:
        return [dict(l) for l in con.execute(query, params).fetchall()]
    finally:
        con.close()


def agrupado(empresa_id: str, busca: Optional[str] = None) -> dict:
    """O mesmo catálogo já em grupos, que é como a tela mostra.

    Agrupar aqui e não no JavaScript é o padrão do projeto (o Consultor
    faz igual com o checklist): a tela desenha o que recebe, e a forma do
    dado é decidida onde o dado mora.
    """
    linhas = listar(empresa_id, busca=busca)
    grupos: dict = {}
    for linha in linhas:
        grupos.setdefault(linha["grupo"], []).append(
            {"nome": linha["nome"], "modalidade_id_sh": linha["modalidade_id_sh"]}
        )
    con = conectar()
    try:
        sincronizado = con.execute(
            "SELECT MAX(sincronizado_em) FROM modalidade WHERE empresa_id = ?",
            (empresa_id,),
        ).fetchone()[0]
        total = con.execute(
            "SELECT COUNT(*) FROM modalidade WHERE empresa_id = ? AND ativo = 'Sim'",
            (empresa_id,),
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "grupos": [{"grupo": nome, "modalidades": itens} for nome, itens in grupos.items()],
        "total": total,
        "mostrando": len(linhas),
        "sincronizado_em": sincronizado,
    }


def nomes(empresa_id: str) -> list:
    """Só os nomes distintos, para a lista de sugestões do formulário de
    resultado. Distintos porque a mesma modalidade ("Pistola") aparece em
    vários grupos, e a sugestão repetida três vezes só atrapalha."""
    con = conectar()
    try:
        return [
            l[0] for l in con.execute(
                "SELECT DISTINCT nome FROM modalidade WHERE empresa_id = ? "
                "AND ativo = 'Sim' ORDER BY nome COLLATE NOCASE",
                (empresa_id,),
            ).fetchall()
        ]
    finally:
        con.close()
