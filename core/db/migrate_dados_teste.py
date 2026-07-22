"""Migra os dados de teste reais da planilha 'Banco de Dados - Clube de Tiro.xlsx'
para core/db/erp_smith.db. Decisões desta migração (aprovadas com o usuário em 2026-07-22):
  - IDs de teste com 3 dígitos convertidos para 6 (ex.: CLI-001 -> CLI-000001).
  - 47 linhas duplicadas 'TEMP-000001' em Casos foram descartadas (lixo de teste).
  - Linha CLI-000004 (sem nome/cpf) foi descartada.
  - Processos 2 e 3 não tinham Caso na planilha original (caso_id é campo novo) ->
    foram criados 2 Casos sintéticos (CAS-000002, CAS-000003) para viabilizar a migração.
  - Usuários USR-000001 (Felipe) e USR-000002 (Ana) foram criados a partir dos nomes
    soltos em processo.responsavel/documento.revisado_por; não existe aba Usuários na planilha.
  - conversa.iniciada_em/ultima_mensagem_em reconstruídos (planilha tinha texto
    literal "data atual", não uma data real).
  - template: os 7 campos de texto-padrão tirados de servico (2ª rodada) viram
    7 linhas de template (4 fixas + 3 com marcador {campo}).
"""
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "core/db/erp_smith.db"


def excel_to_iso(serial: float) -> str:
    dt = datetime(1899, 12, 30) + timedelta(days=serial)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    # 1) cliente
    cur.executemany(
        "INSERT INTO cliente VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("CLI-000001", "Felipe Bedani", "12345678900", "bedaninho123@gmail.com",
             "5514999990001", "Marília", "Ativo", "Sim",
             excel_to_iso(46204.0), excel_to_iso(46216.791666666664),
             "Cliente de teste principal."),
            ("CLI-000002", "João da Silva", "98765432100", "joao.teste@example.com",
             "5514999990002", "Bauru", "Ativo", "Sim",
             excel_to_iso(46193.0), excel_to_iso(46213.604166666664),
             "Aguardando documento."),
            ("CLI-000003", "Maria Oliveira", "45678912300", "maria.teste@example.com",
             "5514999990003", "Assis", "Inativo", "Não",
             excel_to_iso(46157.0), excel_to_iso(46203.385416666664),
             "Atendimento humano obrigatório."),
        ],
    )

    # 2) usuario (inferidos; não existe aba Usuários na planilha)
    cur.executemany(
        "INSERT INTO usuario VALUES (?,?,?,?,?,?,?)",
        [
            ("USR-000001", "Felipe", "bedaninho123@gmail.com", "Despachante",
             "Despachante", "Sim", "2026-07-22T00:00:00Z"),
            ("USR-000002", "Ana", "ana.despachante@smithclube.local", "Despachante",
             "Despachante", "Sim", "2026-07-22T00:00:00Z"),
        ],
    )

    # 3) servico (IDs convertidos de 3 para 6 dígitos)
    cur.executemany(
        "INSERT INTO servico VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("SER-000001", "renovacao_cr", "Renovação do CR",
             "Renovação do Certificado de Registro.", "Regularização documental",
             45, 850.00, "RG; CPF; comprovante; certidões; laudo; capacidade técnica.",
             "Sim", "Pode variar conforme o Exército."),
            ("SER-000002", "primeiro_cr", "Primeiro CR",
             "Primeiro Certificado de Registro.", "Regularização documental",
             60, 1200.00, "RG; CPF; comprovante; certidões; laudo; capacidade técnica.",
             "Sim", "Primeira emissão."),
            ("SER-000003", "apostilamento", "Apostilamento", "Apostilamento.",
             "Regularização documental", 30, 500.00,
             "Documento da arma; comprovante; documentos pessoais.",
             "Sim", "Inclusão de arma."),
            ("SER-000004", "transferencia_arma", "Transferência",
             "Transferência de arma.", "Transferência", 40, 650.00,
             "Documentação das partes e da arma.", "Sim", "Transferência."),
        ],
    )

    # 4) sessao (caso_id e ultimo_processo_id ficam NULL por enquanto; ver passo 9)
    cur.execute(
        "INSERT INTO sessao VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SES-000001", "CLI-000001", None, "Email", "cliente@email.com",
         "Renovação do CR", "consulta_documentos", "SER-000001", None,
         "Quais documentos preciso para renovar meu CR?",
         "Para renovar seu CR, são necessários os documentos cadastrados para o serviço.",
         "Cliente solicitou informações sobre documentos para renovação do CR. "
         "Existe processo vinculado em análise.",
         "Aberta", excel_to_iso(46221.625), excel_to_iso(46221.62847222222),
         excel_to_iso(46222.62847222222), "Não", None, None, "Sim",
         "Registro de exemplo migrado da planilha. Campo responsavel original era "
         "\"IA Smith\" (não é usuário humano, por isso ficou vazio)."),
    )

    # 5) memoria_ia
    cur.execute(
        "INSERT INTO memoria_ia VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("MEM-000001", "CLI-000001",
         "Cliente possui atendimento relacionado à renovação do CR e já solicitou "
         "informações sobre documentação e andamento.",
         "Renovação do CR; consulta de documentos; status de processo",
         "SER-000001 - Renovação do CR", "PRO-000001 - Em análise",
         "consulta_documentos", "Email", "Profissional, claro e objetivo",
         "Sempre confirmar protocolo e próxima ação quando existirem.",
         "Nunca informar documentos, prazos ou valores diferentes dos cadastrados.",
         "SES-000001", excel_to_iso(46221.62847222222), "Make", 1, "Sim",
         "Memória de exemplo para teste"),
    )

    # 6) caso real (CAS-000001) — criado_em/atualizado_em vazios na origem;
    #    reconstruídos a partir das datas de sessao/memoria_ia do mesmo cenário.
    cur.execute(
        "INSERT INTO caso VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("CAS-000001", "CLI-000001", "Renovação de CR",
         "Cliente deseja renovar o CR e organizar os documentos necessários.",
         "Regularização documental", "Solicitação", "Atendimento", "Email",
         "Em triagem", "Triagem", "Normal", "USR-000001", "Despachante",
         "SES-000001", "MEM-000001",
         excel_to_iso(46221.625), excel_to_iso(46221.62847222222),
         None, None, "Make", "Make", 1, "Sim", None,
         "Linha de exemplo migrada da planilha; criado_em/atualizado_em "
         "reconstruídos (estavam vazios na origem)."),
    )

    # 7) casos sintéticos, criados na migração para os processos 2 e 3
    #    (caso_id não existia como coluna na planilha original de Processos).
    cur.executemany(
        "INSERT INTO caso VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("CAS-000002", "CLI-000002", "Primeiro CR",
             "Caso criado automaticamente na migração para vincular o processo "
             "PRO-000002 (Primeiro CR).",
             "Regularização documental", "Solicitação", "Atendimento", "Email",
             "Aguardando cliente", "Documentação", "Normal", "USR-000001",
             "Despachante", None, None,
             excel_to_iso(46205.0), excel_to_iso(46213.458333333336),
             None, None, "Migração", "Migração", 1, "Sim", None,
             "Caso sintético: não existia na planilha original, criado só para "
             "satisfazer a exigência de caso_id do processo PRO-000002."),
            ("CAS-000003", "CLI-000003", "Apostilamento",
             "Caso criado automaticamente na migração para vincular o processo "
             "PRO-000003 (Apostilamento).",
             "Regularização documental", "Solicitação", "Atendimento", "Email",
             "Encerrado", "Conclusão", "Normal", "USR-000002",
             "Despachante", None, None,
             excel_to_iso(46152.0), excel_to_iso(46178.416666666664),
             None, excel_to_iso(46178.416666666664), "Migração", "Migração", 1,
             "Sim", "Concluído com sucesso",
             "Caso sintético: não existia na planilha original, criado só para "
             "satisfazer a exigência de caso_id do processo PRO-000003."),
        ],
    )

    # 8) processo
    cur.executemany(
        "INSERT INTO processo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("PRO-000001", "CAS-000001", "CLI-000001", "SER-000001",
             "PROTO-2026-001", "Em análise", excel_to_iso(46198.0),
             excel_to_iso(46243.0), "Aguardar retorno do órgão", "USR-000001",
             excel_to_iso(46215.680555555555), "Sem pendências registradas."),
            ("PRO-000002", "CAS-000002", "CLI-000002", "SER-000002",
             None, "Aguardando documentos", excel_to_iso(46205.0),
             excel_to_iso(46265.0), "Receber comprovante de residência",
             "USR-000001", excel_to_iso(46213.458333333336),
             "Falta comprovante de residência atualizado."),
            ("PRO-000003", "CAS-000003", "CLI-000003", "SER-000003",
             "PROTO-2026-003", "Concluído", excel_to_iso(46152.0),
             excel_to_iso(46182.0), "Nenhuma", "USR-000002",
             excel_to_iso(46178.416666666664), "Processo concluído para teste."),
        ],
    )

    # 9) fecha o ciclo sessao <-> caso/processo, agora que ambos existem
    cur.execute(
        "UPDATE sessao SET caso_id = ?, ultimo_processo_id = ? WHERE sessao_id = ?",
        ("CAS-000001", "PRO-000001", "SES-000001"),
    )

    # 10) documento
    cur.executemany(
        "INSERT INTO documento VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("DOC-000001", "CLI-000001", None, "PRO-000001", "RG",
             "rg_felipe.pdf", "https://example.com/arquivo-teste-1", "Aprovado",
             excel_to_iso(46198.0), excel_to_iso(49851.0), "USR-000001",
             "Documento fictício."),
            ("DOC-000002", "CLI-000002", None, "PRO-000002",
             "Comprovante de residência", None, None, "Pendente", None, None,
             None, "Cliente ainda não enviou."),
            ("DOC-000003", "CLI-000003", None, "PRO-000003", "Documento do item",
             "documento_item.pdf", "https://example.com/arquivo-teste-3",
             "Aprovado", excel_to_iso(46154.0), None, "USR-000002",
             "Documento fictício."),
        ],
    )

    # 11) conversa — planilha tinha iniciada_em/ultima_mensagem_em como texto
    #     literal "data atual" (não uma data de verdade); reconstruído a partir
    #     de sessao.iniciada_em, do mesmo cenário de teste.
    cur.execute(
        "INSERT INTO conversa VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("CON-000001", "CLI-000001", "CAS-000001", "SES-000001", "Webhook",
         "Sistema", "Aberta", "Novo Atendimento",
         excel_to_iso(46221.625), excel_to_iso(46221.625), None, None, "Não", 1,
         "make", "make", 1, "Sim",
         "Conversa criada automaticamente. iniciada_em/ultima_mensagem_em "
         "reconstruídos (planilha tinha texto literal \"data atual\")."),
    )

    # 12) fecha o ciclo sessao <-> conversa, agora que conversa existe
    cur.execute(
        "UPDATE sessao SET conversa_id_origem = ? WHERE sessao_id = ?",
        ("CON-000001", "SES-000001"),
    )

    # 13) template — recupera os 7 campos tirados de servico na 2ª rodada.
    cur.executemany(
        "INSERT INTO template VALUES (?,?,?,?,?,?,?,?)",
        [
            ("TPL-000001", "resposta_sem_processo", "Resposta: sem processo",
             "processo", "Não localizei processo vinculado.", None, "Sim", None),
            ("TPL-000002", "resposta_em_analise", "Resposta: em análise",
             "processo", "Processo em análise.", None, "Sim", None),
            ("TPL-000003", "resposta_documento_pendente",
             "Resposta: documento pendente", "processo",
             "Documentação pendente.", None, "Sim", None),
            ("TPL-000004", "resposta_concluido", "Resposta: concluído",
             "processo", "Processo concluído.", None, "Sim", None),
            ("TPL-000005", "mensagem_padrao_servico", "Mensagem padrão de serviço",
             "servico", "Localizei o serviço de {nome_servico}.", None, "Sim",
             None),
            ("TPL-000006", "prazo_texto_servico", "Texto de prazo do serviço",
             "servico", "Prazo médio de {prazo_estimado_dias} dias.", None,
             "Sim", None),
            ("TPL-000007", "valor_texto_servico", "Texto de valor do serviço",
             "servico", "Valor de referência: R$ {valor_referencia}.", None,
             "Sim", None),
        ],
    )

    con.commit()

    print("Migração concluída. Contagem de linhas por tabela:")
    for tabela in ["cliente", "usuario", "servico", "caso", "processo",
                   "documento", "sessao", "memoria_ia", "conversa", "template"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        print(f"  {tabela}: {n}")

    con.close()


if __name__ == "__main__":
    main()
