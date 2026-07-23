"""Decide, a partir da classificação de intenção, quais fontes consultar e
se o atendimento deve ser encaminhado a um humano. Não chama a OpenAI --
é roteamento determinístico, não interpretação. Não decide regra de
negócio sobre o caso (prazo, valor, documento); só decide o caminho de
dados a seguir dentro do próprio Motor IA.
"""
from dataclasses import dataclass

from motor_ia.classificador import Intencao, ResultadoClassificacao

# Quais fontes o Consultor deve buscar para cada intenção. VW_* são as
# views do Core (core/db/views.sql); "conhecimento" é a tabela de Domínio
# (domain/clube_tiro/db/schema.sql); "SHOOTING_HOUSE_HABITUALIDADE" é uma
# fonte externa (integracoes/shooting_house.py), não um banco nosso.
FONTES_POR_INTENCAO: dict[Intencao, list[str]] = {
    "CONSULTA_DOCUMENTOS": ["VW_SERVICO"],
    "CONSULTA_PROCESSO": ["VW_PROCESSO", "VW_CLIENTE"],
    "CONSULTA_CLIENTE": ["VW_CLIENTE"],
    "CONSULTA_HABITUALIDADE": ["SHOOTING_HOUSE_HABITUALIDADE"],
    "ATENDIMENTO_GERAL": ["conhecimento"],
    "ATENDIMENTO_HUMANO": [],
}


@dataclass
class Plano:
    rota: str
    fontes: list[str]
    encaminhar_humano: bool
    motivo_humano: str | None


def planejar(classificacao: ResultadoClassificacao) -> Plano:
    encaminhar_humano = (
        classificacao.precisa_humano or classificacao.intencao == "ATENDIMENTO_HUMANO"
    )

    motivo_humano = None
    if classificacao.intencao == "ATENDIMENTO_HUMANO":
        motivo_humano = "Classificado diretamente como ATENDIMENTO_HUMANO."
    elif classificacao.precisa_humano:
        motivo_humano = (
            f"Intenção classificada como {classificacao.intencao}, mas a "
            "mensagem sinalizou necessidade de atendimento humano."
        )

    return Plano(
        rota=classificacao.intencao.lower(),
        fontes=FONTES_POR_INTENCAO[classificacao.intencao],
        encaminhar_humano=encaminhar_humano,
        motivo_humano=motivo_humano,
    )


if __name__ == "__main__":
    from motor_ia.classificador import classificar

    exemplos = [
        "Quais documentos preciso para renovar meu CR?",
        "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001",
        "Isso é um absurdo, ninguém me responde há uma semana, quero falar com uma pessoa AGORA",
    ]
    for texto in exemplos:
        classificacao = classificar(texto)
        plano = planejar(classificacao)
        print(f"Mensagem: {texto}")
        print(f"  intenção: {classificacao.intencao}")
        print(f"  -> rota={plano.rota} fontes={plano.fontes} "
              f"encaminhar_humano={plano.encaminhar_humano} "
              f"motivo={plano.motivo_humano}")
        print()
