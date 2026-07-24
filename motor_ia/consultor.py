"""Busca de fato os dados que o Planejador apontou como necessários
(plano.fontes) -- só consulta as views do Core, a tabela conhecimento do
Domínio e integrações externas (Shooting House), nunca decide nada sobre
o conteúdo."""
from typing import Optional

from integracoes.shooting_house import consultar_cr, consultar_habitualidade
from motor_ia.classificador import ResultadoClassificacao
from motor_ia.conexao import conectar
from motor_ia.planejador import Plano


def _montar_checklist_texto(con, servico_id: str) -> Optional[str]:
    """Agrupa VW_CHECKLIST_SERVICO num texto legível (markdown simples),
    formatação pura em Python -- a IA não decide nem monta essa lista,
    só recebe o texto pronto."""
    linhas_checklist = con.execute(
        "SELECT grupo, item FROM VW_CHECKLIST_SERVICO WHERE servico_id = ?",
        (servico_id,),
    ).fetchall()
    if not linhas_checklist:
        return None

    blocos = []
    grupo_atual = "__nenhum_ainda__"
    for linha in linhas_checklist:
        if linha["grupo"] != grupo_atual:
            grupo_atual = linha["grupo"]
            if grupo_atual:
                blocos.append(f"{grupo_atual}:")
        blocos.append(f"- {linha['item']}")
    return "\n".join(blocos)


def consultar(
    plano: Plano,
    cliente_id: str,
    classificacao: Optional[ResultadoClassificacao] = None,
) -> dict:
    con = conectar()
    try:
        # O cliente já foi identificado antes da classificação acontecer
        # (fluxo real: Identificar cliente -> Classificar intenção), então
        # os dados básicos dele não dependem de plano.fontes -- toda
        # resposta precisa saber com quem está falando.
        linha_cliente = con.execute(
            "SELECT * FROM VW_CLIENTE WHERE cliente_id = ?", (cliente_id,)
        ).fetchone()
        resultado = {"cliente": dict(linha_cliente) if linha_cliente else None}

        for fonte in plano.fontes:
            if fonte == "VW_CLIENTE":
                continue  # já buscado acima, sempre
            if fonte == "VW_SERVICO":
                servico_mencionado = (
                    classificacao.servico_mencionado if classificacao else None
                )
                linhas = []
                correspondencia_exata = False
                if servico_mencionado:
                    linhas = con.execute(
                        "SELECT * FROM VW_SERVICO WHERE ativo = 'Sim' AND nome_servico = ?",
                        (servico_mencionado,),
                    ).fetchall()
                    correspondencia_exata = bool(linhas)
                if not linhas:
                    # Pergunta genérica, ou o nome não bateu exato com o
                    # cadastro -- devolve o catálogo inteiro em vez de nada.
                    linhas = con.execute(
                        "SELECT * FROM VW_SERVICO WHERE ativo = 'Sim'"
                    ).fetchall()
                servicos = [dict(r) for r in linhas]
                if correspondencia_exata:
                    # Checklist completo só entra quando o cliente perguntou
                    # sobre UM serviço específico -- no catálogo inteiro
                    # (pergunta genérica) continuaria usando o resumo curto,
                    # mesma cautela já documentada contra despejar tudo.
                    for s in servicos:
                        s["checklist_texto"] = _montar_checklist_texto(con, s["service_id"])
                resultado["servicos"] = servicos
            elif fonte == "VW_PROCESSO":
                protocolo = classificacao.protocolo_mencionado if classificacao else None
                if protocolo:
                    linhas = con.execute(
                        "SELECT * FROM VW_PROCESSO WHERE cliente_id = ? AND protocolo = ?",
                        (cliente_id, protocolo),
                    ).fetchall()
                else:
                    linhas = con.execute(
                        "SELECT * FROM VW_PROCESSO WHERE cliente_id = ?", (cliente_id,)
                    ).fetchall()
                resultado["processos"] = [dict(r) for r in linhas]
            elif fonte == "conhecimento":
                # Diferente de VW_SERVICO, aqui NÃO existe fallback pra "traz
                # tudo" quando a categoria não bate -- são 10 respostas sobre
                # regulamentação de arma de fogo, um assunto bem específico;
                # despejar isso numa pergunta sobre horário de funcionamento,
                # por exemplo, é o próprio bug que motivou esse filtro.
                categoria = classificacao.categoria_conhecimento if classificacao else None
                linhas = []
                if categoria:
                    linhas = con.execute(
                        "SELECT * FROM dominio.conhecimento "
                        "WHERE aprovado = 'Sim' AND ativo = 'Sim' AND categoria = ?",
                        (categoria,),
                    ).fetchall()
                resultado["conhecimento"] = [dict(r) for r in linhas]
            elif fonte == "SHOOTING_HOUSE_HABITUALIDADE":
                cpf_cliente = (resultado.get("cliente") or {}).get("cpf")
                resultado["habitualidade"] = (
                    consultar_habitualidade(cpf_cliente) if cpf_cliente else None
                )
            elif fonte == "SHOOTING_HOUSE_CR":
                cpf_cliente = (resultado.get("cliente") or {}).get("cpf")
                resultado["cr"] = consultar_cr(cpf_cliente) if cpf_cliente else None
            else:
                raise ValueError(f"Fonte desconhecida: {fonte}")
        return resultado
    finally:
        con.close()


if __name__ == "__main__":
    from motor_ia.classificador import classificar
    from motor_ia.planejador import planejar

    texto = "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001"
    classificacao = classificar(texto)
    plano = planejar(classificacao)
    dados = consultar(plano, cliente_id="CLI-000001", classificacao=classificacao)

    print(f"Mensagem: {texto}")
    print(f"Intenção: {classificacao.intencao}")
    print(f"Fontes consultadas: {plano.fontes}")
    print("Dados encontrados:")
    for chave, valor in dados.items():
        print(f"  {chave}: {valor}")
