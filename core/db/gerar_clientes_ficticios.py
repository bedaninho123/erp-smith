"""Gera 20 clientes fictícios com dados variados, para testar o pipeline
com mais diversidade do que os 3 clientes de exemplo originais (que são
quase todos iguais entre si). TODO O CONTEÚDO AQUI É FICTÍCIO -- CPFs
seguem um padrão obviamente falso (10000000001, 10000000002...), nomes
e situações são inventados para cobrir cenários diferentes do pipeline
(cada status de caso, cada categoria, perfis de habitualidade
diferentes no Shooting House simulado).

Não substitui a migração de dados reais (ver recomendação do Claude no
chat) -- serve para testar amplitude de cenários enquanto não há
cliente real disponível para teste.
"""
from datetime import datetime, timezone

from core.conexao import conectar

CIDADES = ["Marília", "Bauru", "Assis", "Ourinhos", "Tupã", "Garça", "Lins"]


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> int:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return maior + 1


# (nome, cidade, status, atendimento_ia, categoria_caso, tipo_caso, origem,
#  canal_origem, status_caso, fase, prioridade, servico_key ou None,
#  status_processo ou None, observacao_cenario)
PERFIS = [
    ("Roberto Almeida", "Marília", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Email", "Em andamento", "Documentação", "Normal", "renovacao_cr", "Em análise", "Renovação de CR em andamento normal"),
    ("Carla Mendes", "Bauru", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Email", "Aguardando cliente", "Documentação", "Normal", "primeiro_cr", "Aguardando documentos", "Primeiro CR, falta documento do cliente"),
    ("Eduardo Santos", "Assis", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "WhatsApp", "Encerrado", "Conclusão", "Baixa", "apostilamento", "Concluído", "Apostilamento já concluído com sucesso"),
    ("Fernanda Lima", "Marília", "Ativo", "Sim", "Transferência", "Solicitação", "Atendimento", "Email", "Em andamento", "Execução", "Normal", "transferencia_arma", "Em análise", "Transferência de arma em andamento"),
    ("Gustavo Pereira", "Ourinhos", "Ativo", "Sim", "CRAF", "Dúvida", "Atendimento", "Email", "Aberto", "Triagem", "Normal", None, None, "Dúvida geral sobre CRAF, sem processo aberto ainda"),
    ("Helena Costa", "Tupã", "Ativo", "Sim", "Habitualidade", "Consulta", "Atendimento", "Email", "Em triagem", "Triagem", "Normal", None, None, "Pergunta sobre habitualidade -- perfil Shooting House: em dia"),
    ("Igor Ramos", "Marília", "Ativo", "Sim", "Reclamação", "Reclamação", "Atendimento", "Email", "Aberto", "Triagem", "Urgente", None, None, "Cliente insatisfeito, reclamação de demora -- deve ir a humano"),
    ("Juliana Rocha", "Garça", "Ativo", "Sim", "Aquisição", "Solicitação", "Atendimento", "Email", "Em andamento", "Documentação", "Normal", None, None, "Processo de aquisição de arma em andamento"),
    ("Marcelo Dias", "Marília", "Inativo", "Não", "Regularização documental", "Solicitação", "Atendimento", "Email", "Encerrado", "Conclusão", "Baixa", "renovacao_cr", "Concluído", "Renovação de CR concluída, cliente inativo"),
    ("Patrícia Souza", "Bauru", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Email", "Aguardando cliente", "Documentação", "Alta", "primeiro_cr", "Aguardando documentos", "Primeiro CR, prioridade alta, aguardando cliente"),
    ("Rafael Nunes", "Lins", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Portal", "Aberto", "Triagem", "Normal", "apostilamento", "Em análise", "Apostilamento recém-aberto"),
    ("Sandra Vieira", "Assis", "Ativo", "Sim", "Transferência", "Solicitação", "Atendimento", "Email", "Encerrado", "Conclusão", "Normal", "transferencia_arma", "Concluído", "Transferência concluída com sucesso"),
    ("Thiago Moreira", "Marília", "Ativo", "Sim", "CRAF", "Dúvida", "Atendimento", "WhatsApp", "Em triagem", "Triagem", "Normal", None, None, "Dúvida sobre registro de arma específica"),
    ("Vanessa Teixeira", "Ourinhos", "Ativo", "Sim", "Habitualidade", "Consulta", "Atendimento", "Email", "Aberto", "Triagem", "Normal", None, None, "Pergunta sobre habitualidade -- perfil Shooting House: em dia"),
    ("William Cardoso", "Tupã", "Ativo", "Sim", "Habitualidade", "Consulta", "Atendimento", "Email", "Aberto", "Triagem", "Normal", None, None, "Pergunta sobre habitualidade -- perfil Shooting House: irregular"),
    ("Ana Beatriz Fonseca", "Garça", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Email", "Cancelado", "Conclusão", "Baixa", "primeiro_cr", None, "Primeiro CR cancelado -- cliente desistiu"),
    ("Bruno Carvalho", "Marília", "Ativo", "Sim", "Regularização documental", "Solicitação", "Atendimento", "Email", "Suspenso", "Acompanhamento", "Normal", "renovacao_cr", "Aguardando documentos", "Renovação suspensa aguardando retorno do órgão"),
    ("Camila Duarte", "Bauru", "Ativo", "Sim", "Aquisição", "Solicitação", "Atendimento", "Email", "Aberto", "Triagem", "Normal", None, None, "Aquisição recém-iniciada"),
    ("Diego Martins", "Lins", "Ativo", "Sim", "Transferência", "Solicitação", "Atendimento", "Email", "Aguardando cliente", "Documentação", "Normal", "transferencia_arma", "Aguardando documentos", "Transferência aguardando documento do cedente"),
    ("Larissa Barbosa", "Assis", "Ativo", "Sim", "Habitualidade", "Consulta", "Atendimento", "Email", "Aberto", "Triagem", "Normal", None, None, "Pergunta sobre habitualidade -- perfil Shooting House: sem registros"),
]


def main():
    con = conectar()
    try:
        prox_cliente = _proximo_id(con, "cliente", "cliente_id", "CLI")
        prox_caso = _proximo_id(con, "caso", "caso_id", "CAS")
        prox_processo = _proximo_id(con, "processo", "processo_id", "PRO")
        agora = _agora_iso()

        criados = {"cliente": 0, "caso": 0, "processo": 0}

        for i, perfil in enumerate(PERFIS):
            (nome, cidade, status, atendimento_ia, categoria_caso, tipo_caso,
             origem, canal_origem, status_caso, fase, prioridade,
             servico_key, status_processo, cenario) = perfil

            cliente_id = f"CLI-{prox_cliente + i:06d}"
            cpf = f"{10000000001 + i:011d}"
            email = f"cliente.teste{prox_cliente + i}@example.com"
            telefone = f"551499990{prox_cliente + i:04d}"

            con.execute(
                "INSERT INTO cliente VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cliente_id, nome, cpf, email, telefone, cidade, status,
                 atendimento_ia, agora, agora,
                 f"[FICTÍCIO -- dado de teste] {cenario}"),
            )
            criados["cliente"] += 1

            caso_id = f"CAS-{prox_caso:06d}"
            prox_caso += 1
            encerrado_em = agora if status_caso in ("Encerrado", "Cancelado") else None
            motivo_encerramento = None
            if status_caso == "Encerrado":
                motivo_encerramento = "Concluído com sucesso"
            elif status_caso == "Cancelado":
                motivo_encerramento = "Solicitação cancelada pelo cliente"

            con.execute(
                "INSERT INTO caso VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    caso_id, cliente_id, f"{tipo_caso} - {categoria_caso}", cenario,
                    categoria_caso, tipo_caso, origem, canal_origem, status_caso,
                    fase, prioridade, None, "Despachante", None, None,
                    agora, agora, None, encerrado_em, "Migração", "Migração",
                    1, "Sim", motivo_encerramento,
                    f"[FICTÍCIO -- dado de teste] {cenario}",
                ),
            )
            criados["caso"] += 1

            if servico_key:
                servico = con.execute(
                    "SELECT service_id FROM servico WHERE service_key = ?", (servico_key,)
                ).fetchone()
                if servico:
                    processo_id = f"PRO-{prox_processo:06d}"
                    prox_processo += 1
                    con.execute(
                        "INSERT INTO processo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            processo_id, caso_id, cliente_id, servico["service_id"],
                            None, status_processo or "Em análise", agora, None,
                            None, None, agora,
                            f"[FICTÍCIO -- dado de teste] {cenario}",
                        ),
                    )
                    criados["processo"] += 1

        con.commit()
        print(f"Criados: {criados['cliente']} clientes, {criados['caso']} casos, "
              f"{criados['processo']} processos -- todos marcados como FICTÍCIO.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
