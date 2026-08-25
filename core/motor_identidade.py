"""Decide se uma mensagem que chegou por um canal não autenticado pode
receber de volta dado sensível do atirador (habitualidade, CR, armas
registradas, guia de tráfego, SIMAF).

REGRA DE NEGÓCIO, por isso vive no Core e não no Motor IA -- "quem pode
ver o quê" nunca é decisão de IA (mesmo princípio de motor_casos.py, que
guarda a lista de status válidos, e de motor_usuarios.py, que guarda os
papéis).

O problema que isto resolve
---------------------------
Até aqui, o sistema decidia quem era o remetente pelo endereço de e-mail
do cabeçalho "De:" -- e falsificar esse cabeçalho é trivial, o poller não
confere SPF nem DKIM. Enquanto tudo era dado simulado, o pior caso era
uma resposta errada. Com a API do Shooting House ligada, o pior caso
passa a ser: alguém escreve de um endereço forjado, pergunta "quais
armas eu tenho registradas?", e recebe modelo, calibre e número de série
de armas de verdade, com o endereço do dono no cadastro. Isso é uma
lista de compras para um roubo.

O que a regra faz
-----------------
Para as intenções sensíveis, exige que o CPF esteja escrito NA PRÓPRIA
MENSAGEM e que ele bata com o CPF do cadastro de quem o e-mail/telefone
identificou. Quem só falsificou o endereço não passa; quem é o cliente
de verdade escreve o CPF e é atendido na hora, sem depender de alguém
ler o e-mail.

Isto NÃO é autenticação forte, e é importante ser honesto sobre isso:
CPF no Brasil circula muito, e quem tiver o CPF **e** falsificar o e-mail
passa pelo portão. O que a regra faz é subir o degrau de "qualquer um que
saiba o e-mail" para "alguém que saiba e-mail e CPF da mesma pessoa", e
compor com os outros freios que já existem (revisão humana ligada,
filtro por empresa, registro de acesso). Autenticação de verdade para
dado sensível é o link mágico do Portal do Cliente -- por isso o Portal,
que tem login, não passa por este portão.
"""
import hmac
import re
from dataclasses import dataclass
from typing import Optional, Sequence

# Formatos de CPF que aparecem em texto escrito por gente: 123.456.789-00,
# 12345678900, "123 456 789 00". As bordas \b evitam pegar o meio de um
# número maior.
#
# O padrão é deliberadamente frouxo -- ele também casa com um telefone de
# 11 dígitos, e isso é aceitável nos dois usos que ele tem. Na extração,
# porque o candidato só vale se BATER com o CPF do cadastro (um telefone
# nunca bate). No mascaramento, porque esconder um telefone por engano
# antes de mandar o texto pra OpenAI é errar para o lado certo.
#
# Validar dígito verificador foi considerado e descartado: não melhora a
# segurança (a comparação contra o cadastro já é exata) e quebraria os
# CPFs fictícios usados no projeto inteiro, que não têm dígito válido.
_PADRAO_CPF = re.compile(r"\b\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[-.\s]?\d{2}\b")

# Intenções cuja resposta expõe dado do atirador vindo do Shooting House.
# Note que CONSULTA_PROCESSO e CONSULTA_CLIENTE ficaram DE FORA: elas
# falam do serviço contratado aqui (status do caso, prazo), não de arma
# nem de habitualidade. Se um dia expuserem dado de arma, entram aqui.
INTENCOES_DADO_SENSIVEL = frozenset({
    "CONSULTA_HABITUALIDADE",
    "CONSULTA_CR",
    "CONSULTA_DOCUMENTOS_VENCIMENTO",
})

# Canais em que já se sabe quem é a pessoa antes de a mensagem chegar.
# Hoje está vazio de propósito: e-mail e WhatsApp identificam por
# endereço/número, e nenhum dos dois é prova de identidade. O Portal do
# Cliente não entra aqui porque nem passa pelo orquestrador -- ele lê o
# Shooting House direto, depois de um login por link mágico.
CANAIS_AUTENTICADOS = frozenset()

# Por qual identificador NÃO basta ter sido encontrado para receber dado
# sensível (ver motor_ia/identificador_cliente.py, chave
# "identificado_por").
#
# "nome" está aqui porque é o único dos quatro que o próprio remetente
# escolhe na mesma mensagem: o nome exibido no cabeçalho "De:" é texto
# livre, quem manda escreve o que quiser. Alguém que descubra o nome e o
# CPF de um atirador -- e os dois circulam -- poderia se identificar como
# ele sem precisar nem falsificar endereço: bastaria assinar o e-mail
# como "Fulano de Tal". Com isso, o portão de CPF não seria portão
# nenhum, porque as duas metades viriam da mesma mão.
#
# E-mail e telefone também são falsificáveis, mas em outro grau: exigem
# saber (e forjar) um endereço que já está no cadastro. Somados ao CPF,
# são dois fatos independentes sobre a pessoa.
ORIGENS_INSUFICIENTES = frozenset({"nome"})


@dataclass
class ResultadoIdentidade:
    liberado: bool
    motivo: Optional[str] = None


def _so_digitos(valor: Optional[str]) -> str:
    return re.sub(r"\D", "", valor or "")


def mascarar_cpf(valor: Optional[str]) -> str:
    """***.***.789-** -- guarda três dígitos, o suficiente pra uma pessoa
    conferir "é o meu" sem que o número reste utilizável."""
    digitos = _so_digitos(valor)
    if len(digitos) != 11:
        return "***"
    return f"***.***.{digitos[6:9]}-**"


def extrair_cpfs(texto: Optional[str]) -> list[str]:
    """Todos os CPFs escritos no texto, só dígitos, sem repetir.

    Feito em Python, e não pela IA, de propósito. O Classificador já
    devolvia um campo `cpf_mencionado`, e o portão de identidade chegou a
    usá-lo -- o que apoiava uma decisão de SEGURANÇA na saída de um
    modelo probabilístico, extraída de dentro da mesma mensagem que um
    atacante escreve. Uma mensagem construída pra confundir o modelo
    passava a ter um caminho até o portão. Achar dígito em texto é
    trabalho de expressão regular: determinístico, auditável, e imune a
    qualquer instrução escondida no meio do texto."""
    vistos = []
    for achado in _PADRAO_CPF.findall(texto or ""):
        digitos = _so_digitos(achado)
        if len(digitos) == 11 and digitos not in vistos:
            vistos.append(digitos)
    return vistos


def mascarar_cpfs_no_texto(texto: Optional[str]) -> str:
    """Troca todo CPF do texto pela versão mascarada.

    Usado no texto que vai pra OpenAI (ver motor_ia/orquestrador.py). O
    portão de identidade pede ao cliente que escreva o CPF na mensagem --
    ou seja, ele próprio criou um fluxo constante de CPF de gente real
    saindo desta máquina para um serviço de terceiro. Mascarar aqui
    devolve isso ao lugar: o Classificador precisa entender a intenção
    da frase, não precisa do número.

    O texto ORIGINAL continua sendo o que se grava em `mensagem` e na
    sessão -- o banco é nosso, e ali o dado completo é legítimo e
    necessário. O que muda é só o que atravessa a rede."""
    if not texto:
        return texto or ""
    return _PADRAO_CPF.sub(lambda m: mascarar_cpf(m.group(0)), texto)


def exige_confirmacao_cpf(intencao: str, canal: str) -> bool:
    return intencao in INTENCOES_DADO_SENSIVEL and canal not in CANAIS_AUTENTICADOS


def verificar_acesso_dado_sensivel(
    intencao: str,
    canal: str,
    cpfs_mencionados: Optional[Sequence[str]],
    cpf_cadastro: Optional[str],
    identificado_por: Optional[str] = None,
) -> ResultadoIdentidade:
    """`cpfs_mencionados` são os CPFs que `extrair_cpfs()` achou escritos
    no texto da mensagem -- em Python, nunca pela IA (ver extrair_cpfs);
    `cpf_cadastro` é o do cliente que o e-mail/telefone identificou no
    banco.

    É uma lista, não um valor, porque uma mensagem pode citar mais de um
    número ("meu CPF é X, o do meu filho é Y") e porque o padrão de busca
    também casa com telefone. Basta UM bater com o cadastro: os outros
    candidatos simplesmente não batem, e nada é liberado por causa deles.

    Falha fechado: sem CPF no cadastro, sem CPF na mensagem, ou os dois
    diferentes, não libera. O motivo devolvido é para o log interno -- a
    mensagem ao cliente é sempre a mesma, escrita pelo orquestrador, e
    de propósito não conta qual dos casos aconteceu: dizer "esse CPF não
    confere" para quem está tentando adivinhar já é confirmar que o
    endereço de e-mail pertence a alguém, e transforma o portão num
    verificador de palpites.
    """
    if not exige_confirmacao_cpf(intencao, canal):
        return ResultadoIdentidade(liberado=True)

    if identificado_por in ORIGENS_INSUFICIENTES:
        return ResultadoIdentidade(
            liberado=False,
            motivo=f"Cliente foi identificado apenas por {identificado_por}.",
        )

    if not cpf_cadastro:
        return ResultadoIdentidade(
            liberado=False, motivo="Cliente identificado não tem CPF no cadastro."
        )
    candidatos = [
        _so_digitos(c) for c in (cpfs_mencionados or []) if len(_so_digitos(c)) == 11
    ]
    if not candidatos:
        return ResultadoIdentidade(
            liberado=False, motivo="CPF não foi informado na mensagem."
        )

    cadastrado = _so_digitos(cpf_cadastro)
    # compare_digest em vez de "==": compara em tempo constante, sem
    # parar no primeiro dígito diferente. O ganho prático aqui é pequeno
    # (o gargalo do atendimento é a chamada de IA, que abafa qualquer
    # medição), mas comparação de segredo é um daqueles hábitos que só
    # valem se forem sempre. Todos os candidatos são percorridos mesmo
    # depois de um acerto, pelo mesmo motivo.
    conferiu = False
    for candidato in candidatos:
        if hmac.compare_digest(candidato, cadastrado):
            conferiu = True

    if not conferiu:
        return ResultadoIdentidade(
            liberado=False, motivo="Nenhum CPF informado confere com o do cadastro."
        )

    return ResultadoIdentidade(liberado=True)


if __name__ == "__main__":
    exemplo = "Bom dia, meu CPF é 123.456.789-00 e meu telefone 14999998888."
    print("Texto original :", exemplo)
    print("Extraído       :", extrair_cpfs(exemplo))
    print("Vai pra OpenAI :", mascarar_cpfs_no_texto(exemplo))
    print()

    casos = [
        ("CONSULTA_HABITUALIDADE", "Email", ["12345678900"], "12345678900", "email"),
        ("CONSULTA_HABITUALIDADE", "Email", [], "12345678900", "email"),
        ("CONSULTA_HABITUALIDADE", "Email", ["11122233344"], "12345678900", "email"),
        ("CONSULTA_HABITUALIDADE", "Email", ["11122233344", "12345678900"], "12345678900", "email"),
        ("CONSULTA_HABITUALIDADE", "Email", ["12345678900"], "12345678900", "nome"),
        ("CONSULTA_HABITUALIDADE", "WhatsApp", ["12345678900"], None, "telefone"),
        ("CONSULTA_PROCESSO", "Email", [], "12345678900", "nome"),
        ("ATENDIMENTO_GERAL", "Email", [], None, "nome"),
    ]
    for intencao, canal, mencionados, cadastro, origem in casos:
        r = verificar_acesso_dado_sensivel(intencao, canal, mencionados, cadastro, origem)
        print(f"{intencao:32} {canal:9} por {origem:9} -> "
              f"liberado={r.liberado}  {r.motivo or ''}")
