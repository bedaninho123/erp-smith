"""Rastreamento de documento recebido vs. exigido, por processo. Estado
do Core, sem IA -- a marcação de que um arquivo recebido atende a um
item do checklist (documento_exigido) é sempre feita por uma pessoa no
painel, nunca inferida automaticamente: decidir "este PDF é a certidão
X" é julgamento humano/regra de negócio, não algo que a IA decide (ver
CLAUDE.md, "a IA nunca contém regra de negócio").
"""
from datetime import datetime, timezone

from core.conexao import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(documento_checklist_id, 5) AS INTEGER)) FROM documento_checklist"
    ).fetchone()[0] or 0
    return f"DCK-{maior + 1:06d}"


def status_checklist(con, processo_id: str) -> list:
    """Itens exigidos pelo serviço do processo + quais documentos já foram
    marcados atendendo cada um. Aceita uma conexão já aberta (chamado de
    dentro de webapp/app.py, que já tem uma pra montar o resto da tela de
    Detalhe do Caso) -- não abre/fecha conexão própria, diferente de
    marcar_documento()/desmarcar()."""
    linha = con.execute(
        "SELECT servico_id FROM processo WHERE processo_id = ?", (processo_id,)
    ).fetchone()
    if not linha:
        raise ValueError(f"Processo não encontrado: {processo_id}")
    servico_id = linha["servico_id"]

    itens = con.execute(
        "SELECT documento_exigido_id, grupo, item, ordem FROM documento_exigido "
        "WHERE servico_id = ? AND ativo = 'Sim' ORDER BY ordem",
        (servico_id,),
    ).fetchall()

    resultado = []
    for item in itens:
        marcados = con.execute(
            "SELECT dck.documento_checklist_id, dck.documento_id, d.nome_arquivo "
            "FROM documento_checklist dck "
            "JOIN documento d ON d.documento_id = dck.documento_id "
            "WHERE dck.processo_id = ? AND dck.documento_exigido_id = ?",
            (processo_id, item["documento_exigido_id"]),
        ).fetchall()
        resultado.append({
            "documento_exigido_id": item["documento_exigido_id"],
            "grupo": item["grupo"],
            "item": item["item"],
            "ordem": item["ordem"],
            "recebido": bool(marcados),
            "documentos": [dict(m) for m in marcados],
        })
    return resultado


def marcar_documento(
    processo_id: str, documento_exigido_id: str, documento_id: str,
    marcado_por: str = "Painel administrativo",
) -> str:
    con = conectar()
    try:
        processo = con.execute(
            "SELECT servico_id FROM processo WHERE processo_id = ?", (processo_id,)
        ).fetchone()
        if not processo:
            raise ValueError(f"Processo não encontrado: {processo_id}")

        existe_item = con.execute(
            "SELECT 1 FROM documento_exigido WHERE documento_exigido_id = ? AND servico_id = ?",
            (documento_exigido_id, processo["servico_id"]),
        ).fetchone()
        if not existe_item:
            raise ValueError("Este item de checklist não pertence ao serviço deste processo.")

        existe_documento = con.execute(
            "SELECT 1 FROM documento WHERE documento_id = ?", (documento_id,)
        ).fetchone()
        if not existe_documento:
            raise ValueError(f"Documento não encontrado: {documento_id}")

        ja_marcado = con.execute(
            "SELECT 1 FROM documento_checklist "
            "WHERE processo_id = ? AND documento_exigido_id = ? AND documento_id = ?",
            (processo_id, documento_exigido_id, documento_id),
        ).fetchone()
        if ja_marcado:
            raise ValueError("Este documento já está marcado para este item.")

        novo_id = _proximo_id(con)
        con.execute(
            "INSERT INTO documento_checklist VALUES (?,?,?,?,?,?)",
            (novo_id, processo_id, documento_exigido_id, documento_id, _agora_iso(), marcado_por),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


def desmarcar(documento_checklist_id: str) -> None:
    con = conectar()
    try:
        existe = con.execute(
            "SELECT 1 FROM documento_checklist WHERE documento_checklist_id = ?",
            (documento_checklist_id,),
        ).fetchone()
        if not existe:
            raise ValueError(f"Marcação não encontrada: {documento_checklist_id}")
        con.execute(
            "DELETE FROM documento_checklist WHERE documento_checklist_id = ?",
            (documento_checklist_id,),
        )
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    con = conectar()
    try:
        processo = con.execute("SELECT processo_id FROM processo LIMIT 1").fetchone()
        if not processo:
            print("Nenhum processo cadastrado para testar.")
        else:
            status = status_checklist(con, processo["processo_id"])
            print(f"Checklist de {processo['processo_id']}: {len(status)} itens.")
            for item in status:
                marca = "recebido" if item["recebido"] else "faltando"
                print(f"  [{marca}] {item['item']}")
    finally:
        con.close()
