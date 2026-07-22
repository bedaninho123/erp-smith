"""Busca de fato os dados que o Planejador apontou como necessários
(plano.fontes) -- só consulta as views do Core e a tabela conhecimento do
Domínio, nunca decide nada sobre o conteúdo."""
from typing import Optional

from motor_ia.classificador import ResultadoClassificacao
from motor_ia.conexao import conectar
from motor_ia.planejador import Plano


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
                if servico_mencionado:
                    linhas = con.execute(
                        "SELECT * FROM VW_SERVICO WHERE ativo = 'Sim' AND nome_servico = ?",
                        (servico_mencionado,),
                    ).fetchall()
                if not linhas:
                    # Pergunta genérica, ou o nome não bateu exato com o
                    # cadastro -- devolve o catálogo inteiro em vez de nada.
                    linhas = con.execute(
                        "SELECT * FROM VW_SERVICO WHERE ativo = 'Sim'"
                    ).fetchall()
                resultado["servicos"] = [dict(r) for r in linhas]
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
                resultado["conhecimento"] = [
                    dict(r) for r in con.execute(
                        "SELECT * FROM dominio.conhecimento "
                        "WHERE aprovado = 'Sim' AND ativo = 'Sim'"
                    ).fetchall()
                ]
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
