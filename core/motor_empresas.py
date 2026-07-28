"""Motor de Empresas: a raiz do multi-tenant (docs/schema_multi_tenant.md).

Único módulo do Core que trabalha por cima de `conectar_admin()`, e o
motivo é circular por natureza: não dá para abrir uma conexão amarrada a
uma empresa antes dessa empresa existir. Todo o resto do Core usa
`conectar(empresa_id)`.

Deliberadamente pequeno: cadastro de empresa nova pelo painel
(onboarding, serviços padrão, configuração inicial) está fora do escopo
desta fase -- ver docs/schema_multi_tenant.md §9. Aqui só existe o
necessário para os scripts de dados criarem e conferirem a empresa.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar_admin

# A Smith, primeira e (por enquanto) única empresa do sistema. Os scripts
# de dados usam esta constante como padrão para não repetir o literal em
# quatro arquivos diferentes.
EMPRESA_PADRAO = "EMP-000001"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(empresa_id, 5) AS INTEGER)) FROM empresa"
    ).fetchone()[0] or 0
    return f"EMP-{maior + 1:06d}"


def criar_empresa(nome: str, dominio: str, empresa_id: Optional[str] = None) -> str:
    """Cria uma empresa e devolve o empresa_id.

    empresa_id explícito existe só para o bootstrap: a Smith precisa ser
    EMP-000001 porque é assim que ela aparece em todo o dado migrado e
    nos testes de fumaça dos módulos. No uso normal, deixe em branco e o
    ID sai do mesmo gerador do resto do projeto.
    """
    con = conectar_admin()
    try:
        novo_id = empresa_id or _proximo_id(con)
        ja_existe = con.execute(
            "SELECT 1 FROM empresa WHERE empresa_id = ?", (novo_id,)
        ).fetchone()
        if ja_existe:
            raise ValueError(f"Empresa já existe: {novo_id}")
        con.execute(
            "INSERT INTO empresa (empresa_id, nome, dominio, ativo, criado_em) "
            "VALUES (?,?,?,?,?)",
            (novo_id, nome, dominio, "Sim", _agora_iso()),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def obter_empresa(empresa_id: str) -> Optional[dict]:
    con = conectar_admin()
    try:
        linha = con.execute(
            "SELECT * FROM empresa WHERE empresa_id = ?", (empresa_id,)
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def listar_empresas(apenas_ativas: bool = True) -> list:
    con = conectar_admin()
    try:
        query = "SELECT * FROM empresa"
        if apenas_ativas:
            query += " WHERE ativo = 'Sim'"
        query += " ORDER BY empresa_id"
        return [dict(row) for row in con.execute(query).fetchall()]
    finally:
        con.close()


def exigir_empresa(empresa_id: str) -> dict:
    """Devolve a empresa ou explode com uma mensagem que diz o que fazer.

    Os scripts de dados chamam isto antes de inserir qualquer coisa: sem
    empresa, todo INSERT quebraria depois na FK, com um erro do SQLite
    que não ajuda ninguém a entender que faltou rodar o passo anterior.
    """
    empresa = obter_empresa(empresa_id)
    if not empresa:
        raise SystemExit(
            f"Empresa {empresa_id} não existe neste banco.\n"
            "Crie o banco e a empresa antes de popular os dados:\n"
            "  .venv\\Scripts\\python.exe -m core.db.criar_banco\n"
            "  .venv\\Scripts\\python.exe -m core.db.migrate_dados_teste"
        )
    return empresa


if __name__ == "__main__":
    for empresa in listar_empresas(apenas_ativas=False):
        print(f"{empresa['empresa_id']}  {empresa['nome']}  "
              f"(domínio: {empresa['dominio']}, ativa: {empresa['ativo']})")
