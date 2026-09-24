"""Preenche `template` no banco de PRODUÇÃO, que nunca recebeu essa
tabela -- mesmo padrão de core.db.migrar_configuracoes_institucionais.

Achado em 2026-09-23 testando "quais os documentos para tirar o CR?" em
produção: `TypeError: sequence item 3: expected str instance, NoneType
found`. Causa: VW_SERVICO (core/db/views.sql) junta prazo_texto/valor_texto
com `LEFT JOIN template ON template_key = 'prazo_texto_servico'/
'valor_texto_servico'`. Sem essas duas linhas, o JOIN não acha nada e
`REPLACE(NULL, ...)` devolve NULL -- para QUALQUER serviço com prazo ou
valor cadastrado (não só o CR). `motor_ia/redator.py::montar_bloco_dados`
cola esse valor direto (`linhas.append(s["prazo_texto"])`, sem passar por
f-string), e o `"\\n".join(linhas)` final quebra na primeira vez que um
item da lista não é string.

As outras cinco chaves (resposta_concluido, resposta_em_analise,
resposta_documento_pendente, resposta_sem_processo,
mensagem_padrao_servico) não são lidas por nenhum código atual -- só o
próprio seed as escrevia, provavelmente resquício de uma fase anterior
do projeto, antes do Redator dinâmico. Inseridas aqui mesmo assim, só
pra produção não ficar divergente do banco local -- não corrigem bug
nenhum hoje, mas não custam nada.

Dado real de UMA empresa (valores exatamente iguais aos já usados
localmente desde a migração original da planilha) -- por isso recebe o
empresa_id por linha de comando (padrão EMP-000001, mesmo padrão de
core.db.gerar_clientes_ficticios).

Idempotente -- roda sobre banco em uso. Cada template_key só é inserida
se ainda não existir para a empresa.

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_templates_producao [empresa_id]`
"""
import sys

from core.conexao import conectar
from core.motor_empresas import EMPRESA_PADRAO

# (template_key, nome, categoria, conteudo) -- mesmo texto de
# core/db/migrate_dados_teste.py.
TEMPLATES = [
    ("resposta_sem_processo", "Resposta: sem processo", "processo",
     "Não localizei processo vinculado."),
    ("resposta_em_analise", "Resposta: em análise", "processo",
     "Processo em análise."),
    ("resposta_documento_pendente", "Resposta: documento pendente", "processo",
     "Documentação pendente."),
    ("resposta_concluido", "Resposta: concluído", "processo",
     "Processo concluído."),
    ("mensagem_padrao_servico", "Mensagem padrão de serviço", "servico",
     "Localizei o serviço de {nome_servico}."),
    # Estas duas são as que quebravam VW_SERVICO -- prioridade real.
    ("prazo_texto_servico", "Texto de prazo do serviço", "servico",
     "Prazo médio de {prazo_estimado_dias} dias."),
    ("valor_texto_servico", "Texto de valor do serviço", "servico",
     "Valor de referência: R$ {valor_referencia}."),
]


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def main(empresa_id: str = EMPRESA_PADRAO) -> None:
    con = conectar(empresa_id)
    try:
        chaves_existentes = {
            r[0] for r in con.execute(
                "SELECT template_key FROM template WHERE empresa_id = ?", (empresa_id,)
            )
        }

        inseridas = []
        for template_key, nome, categoria, conteudo in TEMPLATES:
            if template_key in chaves_existentes:
                continue
            template_id = _proximo_id(con, "template", "template_id", "TPL")
            con.execute(
                "INSERT INTO template (template_id, empresa_id, template_key, nome, "
                "categoria, conteudo, canal, ativo) VALUES (?,?,?,?,?,?,?,?)",
                (template_id, empresa_id, template_key, nome, categoria, conteudo, None, "Sim"),
            )
            chaves_existentes.add(template_key)
            inseridas.append(template_key)
        con.commit()

        if inseridas:
            print(f"Inseridas {len(inseridas)} template(s) novo(s): {', '.join(inseridas)}")
        else:
            print("Nenhum template novo a inserir (todos já existiam).")
    finally:
        con.close()


if __name__ == "__main__":
    empresa = sys.argv[1] if len(sys.argv) > 1 else EMPRESA_PADRAO
    main(empresa)
