"""Permite que um documento pertença ao CLIENTE, e não a um caso.

O problema: `documento` nasceu com `CHECK (caso_id IS NOT NULL OR
processo_id IS NOT NULL)` -- todo arquivo tinha que estar preso a um
atendimento. Isso está certo para o comprovante que o cliente mandou num
caso específico, e errado para o CR dele: o CR é da pessoa, vale por
anos, atravessa vários casos e continua valendo quando todos fecharem.

A solução é uma categoria explícita:

    'Caso'   -> documento de um atendimento. Continua exigindo caso ou
                processo, exatamente como antes.
    'Dossiê' -> documento permanente da pessoa (CR, CRAF, comprovante de
                residência, laudos). Não tem caso, e é ERRADO que tenha.

O CHECK novo cobre os dois e não deixa zona cinzenta: dossiê com caso
preenchido é recusado pelo banco, e documento de caso sem caso também.

POR QUE RECONSTRUIR A TABELA: o SQLite não sabe remover um CHECK. O
caminho é o oficial da documentação deles -- criar a tabela nova, copiar,
apagar a velha, renomear -- com `foreign_keys` desligado durante a troca
(senão `documento_checklist`, que aponta para cá, bloqueia o DROP) e uma
verificação de integridade no fim, antes do commit.

Idempotente: se a coluna `categoria` já existe, não faz nada.

    .venv\\Scripts\\python.exe -m core.db.migrar_dossie_cliente
"""
from core.conexao import conectar_admin

TABELA_NOVA = """
CREATE TABLE documento_nova (
    documento_id      TEXT PRIMARY KEY,
    empresa_id        TEXT NOT NULL REFERENCES empresa(empresa_id),
    cliente_id        TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id           TEXT REFERENCES caso(caso_id),
    processo_id       TEXT REFERENCES processo(processo_id),
    tipo_documento    TEXT NOT NULL,
    nome_arquivo      TEXT,
    link_arquivo      TEXT,
    status            TEXT NOT NULL,
    data_envio        TEXT,
    data_validade     TEXT,
    revisado_por_id   TEXT REFERENCES usuario(usuario_id),
    observacoes       TEXT,
    mensagem_id       TEXT REFERENCES mensagem(mensagem_id),
    -- 'Caso' (documento de um atendimento) | 'Dossiê' (documento
    -- permanente da pessoa). Lista controlada em código, como o resto do
    -- projeto -- ver core/motor_documentos.py.
    categoria         TEXT NOT NULL DEFAULT 'Caso',
    CHECK (
        (categoria = 'Dossiê' AND caso_id IS NULL AND processo_id IS NULL)
        OR
        (categoria = 'Caso' AND (caso_id IS NOT NULL OR processo_id IS NOT NULL))
    )
);
"""

INDICES = (
    "CREATE INDEX idx_documento_empresa_id ON documento(empresa_id)",
    "CREATE INDEX idx_documento_cliente_id ON documento(cliente_id)",
    "CREATE INDEX idx_documento_caso_id ON documento(caso_id)",
    "CREATE INDEX idx_documento_processo_id ON documento(processo_id)",
    # Novo: a tela do dossiê lê sempre por (cliente, categoria).
    "CREATE INDEX idx_documento_categoria ON documento(empresa_id, cliente_id, categoria)",
)


def migrar() -> dict:
    con = conectar_admin()
    try:
        colunas = {c[1] for c in con.execute("PRAGMA table_info(documento)")}
        if "categoria" in colunas:
            total = con.execute("SELECT COUNT(*) FROM documento").fetchone()[0]
            return {"migrada": False, "documentos": total}

        antes = con.execute("SELECT COUNT(*) FROM documento").fetchone()[0]

        con.isolation_level = None
        # Desligado só durante a troca: com ele ligado, a FK de
        # documento_checklist impediria apagar a tabela antiga.
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN")
        try:
            # execute(), NUNCA executescript(): o executescript faz
            # COMMIT implícito antes de rodar, o que encerraria a
            # transação aberta duas linhas acima -- e aí o resto da
            # migração rodaria solto, sem nada para desfazer se falhasse.
            con.execute(TABELA_NOVA)
            con.execute(
                "INSERT INTO documento_nova (documento_id, empresa_id, cliente_id, "
                "caso_id, processo_id, tipo_documento, nome_arquivo, link_arquivo, "
                "status, data_envio, data_validade, revisado_por_id, observacoes, "
                "mensagem_id, categoria) "
                "SELECT documento_id, empresa_id, cliente_id, caso_id, processo_id, "
                "tipo_documento, nome_arquivo, link_arquivo, status, data_envio, "
                "data_validade, revisado_por_id, observacoes, mensagem_id, 'Caso' "
                "FROM documento"
            )
            con.execute("DROP TABLE documento")
            con.execute("ALTER TABLE documento_nova RENAME TO documento")
            for indice in INDICES:
                con.execute(indice)

            # Antes de fechar: nenhuma FK pode ter ficado pendurada. Se
            # ficou, a migração inteira volta atrás.
            quebradas = con.execute("PRAGMA foreign_key_check").fetchall()
            if quebradas:
                con.execute("ROLLBACK")
                return {"migrada": False, "erro": f"{len(quebradas)} referência(s) quebrada(s)"}
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.execute("PRAGMA foreign_keys = ON")

        depois = con.execute("SELECT COUNT(*) FROM documento").fetchone()[0]
        return {"migrada": True, "documentos": depois, "antes": antes}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    if saida.get("erro"):
        print(f"FALHOU: {saida['erro']}. Nada foi alterado.")
        raise SystemExit(1)
    if not saida["migrada"]:
        print(f"A coluna 'categoria' já existe -- nada a fazer. "
              f"({saida['documentos']} documento(s) na tabela.)")
    else:
        print("Tabela documento reconstruída com a categoria 'Dossiê'.")
        print(f"  Documentos preservados: {saida['antes']} -> {saida['documentos']}")
        print("  Todos os existentes entraram como categoria 'Caso'.")
