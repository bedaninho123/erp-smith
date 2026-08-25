"""Cliente SOMENTE LEITURA da API de Parceiros do Shooting House
(https://app.swaggerhub.com/apis/shootinghouse/Parceiros/1.0.1) -- o
sistema de gestão do clube de tiro que já guarda atirador, arma,
habitualidade e campeonatos. O ERP Smith não duplica esse dado; consulta
ao vivo quando precisa responder sobre ele (mesmo princípio das views do
Core: consultar, não copiar).

SOMENTE LEITURA, e isso é regra, não estilo: o Shooting House é o
sistema de registro que reporta à Polícia Federal e ao Exército. A
credencial TEM permissão de escrita (registrar habitualidade, cadastrar
filiado, adicionar crédito), e é justamente por isso que nenhum caminho
de escrita existe aqui -- ver tests/test_shooting_house_somente_leitura.py,
que lê este arquivo e falha se alguém acrescentar um.

Pelo mesmo motivo, este módulo nunca guarda cópia do que leu: consulta
ao vivo, sempre. Dado regulatório com duas fontes é dado que uma hora
diverge, e a fonte que vale legalmente é a deles.

Enquanto a credencial (Basic Auth) não está configurada em .env
(SHOOTING_HOUSE_USER / SHOOTING_HOUSE_PASSWORD), as funções devolvem
dado simulado com "simulado": True -- permite testar o resto do
pipeline sem depender do suporte do Shooting House liberar acesso.
"""
import re
from datetime import datetime
from typing import Optional

import requests

from integracoes.config import (
    SHOOTING_HOUSE_BASE_URL,
    SHOOTING_HOUSE_PASSWORD,
    SHOOTING_HOUSE_USER,
    shooting_house_ativo,
    shooting_house_credencial_presente,
    validar_base_url,
)

# Quanto esperar a API responder antes de desistir. Curto de propósito:
# quem está esperando do outro lado é o poller (que roda a cada 2 min) e
# o Portal (com um cliente olhando a tela). Uma chamada pendurada trava
# a fila de atendimento inteira.
TIMEOUT_SEGUNDOS = 10


class ShootingHouseIndisponivel(Exception):
    """Não deu pra saber a resposta -- API fora do ar, credencial
    recusada, ou a consulta simplesmente ainda não tem implementação
    real. O ponto é que "não sei" NUNCA pode virar "não tem nada
    registrado" na resposta ao cliente: num domínio de arma de fogo,
    dizer a alguém que ele não tem CR registrado quando ele tem é pior
    do que não responder. Quem trata isso é motor_ia/consultor.py, que
    marca a fonte como indisponível e faz o atendimento ir pra um
    humano."""


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def _mascarar_cpf(cpf: str) -> str:
    """CPF vira ***.***.789-** em qualquer texto que possa acabar em log,
    e-mail de alerta ou banco.

    Isto não é preciosismo: a URL da API tem o CPF no caminho
    (.../habitualities/12345678900), e o erro que o requests levanta traz
    a URL inteira dentro da mensagem. Sem mascarar, um fora-do-ar da API
    escreveria CPF de cliente real em atendimento/poller.log, na coluna
    log_ia.erro do banco E num e-mail de alerta disparado por
    atendimento/alertas.py -- três lugares que ninguém trata como dado
    sensível."""
    digitos = _limpar_cpf(cpf or "")
    if len(digitos) != 11:
        return "(CPF inválido)"
    return f"***.***.{digitos[6:9]}-**"


def _chamar_api(caminho: str, params: Optional[dict] = None) -> dict:
    """Faz a chamada e transforma QUALQUER falha em
    ShootingHouseIndisponivel com mensagem já limpa de dado pessoal --
    nenhuma exceção crua do requests escapa daqui, justamente porque a
    mensagem crua carrega a URL com o CPF (ver _mascarar_cpf).

    allow_redirects=False de propósito: se a API responder um redirect
    para http:// (ou para outro host), o requests reenviaria a credencial
    Basic Auth para o novo endereço. Redirect aqui é tratado como falha,
    não seguido."""
    try:
        resposta = requests.get(
            f"{SHOOTING_HOUSE_BASE_URL}{caminho}",
            params=params,
            auth=(SHOOTING_HOUSE_USER, SHOOTING_HOUSE_PASSWORD),
            timeout=TIMEOUT_SEGUNDOS,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise ShootingHouseIndisponivel(
            f"Falha de rede ao consultar o Shooting House ({type(e).__name__})."
        ) from None  # from None: corta o encadeamento, senão a mensagem
        # original (com a URL e o CPF dentro) reaparece no traceback.

    if resposta.is_redirect or resposta.is_permanent_redirect:
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu com um redirecionamento, que não é "
            "seguido para não reenviar a credencial a outro endereço."
        )
    if resposta.status_code in (401, 403):
        raise ShootingHouseIndisponivel(
            "Shooting House recusou a credencial (verifique SHOOTING_HOUSE_USER "
            "e SHOOTING_HOUSE_PASSWORD no .env)."
        )
    if resposta.status_code == 404:
        # 404 aqui é ambíguo -- pode ser "atirador não existe" ou "rota
        # errada". Tratar como "não tem registro" seria justamente a
        # afirmação falsa que esta classe existe pra evitar.
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu 404 para esta consulta (atirador não "
            "encontrado ou endpoint mudou)."
        )
    if not resposta.ok:
        raise ShootingHouseIndisponivel(
            f"Shooting House respondeu HTTP {resposta.status_code}."
        )

    try:
        return resposta.json()
    except ValueError:
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu algo que não é JSON."
        ) from None


# Perfis variados para teste (ver core/db/gerar_clientes_ficticios.py) --
# CPF -> lista de eventos. Sem credencial de verdade, não dá pra saber o
# histórico real de ninguém, então cada CPF conhecido aqui simula um
# comportamento diferente (em dia / irregular / sem registro), para o
# pipeline poder ser testado contra respostas variadas, não sempre a mesma.
#
# Importante: nem todo cliente do despachante é atirador ativo do clube --
# transferência de arma, por exemplo, é serviço que o despachante presta
# mesmo para quem nunca pisou no clube (RCA de negócio confirmada com o
# usuário em 2026-07-23). Por isso o padrão para qualquer CPF NÃO listado
# aqui é "sem nenhum registro", não um perfil "em dia" inventado -- seria
# enganoso presumir habitualidade de quem nunca foi cadastrado como atirador.
#
# "arma" e "competicao" foram acrescentados em 2026-07-30, depois de ler a
# especificação real da API (SwaggerHub) -- lá, cada evento vem com o nome
# da arma usada (arma_formatada) e, quando o evento é uma competição (não
# um treino), o nome dela (competicao). Só esses dois campos foram
# adicionados -- a API real tem ~30 campos por evento (nr_sumula, cidade_uf,
# calibre, sigma etc.), mas sem ter visto uma resposta de verdade ainda,
# modelar tudo seria inventar detalhe que ninguém confirmou que o resto do
# projeto precisa. "modalidade" e "local" continuam com o mesmo sentido de
# antes: modalidade praticada e nome do clube/local do evento.
_PERFIS_HABITUALIDADE_TESTE = {
    "12345678900": [  # Felipe Bedani (CLI-000001) -- em dia, caso de Renovação de CR
        {"data_participacao": "15/01/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
        {"data_participacao": "12/03/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
        {"data_participacao": "20/05/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": "Copa Regional de Tiro Prático"},
        {"data_participacao": "18/07/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
    ],
    "10000000006": [  # Helena Costa -- em dia
        {"data_participacao": "10/02/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
        {"data_participacao": "14/04/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
        {"data_participacao": "09/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
    ],
    "10000000014": [  # Vanessa Teixeira -- em dia
        {"data_participacao": "05/01/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "03/03/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "07/05/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "12/07/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": "Campeonato Estadual de Tiro Esportivo"},
    ],
    "10000000015": [  # William Cardoso -- irregular, só 1 participação
        {"data_participacao": "22/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G2C", "competicao": None},
    ],
    "10000000020": [],  # Larissa Barbosa -- sem nenhum registro
}


def _habitualidade_simulada(cpf: str) -> dict:
    # Default = sem registro, não um perfil "em dia" -- ver comentário acima.
    eventos = _PERFIS_HABITUALIDADE_TESTE.get(cpf, [])
    return {
        "simulado": True,
        "idatirador": 0,
        "atirador": "(dado simulado -- credencial do Shooting House ainda não configurada)",
        "cpf": cpf,
        "cr": None,
        "habitualidades": (
            {"ACLP": {"count": len(eventos), "eventos": eventos}} if eventos else {}
        ),
    }


# Perfis de CR pra teste -- só o Felipe (atirador de verdade nos testes,
# ver _PERFIS_HABITUALIDADE_TESTE acima) tem CR simulado; qualquer outro
# CPF não cadastrado aqui não tem CR nenhum (mesmo princípio "cliente não
# é necessariamente atirador" da habitualidade).
#
# categoria/data_ultima_confirmacao/nivel_cr são o dado bruto -- nivel_cr
# (1 a 3) ainda não tem endpoint conhecido no Shooting House, então por
# enquanto é cadastrado manualmente aqui mesmo (mesmo padrão de
# categoria_cr): pedido do usuário 2026-07-25, sem regra automática de
# cálculo por enquanto (não fabricar um critério que não foi confirmado
# com o cliente/órgão regulador). proxima_confirmacao é CALCULADA aqui em
# Python (nunca pela IA -- data é aritmética, não interpretação de texto,
# e LLM erra conta com facilidade). Só datas de referência, sem contagem
# de dias restantes -- decisão do usuário pra não soar como uma contagem
# regressiva de "vencimento" (o CR não vence).
#
# data_expiracao_bruta (2026-07-30): a especificação real da API tem um
# campo `documents.cr.expirationDate` em GET /registers/shooters/{id} --
# ao contrário do que este módulo assumia até agora ("endpoint real ainda
# não documentado"). Existe, então, mas com uma ressalva: pelo Decreto nº
# 11.615/2023, já confirmado com o usuário, o CR do atirador desportivo
# NÃO tem prazo fixo de vencimento -- então esse campo bruto da API não
# necessariamente significa "quando o CR vence" para efeito de resposta ao
# cliente. Por isso ele é mantido aqui separado de proxima_confirmacao,
# só para o pipeline já ter o campo disponível e testável -- nenhuma
# lógica de negócio lê data_expiracao_bruta ainda. Decidir o que fazer com
# ele (ignorar, ou é a data de emissão do CRAF do porte, algo diferente do
# CR desportivo) só quando a credencial real existir e der pra confirmar
# o que o campo de fato representa.
_PERFIS_CR_TESTE = {
    "12345678900": {  # Felipe Bedani -- Atirador Desportivo
        "categoria_cr": "Atirador Desportivo",
        "data_ultima_confirmacao": "01/09/2025",
        "nivel_cr": 2,
        "data_expiracao_bruta": "01/09/2026",
    },
}


def _cr_simulado(cpf: str) -> Optional[dict]:
    perfil = _PERFIS_CR_TESTE.get(cpf)
    if not perfil:
        return None

    data_confirmacao = datetime.strptime(perfil["data_ultima_confirmacao"], "%d/%m/%Y").date()
    proxima_confirmacao = data_confirmacao.replace(year=data_confirmacao.year + 1)

    return {
        "simulado": True,
        "cpf": cpf,
        "categoria_cr": perfil["categoria_cr"],
        "data_ultima_confirmacao": perfil["data_ultima_confirmacao"],
        "proxima_confirmacao": proxima_confirmacao.strftime("%d/%m/%Y"),
        "nivel_cr": perfil.get("nivel_cr"),
        "data_expiracao_bruta": perfil.get("data_expiracao_bruta"),
    }


# Perfis de armas pra teste -- espelha GET /registers/shooters/weapon/
# {shooterId} da API real. Esse endpoint real pede o ID interno do
# Shooting House (idatirador), não CPF -- este módulo não sabe converter
# um pro outro ainda (precisaria de um GET /registers/shooters/paginate
# ou busca equivalente por CPF, que não foi confirmado que existe com
# filtro direto). Por isso, mesmo padrão de consultar_cr: sempre simulado,
# até essa resolução CPF -> idatirador existir de verdade.
_PERFIS_ARMAS_TESTE = {
    "12345678900": [  # Felipe Bedani
        {"id": 1, "model": "G3", "brand": "Taurus", "caliber": ".40 S&W", "serie": "TA123456", "type": "Pistola"},
    ],
    "10000000006": [  # Helena Costa
        {"id": 2, "model": "G3", "brand": "Glock", "caliber": "9mm", "serie": "GL654321", "type": "Pistola"},
    ],
}


def consultar_armas(cpf: str) -> list[dict]:
    """Armas registradas do atirador. Devolve lista vazia se o CPF não
    tem arma simulada cadastrada -- nem todo cliente é atirador (mesma
    regra de consultar_habitualidade). Ver comentário acima de
    _PERFIS_ARMAS_TESTE sobre por que ainda não tem modo real.

    Com o modo real LIGADO, levanta ShootingHouseIndisponivel em vez de
    cair no simulado. Sem isso, um cliente de verdade perguntando "quais
    armas tenho registradas?" receberia lista vazia -- porque o CPF dele
    não está entre os de teste -- e a IA responderia "nenhuma arma
    registrada" com toda a confiança. Resposta falsa, sobre arma de
    fogo, para a pessoa errada."""
    if shooting_house_ativo():
        raise ShootingHouseIndisponivel(
            "Consulta de armas ainda não tem implementação real: o endpoint "
            "do Shooting House pede o ID interno do atirador (idatirador), e "
            "a conversão CPF -> idatirador ainda não existe neste projeto."
        )
    return _PERFIS_ARMAS_TESTE.get(_limpar_cpf(cpf), [])


# Perfis de documentos com vencimento pra teste -- espelha GET /registers/
# shooters/documentos-por-data-vencimento da API real. Esse endpoint real
# é filtrado por INTERVALO DE DATA (dataInicio/dataFinal) e devolve o
# clube inteiro de uma vez, não por CPF -- pra usar isso de verdade
# precisaria buscar o idatirador do CPF e filtrar a resposta em massa por
# ele, o que ainda não está implementado (mesma ressalva de
# consultar_armas acima). "liberado" = documento já pode ser retirado/
# usado; "arquivo_url" fica None no simulado (não existe arquivo de
# verdade pra baixar).
_PERFIS_DOCUMENTOS_VENCIMENTO_TESTE = {
    "12345678900": [  # Felipe Bedani
        {
            "idarma": 1,
            "arma": "Pistola Taurus G3 .40 S&W",
            "cr": "12345",
            "guia_trafego": [
                {"vencimento": "10/12/2026", "arquivo_url": None, "liberado": True, "observacao": None},
            ],
            "simaf": [
                {"vencimento": "05/03/2027", "arquivo_url": None, "liberado": True},
            ],
        },
    ],
}


def consultar_documentos_vencimento(cpf: str) -> list[dict]:
    """Guia de tráfego e SIMAF por arma do atirador, com data de
    vencimento e link de download. Lista vazia = sem arma/documento
    simulado cadastrado para este CPF. Ver comentário acima de
    _PERFIS_DOCUMENTOS_VENCIMENTO_TESTE sobre por que ainda não tem modo
    real.

    Mesma trava de consultar_armas com o modo real ligado -- e aqui o
    risco é ainda mais concreto: dizer a um atirador que a guia de
    tráfego dele está em dia (ou que não existe) sem ter consultado nada
    pode fazê-lo transportar arma com documento vencido."""
    if shooting_house_ativo():
        raise ShootingHouseIndisponivel(
            "Consulta de guia de tráfego/SIMAF ainda não tem implementação "
            "real: o endpoint do Shooting House filtra por intervalo de data "
            "e devolve o clube inteiro, sem busca por CPF."
        )
    return _PERFIS_DOCUMENTOS_VENCIMENTO_TESTE.get(_limpar_cpf(cpf), [])


# Nomes dos campos-array da resposta real de habitualidade (colunares,
# paralelos por índice dentro de cada arma) que este módulo sabe mapear
# pro formato simples já consumido por portal/app.py e motor_ia/
# consultor.py. Só os campos abaixo -- a resposta real tem dezenas de
# outros (nr_sumula, cidade_uf, sigma, cms_id...) sem descrição conferida,
# então mapear todos seria inventar sentido para campo que ninguém viu
# numa resposta de verdade ainda.
#
# CONFERIDO contra a especificação em 2026-08-25: os cinco campos usados
# (os quatro abaixo + data_participacao) existem mesmo, com estes nomes.
# Duas ressalvas descobertas na mesma leitura, que valem na hora de olhar
# uma resposta de verdade:
#
# - `competicao` NÃO é "nome da competição ou vazio", como o dado
#   simulado deste módulo sempre fingiu. Num treino comum ela vem com o
#   texto "TREINO". Ou seja, o filtro `if v` do Redator não a descarta, e
#   a IA recebe "competicao: TREINO" -- que ela pode fraseiar como
#   "Competição: TREINO" pro cliente. Conferir na primeira resposta real.
# - `arma_formatada` traz o número de série embutido no texto
#   ("(ABA212416) Pistola - TH380 CLUBE - 380 ACP"). É por isso que
#   mascarar só um campo chamado "serie" não bastaria pra manter número
#   de série fora do prompt da OpenAI.
_CAMPOS_EVENTO_HABITUALIDADE_REAL = {
    "modalidades_simples": "modalidade",
    "local": "local",
    "arma_formatada": "arma",
    "competicao": "competicao",
}


def _separar_data_e_hora(valor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """A API real manda "09/10/2025 16:30" -- data E hora no mesmo campo.

    Bug pego lendo a especificação (2026-08-25), antes de acontecer: todo
    o resto do projeto trata `data_participacao` como só o dia, e
    `portal/app.py` faz `strptime(..., "%d/%m/%Y")` para ordenar a lista.
    Com a hora colada, esse strptime levanta ValueError e a tela de
    Habitualidade do Portal quebra inteira -- na primeira consulta real,
    para o primeiro atirador de verdade.

    A hora não é jogada fora (é informação legítima de um treino), só
    guardada separada em `hora_participacao`."""
    if not valor:
        return None, None
    partes = str(valor).strip().split(" ", 1)
    dia = partes[0] or None
    hora = partes[1].strip() if len(partes) > 1 and partes[1].strip() else None
    return dia, hora


def _normalizar_habitualidade_real(dados_brutos: dict) -> dict:
    """Converte a resposta real de GET /registers/habitualities/{cpf} --
    colunar, agrupada em habitualidades[grupo_arma][id_arma] com arrays
    paralelos por índice -- no MESMO formato simples que o dado simulado
    sempre teve: habitualidades[grupo_arma] = {"count":, "eventos": [{...}
    ]}. Sem essa conversão, portal/app.py e motor_ia/consultor.py quebram
    no primeiro CPF consultado de verdade, porque os dois esperam
    "eventos" direto dentro de cada grupo, não mais um nível de arma por
    baixo.

    Estrutura inferida da documentação (SwaggerHub) em 2026-07-30 --
    NUNCA testada contra uma resposta real, porque a credencial ainda não
    foi liberada. Conferir e ajustar os nomes de campo aqui assim que a
    primeira resposta de verdade chegar (ver _CAMPOS_EVENTO_HABITUALIDADE_REAL).
    """
    habitualidades_brutas = dados_brutos.get("habitualidades") or {}
    habitualidades = {}
    for grupo_arma, armas in habitualidades_brutas.items():
        eventos = []
        for dados_arma in (armas or {}).values():
            datas = dados_arma.get("data_participacao") or []
            for indice, data in enumerate(datas):
                data_dia, hora = _separar_data_e_hora(data)
                evento = {"data_participacao": data_dia, "hora_participacao": hora}
                for campo_real, campo_normalizado in _CAMPOS_EVENTO_HABITUALIDADE_REAL.items():
                    valores = dados_arma.get(campo_real) or []
                    if indice < len(valores):
                        evento[campo_normalizado] = valores[indice]
                eventos.append(evento)
        habitualidades[grupo_arma] = {"count": len(eventos), "eventos": eventos}

    return {
        "simulado": False,
        "idatirador": dados_brutos.get("idatirador"),
        "atirador": dados_brutos.get("atirador"),
        "matricula": dados_brutos.get("matricula"),
        "cr": dados_brutos.get("cr"),
        "cpf": dados_brutos.get("cpf"),
        "habitualidades": habitualidades,
    }


def verificar_credencial() -> dict:
    """Bate no GET /checkAuth, que só responde "a autenticação vale ou
    não" -- sem CPF, sem nome, sem dado de pessoa nenhuma no caminho da
    URL nem na resposta.

    É a forma certa de descobrir se a credencial recebida pertence ao
    ambiente configurado em SHOOTING_HOUSE_BASE_URL: credencial de
    produção batendo no servidor de homologação (ou o contrário) é
    recusada, e a recusa já é a resposta. Antes de existir este caminho,
    a única maneira de testar era consultar a habitualidade de alguém --
    ou seja, usar o dado de uma pessoa real como material de teste.

    Devolve {"ok": bool, "detalhe": str}. Não levanta exceção: quem chama
    é diagnóstico, e "falhou" aqui é resultado, não erro de programação.
    """
    if not shooting_house_credencial_presente():
        return {"ok": False, "detalhe": "Credencial não configurada no .env."}
    try:
        validar_base_url()
        _chamar_api("/checkAuth")
    except (ShootingHouseIndisponivel, RuntimeError) as e:
        return {"ok": False, "detalhe": str(e)}
    return {"ok": True, "detalhe": "Credencial aceita por este servidor."}


def consultar_cr(cpf: str) -> Optional[dict]:
    """Status de confirmação cadastral do CR do atirador desportivo --
    diferente de habitualidade (frequência de treino/competição). Pelo
    Decreto nº 11.615/2023, o CR do atirador desportivo não tem prazo
    fixo de vencimento: continua válido enquanto a confirmação cadastral
    anual + a habitualidade mínima estiverem em dia (ver domain/clube_
    tiro/db/popular_conhecimento.py). Devolve None se o CPF não tem CR
    registrado (nem todo cliente é atirador -- mesma regra já aplicada em
    consultar_habitualidade).

    Endpoint real do Shooting House para isso ainda não foi documentado/
    testado -- por enquanto sempre devolve dado simulado, mesmo com
    credencial configurada. Com o modo real ligado, levanta
    ShootingHouseIndisponivel em vez de devolver None (mesma razão de
    consultar_armas: None aqui seria lido como "este cliente não tem CR",
    e a IA diria isso a um atirador que tem).
    """
    if shooting_house_ativo():
        raise ShootingHouseIndisponivel(
            "Consulta de CR ainda não tem implementação real: falta confirmar "
            "com o Shooting House qual endpoint devolve a confirmação "
            "cadastral do CR por CPF."
        )
    return _cr_simulado(_limpar_cpf(cpf))


def consultar_habitualidade(
    cpf: str,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> dict:
    cpf_limpo = _limpar_cpf(cpf)

    if not shooting_house_ativo():
        return _habitualidade_simulada(cpf_limpo)

    if len(cpf_limpo) != 11:
        # Não manda pra API o que já se sabe que é inválido -- CPF entra
        # na URL, e texto solto de cliente ("meu cpf é o mesmo de antes")
        # não tem por que virar caminho de requisição.
        raise ShootingHouseIndisponivel("CPF inválido para consulta.")

    params = {}
    if data_inicio:
        params["startDate"] = data_inicio
    if data_fim:
        params["endDate"] = data_fim

    dados = _chamar_api(f"/registers/habitualities/{cpf_limpo}", params)
    dados = dados[0] if isinstance(dados, list) and dados else dados
    if not isinstance(dados, dict):
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu num formato inesperado para habitualidade."
        )
    return _normalizar_habitualidade_real(dados)


if __name__ == "__main__":
    # Teste de fumaça com o CPF fictício de sempre. Recusa rodar com o
    # modo real ligado: este bloco imprime a resposta inteira na tela, e
    # com credencial de verdade isso seria despejar o histórico de
    # treinos e as armas de uma pessoa real no terminal (e no histórico
    # do PowerShell). Para conferir a API real existe outro caminho, que
    # mostra só a ESTRUTURA da resposta e nenhum valor:
    #     .venv\Scripts\python.exe -m integracoes.diagnostico_shooting_house
    if shooting_house_ativo():
        raise SystemExit(
            "Modo real ligado (SHOOTING_HOUSE_ATIVO=Sim). Este teste de fumaça "
            "imprime dado pessoal na tela e por isso não roda assim.\n"
            "Use: .venv\\Scripts\\python.exe -m integracoes.diagnostico_shooting_house"
        )

    resultado = consultar_habitualidade("12345678900")
    print(f"Modo simulado: {resultado.get('simulado', False)}")
    print(resultado)

    print()
    print("CR:", consultar_cr("12345678900"))

    print()
    print("Armas:", consultar_armas("12345678900"))

    print()
    print("Documentos com vencimento:", consultar_documentos_vencimento("12345678900"))
