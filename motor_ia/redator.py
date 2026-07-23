"""Escreve a resposta final ao cliente, usando exclusivamente os fatos que
o Consultor já buscou -- nunca inventa prazo, valor, documento ou status.
Prompt em motor_ia/prompts/redator_email.md (arquivo, não hardcoded).
"""
from pathlib import Path

from openai import OpenAI

from core.configuracoes import obter_configuracoes
from motor_ia.config import OPENAI_API_KEY

PROMPT_PATH = Path(__file__).parent / "prompts" / "redator_email.md"


def _carregar_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def montar_bloco_dados(dados: dict, cliente_nome: str, config: dict) -> str:
    linhas = [f"Cliente: {cliente_nome}"]

    cliente = dados.get("cliente")
    if cliente:
        if cliente.get("tom_recomendado"):
            linhas.append(f"Tom recomendado: {cliente['tom_recomendado']}")
        if cliente.get("restricoes_atendimento"):
            linhas.append(f"Restrição de atendimento: {cliente['restricoes_atendimento']}")

    if "processos" in dados:
        processos = dados["processos"]
        if not processos:
            linhas.append(
                "Nenhum processo encontrado para este cliente com os dados informados."
            )
        for p in processos:
            linhas.append("--- Processo ---")
            linhas.append(f"Serviço: {p['nome_servico']}")
            linhas.append(f"Protocolo: {p.get('protocolo') or 'não informado'}")
            linhas.append(f"Status: {p['status']}")
            linhas.append(f"Data de abertura: {p['data_abertura']}")
            linhas.append(f"Prazo estimado: {p.get('prazo_estimado') or 'não informado'}")
            linhas.append(f"Próxima ação: {p.get('proxima_acao') or 'nenhuma'}")
            linhas.append(f"Responsável: {p.get('responsavel_nome') or 'não atribuído'}")
            linhas.append(f"Última atualização: {p['ultima_atualizacao']}")
            if p.get("observacoes"):
                linhas.append(f"Observações: {p['observacoes']}")

    for s in dados.get("servicos", []):
        linhas.append("--- Serviço ---")
        linhas.append(f"Nome: {s['nome_servico']}")
        linhas.append(s["prazo_texto"])
        linhas.append(s["valor_texto"])
        linhas.append(f"Documentos necessários: {s['documentos_obrigatorios']}")

    habitualidade = dados.get("habitualidade")
    if habitualidade:
        # Título sem nome de fornecedor/sistema interno -- já vimos a IA
        # copiar rótulos como "(Shooting House)" pro texto do cliente.
        linhas.append("--- Registros de participação em treinos ---")
        if habitualidade.get("simulado"):
            linhas.append(
                "(Aviso interno, não repetir ao cliente nem mencionar nome de "
                "sistema algum: estes dados de participação são de teste.)"
            )
        grupos = habitualidade.get("habitualidades") or {}
        if not grupos:
            linhas.append("Nenhuma participação registrada no período consultado.")
        for grupo, info in grupos.items():
            linhas.append(f"Grupo {grupo}: {info.get('count', '?')} participação(ões) registrada(s).")
            for evento in info.get("eventos", []):
                linhas.append("  - " + "; ".join(f"{k}: {v}" for k, v in evento.items()))

    for k in dados.get("conhecimento", []):
        linhas.append(f"Conhecimento institucional: {k['pergunta']} -> {k['resposta']}")

    linhas.append("--- Configurações institucionais ---")
    for chave in ("nome_empresa", "aviso_valor", "aviso_prazo", "assinatura_email"):
        if config.get(chave):
            linhas.append(f"{chave}: {config[chave]}")

    return "\n".join(linhas)


def redigir(dados: dict, cliente_nome: str) -> str:
    config = obter_configuracoes()
    bloco = montar_bloco_dados(dados, cliente_nome, config)
    modelo = config.get("modelo_openai", "gpt-5-mini")

    client = OpenAI(api_key=OPENAI_API_KEY)
    resposta = client.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": _carregar_prompt()},
            {"role": "user", "content": f"DADOS DISPONÍVEIS:\n{bloco}"},
        ],
    )
    return resposta.choices[0].message.content


if __name__ == "__main__":
    from motor_ia.classificador import classificar
    from motor_ia.consultor import consultar
    from motor_ia.planejador import planejar

    texto = "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001"
    classificacao = classificar(texto)
    plano = planejar(classificacao)
    dados = consultar(plano, cliente_id="CLI-000001", classificacao=classificacao)
    resposta = redigir(dados, cliente_nome=dados["cliente"]["nome"])

    print(f"Mensagem do cliente: {texto}\n")
    print("Resposta gerada:\n")
    print(resposta)
