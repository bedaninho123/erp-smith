"""Demonstração manual do pipeline completo: mensagem -> Classificador ->
Planejador -> Consultor -> Redator -> Auditor. Não é um módulo do Motor IA
em si, é só uma ferramenta pra ver o comportamento atual de ponta a ponta."""
from core.configuracoes import obter_configuracoes
from motor_ia.auditor import auditar
from motor_ia.classificador import classificar
from motor_ia.consultor import consultar
from motor_ia.planejador import planejar
from motor_ia.redator import redigir


def responder(mensagem: str, cliente_id: str) -> None:
    classificacao = classificar(mensagem)
    plano = planejar(classificacao)
    dados = consultar(plano, cliente_id=cliente_id, classificacao=classificacao)
    cliente_nome = (dados.get("cliente") or {}).get("nome", "Cliente")

    resposta = redigir(dados, cliente_nome=cliente_nome)
    resultado = auditar(resposta, dados, cliente_nome, plano)

    print(f"Mensagem: {mensagem}")
    print(f"Intenção: {classificacao.intencao}  |  precisa_humano: {classificacao.precisa_humano}")
    print(f"Auditoria: aprovado={resultado.aprovado}  ação={resultado.acao}  motivo={resultado.motivo}")
    print("-" * 60)

    if resultado.acao == "enviar":
        print("[ENVIADO AO CLIENTE]")
        print(resposta)
    elif resultado.acao == "encaminhar_humano":
        config = obter_configuracoes()
        print("[RESPOSTA DA IA DESCARTADA -- ENCAMINHADO A HUMANO]")
        print(config.get("mensagem_encaminhamento_humano"))
    else:
        print("[RESPOSTA RETIDA PARA REVISÃO -- NÃO ENVIADA]")
        print(resposta)

    print("=" * 60)
    print()


if __name__ == "__main__":
    responder("Quais documentos preciso para renovar meu CR?", "CLI-000001")
    responder(
        "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001",
        "CLI-000001",
    )
    responder(
        "Isso é um absurdo, ninguém me responde há uma semana, quero falar com uma pessoa AGORA",
        "CLI-000001",
    )
