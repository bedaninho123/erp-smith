"""Escreve a resposta final ao cliente, usando exclusivamente os fatos que
o Consultor já buscou -- nunca inventa prazo, valor, documento ou status.
Prompt em motor_ia/prompts/redator_email.md (arquivo, não hardcoded).
"""
import re
import time
from datetime import date
from pathlib import Path
from typing import Optional

from openai import OpenAI

from core.configuracoes import obter_configuracoes
from core.motor_log_ia import registrar_log
from motor_ia.config import OPENAI_API_KEY

PROMPT_PATH = Path(__file__).parent / "prompts" / "redator_email.md"


def _carregar_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# Prefixo entre parênteses no começo do texto da arma. A API real manda
# arma_formatada como "(ABA212416) Pistola - TH380 CLUBE - 380 ACP" --
# aquele primeiro grupo é o NÚMERO DE SÉRIE, embutido no meio de um campo
# descritivo. Foi o que mostrou que mascarar um campo chamado "serie" não
# bastaria.
_SERIE_NO_TEXTO_DA_ARMA = re.compile(r"^\s*\([^)]*\)\s*")


def _arma_sem_serie(texto: Optional[str]) -> str:
    """Tira o número de série do texto descritivo de uma arma.

    Nenhuma resposta legítima ao cliente precisa recitar número de série
    -- ele sabe qual arma é dele, "sua pistola .380" basta. E o que o
    modelo nunca recebe, ele nunca pode repetir numa resposta, nem
    entregar a uma mensagem construída pra extraí-lo. É a única proteção
    desse tipo que não depende de a IA cooperar.

    O número continua existindo no dado (o Portal, com login, mostra pro
    dono); o que muda é só o que atravessa a rede até a OpenAI."""
    return _SERIE_NO_TEXTO_DA_ARMA.sub("", texto or "").strip()


def _data_br(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _formatar_periodo(data_inicio: str, data_fim: str) -> str:
    """dd/mm/aaaa, ou 'de X a Y' quando a prova passa de um dia -- só
    formatação, nenhuma conta de data (isso já foi decidido em Python no
    Consultor; aqui é só deixar legível)."""
    if data_inicio == data_fim:
        return _data_br(data_inicio)
    return f"de {_data_br(data_inicio)} a {_data_br(data_fim)}"


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
        if s.get("checklist_texto"):
            linhas.append("Documentos necessários:")
            linhas.append(s["checklist_texto"])
        else:
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
                # v pode ser None/vazio (ex.: "competicao" na maioria dos
                # treinos) -- sem o filtro, "competicao: None" ia direto pro
                # texto que a IA usa, e já vazou pro cliente como
                # "Competição: None" antes desta correção.
                # `arma` aqui vem de arma_formatada, que traz o número de
                # série embutido no texto -- limpo antes de entrar no bloco.
                partes = [
                    f"{k}: {_arma_sem_serie(v) if k == 'arma' else v}"
                    for k, v in evento.items() if v
                ]
                linhas.append("  - " + "; ".join(partes))

    if "cr" in dados:
        cr = dados["cr"]
        linhas.append("--- Confirmação cadastral do CR ---")
        if not cr:
            linhas.append("Nenhum CR registrado para este cliente em nosso sistema.")
        else:
            if cr.get("simulado"):
                linhas.append(
                    "(Aviso interno, não repetir ao cliente nem mencionar nome de "
                    "sistema algum: estes dados de CR são de teste.)"
                )
            linhas.append(f"Categoria do CR: {cr['categoria_cr']}")
            linhas.append(f"Última confirmação cadastral registrada: {cr['data_ultima_confirmacao']}")
            linhas.append(f"Próxima confirmação cadastral obrigatória: {cr['proxima_confirmacao']}.")
            linhas.append(
                "Importante: o CR do atirador desportivo NÃO tem uma data de "
                "vencimento fixa que expira sozinha -- ele continua válido enquanto "
                "a confirmação cadastral anual e a habitualidade mínima estiverem em "
                "dia. Ao responder, explique que se trata de uma confirmação "
                "cadastral anual obrigatória, nunca chame isso de 'vencimento do CR' "
                "(isso é o CRAF, prazo fixo de 3 ou 5 anos, um documento diferente)."
            )

    if "armas" in dados:
        armas = dados["armas"]
        linhas.append("--- Armas registradas ---")
        if not armas:
            linhas.append("Nenhuma arma registrada para este cliente em nosso sistema.")
        else:
            linhas.append(
                "(Aviso interno, não repetir ao cliente nem mencionar nome de "
                "sistema algum: estes dados de arma são de teste.)"
            )
            for arma in armas:
                # Sem `serie` de propósito -- ver _arma_sem_serie acima.
                linhas.append(
                    f"  - {arma.get('type') or 'Arma'} {arma.get('brand') or ''} "
                    f"{arma.get('model') or ''}, calibre {arma.get('caliber') or 'não informado'}"
                )
            linhas.append(
                "Instrução: o número de série das armas não está disponível "
                "para esta resposta e não deve ser mencionado nem estimado."
            )

    if "documentos_vencimento" in dados:
        documentos_vencimento = dados["documentos_vencimento"]
        linhas.append("--- Guia de tráfego e SIMAF ---")
        if not documentos_vencimento:
            linhas.append("Nenhum documento com vencimento registrado para este cliente em nosso sistema.")
        else:
            linhas.append(
                "(Aviso interno, não repetir ao cliente nem mencionar nome de "
                "sistema algum: estes dados de documento são de teste.)"
            )
            for doc in documentos_vencimento:
                linhas.append(f"Arma: {doc.get('arma') or 'não informada'}")
                for guia in doc.get("guia_trafego") or []:
                    estado = "liberada" if guia.get("liberado") else "não liberada"
                    linhas.append(
                        f"  - Guia de tráfego: vencimento {guia.get('vencimento') or 'não informado'}, {estado}."
                    )
                for simaf in doc.get("simaf") or []:
                    estado = "liberado" if simaf.get("liberado") else "não liberado"
                    linhas.append(
                        f"  - SIMAF: vencimento {simaf.get('vencimento') or 'não informado'}, {estado}."
                    )

    for k in dados.get("conhecimento", []):
        linhas.append(f"Conhecimento institucional: {k['pergunta']} -> {k['resposta']}")

    informacoes_empresa = dados.get("informacoes_empresa")
    if informacoes_empresa:
        linhas.append("--- Informações do clube ---")
        for rotulo, valor in informacoes_empresa.items():
            linhas.append(f"{rotulo}: {valor}")

    if "campeonatos" in dados:
        campeonatos = dados["campeonatos"]
        linhas.append("--- Calendário de provas (só as que ainda vão acontecer) ---")
        if not campeonatos:
            linhas.append("Nenhuma prova cadastrada no calendário a partir de hoje.")
        else:
            for c in campeonatos:
                # Data já formatada em Python (dd/mm/aaaa) -- o Redator só
                # reproduz o texto, nunca calcula nem reordena por conta
                # própria.
                periodo = _formatar_periodo(c["data_inicio"], c["data_fim"])
                linha = f"  - {c['nome']}: {periodo}"
                if c.get("local"):
                    linha += f", em {c['local']}"
                linhas.append(linha)

    if dados.get("fontes_indisponiveis"):
        # Este atendimento já vai ser travado pelo freio determinístico do
        # Auditor antes de chegar ao cliente (motor_ia/auditor.py). O bloco
        # está aqui mesmo assim porque o texto do Redator ainda é gravado e
        # aparece para o atendente na tela -- e um rascunho que afirma
        # "você não tem nenhuma arma registrada" é perigoso mesmo dentro de
        # casa: alguém com pressa aprova.
        linhas.append("--- Consultas que NÃO puderam ser feitas ---")
        for fonte in dados["fontes_indisponiveis"]:
            linhas.append(f"  - {fonte['fonte']}: consulta indisponível no momento.")
        linhas.append(
            "Instrução: sobre estes pontos você NÃO tem informação nenhuma. "
            "Não afirme que não há registro, que está tudo em dia, nem que "
            "não foi encontrado nada -- nada disso foi verificado. Diga "
            "apenas que a consulta não pôde ser feita agora e que um "
            "atendente vai verificar."
        )

    linhas.append("--- Configurações institucionais ---")
    # prazo_resposta_humano fica de fora de propósito -- só é relevante
    # quando o caso é encaminhado a um humano (isso é tratado à parte,
    # em atendimento/processar.py), não em toda resposta automática.
    for chave in (
        "nome_empresa", "telefone", "whatsapp", "email_atendimento", "site",
        "horario_semana", "horario_sabado", "horario_domingo",
        "aviso_valor", "aviso_prazo", "assinatura_email",
    ):
        if config.get(chave):
            linhas.append(f"{chave}: {config[chave]}")

    return "\n".join(linhas)


def redigir(
    empresa_id: str, dados: dict, cliente_nome: str,
    caso_id: Optional[str] = None, sessao_id: Optional[str] = None,
) -> str:
    config = obter_configuracoes(empresa_id)
    bloco = montar_bloco_dados(dados, cliente_nome, config)
    modelo = config.get("modelo_openai", "gpt-5-mini")

    client = OpenAI(api_key=OPENAI_API_KEY)
    inicio = time.monotonic()
    try:
        resposta = client.chat.completions.create(
            model=modelo,
            messages=[
                {"role": "system", "content": _carregar_prompt()},
                {"role": "user", "content": f"DADOS DISPONÍVEIS:\n{bloco}"},
            ],
        )
    except Exception as e:
        registrar_log(
            empresa_id, prompt_key="REDATOR", modelo=modelo, resultado="Erro",
            tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
            caso_id=caso_id, sessao_id=sessao_id, erro=f"{type(e).__name__}: {e}",
        )
        raise

    uso = resposta.usage
    registrar_log(
        empresa_id, prompt_key="REDATOR", modelo=modelo, resultado="Sucesso",
        tokens_entrada=uso.prompt_tokens if uso else None,
        tokens_saida=uso.completion_tokens if uso else None,
        tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
        caso_id=caso_id, sessao_id=sessao_id,
    )
    return resposta.choices[0].message.content


if __name__ == "__main__":
    from motor_ia.classificador import classificar
    from motor_ia.consultor import consultar
    from motor_ia.planejador import planejar

    EMPRESA = "EMP-000001"
    texto = "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001"
    classificacao = classificar(EMPRESA, texto)
    plano = planejar(classificacao)
    dados = consultar(plano, empresa_id=EMPRESA, cliente_id="CLI-000001", classificacao=classificacao)
    resposta = redigir(EMPRESA, dados, cliente_nome=dados["cliente"]["nome"])

    print(f"Mensagem do cliente: {texto}\n")
    print("Resposta gerada:\n")
    print(resposta)
