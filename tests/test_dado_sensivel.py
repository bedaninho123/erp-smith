"""As travas que passaram a existir quando a credencial real do Shooting
House chegou (2026-08-25).

Enquanto tudo era dado simulado, um erro aqui produzia uma resposta
errada. Com a API real ligada, o mesmo erro entrega número de série de
arma, calibre e histórico de treino de uma pessoa de verdade -- para
quem por acaso escreveu de um endereço parecido, ou para quem falsificou
um. Por isso estas quatro coisas viraram teste, e não só comentário:

1. identificação ambígua não escolhe ninguém;
2. dado sensível exige CPF confirmado, e nunca sai de uma identificação
   feita só pelo nome escrito no cabeçalho do e-mail;
3. consulta que não pôde ser feita nunca vira "não há registro";
4. CPF não aparece em texto de erro (que vai pra log, banco e e-mail).

Nenhum teste aqui chama a OpenAI nem a API do Shooting House.
"""
from datetime import datetime

import pytest
import requests

from core.motor_identidade import (
    ORIGENS_INSUFICIENTES,
    exige_confirmacao_cpf,
    extrair_cpfs,
    mascarar_cpfs_no_texto,
    verificar_acesso_dado_sensivel,
)
from integracoes import shooting_house
from integracoes.shooting_house import (
    ShootingHouseIndisponivel,
    _mascarar_cpf,
    _normalizar_habitualidade_real,
    consultar_armas,
    consultar_cr,
    consultar_documentos_vencimento,
    consultar_habitualidade,
)
from motor_ia.auditor import auditar
from motor_ia.classificador import ResultadoClassificacao
from motor_ia.consultor import _buscar_externo
from motor_ia.identificador_cliente import identificar_cliente
from motor_ia.planejador import Plano
from motor_ia.redator import _arma_sem_serie, montar_bloco_dados

from tests.conftest import EMPRESA_A

CPF_DE_TESTE = "12345678900"


@pytest.fixture
def modo_real(monkeypatch):
    """Finge que a credencial está configurada e a chave geral ligada,
    sem tocar no .env de verdade nem fazer chamada nenhuma."""
    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)


# --------------------------------------------------------------------
# 1. Identificação ambígua não escolhe ninguém
# --------------------------------------------------------------------

def test_telefone_repetido_nao_identifica_ninguem(banco):
    """Ana e Bruno são da mesma empresa e têm o mesmo telefone no
    fixture. Antes disto o código fazia fetchone() e devolvia calado
    aquele que o SQLite varresse primeiro -- ordem que ninguém controla.

    O sistema seguia o atendimento inteiro tratando um como se fosse o
    outro: consultava o processo dele, a habitualidade dele, as armas
    dele. Não escolher é a única resposta certa aqui."""
    achado = identificar_cliente(EMPRESA_A, telefone="14999990000")

    assert achado is None


def test_nome_parcial_que_casa_com_dois_nao_identifica_ninguem(banco):
    """"Teste" é sobrenome de Ana e de Bruno. A busca por aproximação é
    a mais frouxa das quatro e é onde a colisão acontece de verdade."""
    achado = identificar_cliente(EMPRESA_A, nome="Teste")

    assert achado is None


def test_identificacao_sem_ambiguidade_continua_funcionando(banco):
    """Controle positivo: sem isto, um identificador que recusasse tudo
    passaria nos dois testes acima."""
    achado = identificar_cliente(EMPRESA_A, email="ana@example.com")

    assert achado["cliente_id"] == "CLI-000001"
    assert achado["identificado_por"] == "email"


def test_origem_da_identificacao_vem_marcada(banco):
    achado = identificar_cliente(EMPRESA_A, nome="Ana Teste")

    assert achado["identificado_por"] == "nome"


# --------------------------------------------------------------------
# 2. Portão de identidade para dado sensível
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "intencao",
    ["CONSULTA_HABITUALIDADE", "CONSULTA_CR", "CONSULTA_DOCUMENTOS_VENCIMENTO"],
)
def test_intencoes_de_arma_exigem_cpf_por_email(intencao):
    assert exige_confirmacao_cpf(intencao, "Email") is True
    assert exige_confirmacao_cpf(intencao, "WhatsApp") is True


@pytest.mark.parametrize(
    "intencao", ["ATENDIMENTO_GERAL", "CONSULTA_PROCESSO", "CONSULTA_DOCUMENTOS"]
)
def test_intencoes_comuns_nao_exigem_cpf(intencao):
    """O portão é estreito de propósito: exigir CPF pra perguntar horário
    de funcionamento seria transformar o atendimento num interrogatório."""
    assert exige_confirmacao_cpf(intencao, "Email") is False


def test_cpf_certo_libera():
    resultado = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email",
        cpfs_mencionados=["123.456.789-00"], cpf_cadastro=CPF_DE_TESTE,
        identificado_por="email",
    )

    assert resultado.liberado is True


@pytest.mark.parametrize(
    "cpfs_mencionados, cpf_cadastro",
    [
        ([], CPF_DE_TESTE),               # não informou o CPF
        (["11122233344"], CPF_DE_TESTE),  # informou o de outra pessoa
        (["123"], CPF_DE_TESTE),          # informou algo que não é CPF
        ([CPF_DE_TESTE], None),           # cadastro sem CPF: não dá pra conferir
    ],
)
def test_sem_cpf_conferido_nao_libera(cpfs_mencionados, cpf_cadastro):
    resultado = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email",
        cpfs_mencionados=cpfs_mencionados, cpf_cadastro=cpf_cadastro,
        identificado_por="email",
    )

    assert resultado.liberado is False


def test_identificado_so_pelo_nome_nunca_libera_mesmo_com_cpf_certo():
    """O caso que anularia o portão inteiro: o nome exibido no cabeçalho
    "De:" é escolhido por quem manda a mensagem. Se ele valesse como
    identificação, o atacante forneceria as duas metades -- nome e CPF --
    na mesma mensagem, e o portão não estaria conferindo nada contra
    nada."""
    resultado = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email",
        cpfs_mencionados=[CPF_DE_TESTE], cpf_cadastro=CPF_DE_TESTE,
        identificado_por="nome",
    )

    assert resultado.liberado is False
    assert "nome" in ORIGENS_INSUFICIENTES


def test_motivo_da_recusa_nunca_vira_dica():
    """Os motivos existem pro log interno. A mensagem que vai pro cliente
    é fixa (montada no orquestrador) justamente pra não confirmar se o
    e-mail existe nem se o CPF chegou perto -- senão o portão vira um
    verificador de palpites."""
    sem_cpf = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email", [], CPF_DE_TESTE, "email"
    )
    cpf_errado = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email", ["11122233344"], CPF_DE_TESTE, "email"
    )

    assert sem_cpf.liberado is cpf_errado.liberado is False
    assert sem_cpf.motivo != cpf_errado.motivo  # distintos só no log


# --------------------------------------------------------------------
# 2b. O CPF sai do texto em Python, não pela IA
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("meu CPF é 123.456.789-00", ["12345678900"]),
        ("cpf 12345678900 obrigado", ["12345678900"]),
        ("CPF: 123 456 789 00", ["12345678900"]),
        ("meu 123.456.789-00 e o do meu filho 111.222.333-44",
         ["12345678900", "11122233344"]),
        ("citei 123.456.789-00 duas vezes: 123.456.789-00", ["12345678900"]),
        ("não tenho CPF aqui", []),
        ("protocolo PROTO-2026-001", []),
    ],
)
def test_extracao_de_cpf_do_texto(texto, esperado):
    assert extrair_cpfs(texto) == esperado


def test_cpf_certo_no_meio_de_varios_libera():
    """Mensagem que cita mais de um número não pode travar o cliente de
    verdade -- basta um dos candidatos bater com o cadastro."""
    resultado = verificar_acesso_dado_sensivel(
        "CONSULTA_HABITUALIDADE", "Email",
        cpfs_mencionados=["11122233344", CPF_DE_TESTE],
        cpf_cadastro=CPF_DE_TESTE, identificado_por="email",
    )

    assert resultado.liberado is True


def test_texto_que_vai_pra_openai_nao_leva_cpf():
    """O portão de identidade pede ao cliente que escreva o CPF na
    mensagem -- ou seja, ele mesmo criou um fluxo constante de CPF real
    saindo desta máquina para um serviço de terceiro. O Classificador
    precisa da intenção da frase, não do número."""
    original = "Bom dia, meu CPF é 123.456.789-00, queria saber da habitualidade."

    mascarado = mascarar_cpfs_no_texto(original)

    assert CPF_DE_TESTE not in mascarado
    assert "123.456.789-00" not in mascarado
    assert "***.***.789-**" in mascarado
    # O resto da frase continua inteiro -- senão o Classificador perde a
    # intenção junto com o número.
    assert "habitualidade" in mascarado
    assert mascarado.startswith("Bom dia")


def test_classificacao_da_ia_nao_tem_mais_voto_no_portao(banco, monkeypatch):
    """A trava de verdade: mesmo que a IA devolva um cpf_mencionado
    perfeito, quem manda é o que o Python extraiu do texto. Aqui a
    mensagem NÃO tem CPF nenhum, e a IA afirma que tem -- é o formato de
    uma mensagem construída pra manipular o modelo."""
    from motor_ia import orquestrador

    mentira = ResultadoClassificacao(
        intencao="CONSULTA_HABITUALIDADE",
        resumo="quer saber da habitualidade",
        cpf_mencionado="11111111111",  # o CPF da Ana no fixture
        precisa_humano=False,
    )
    monkeypatch.setattr(orquestrador, "classificar", lambda *a, **k: mentira)
    monkeypatch.setattr(
        orquestrador, "consultar",
        lambda *a, **k: pytest.fail("chegou a consultar -- o portão não segurou"),
    )

    resultado = orquestrador.atender_mensagem(
        "EMP-000001",
        "Quantos treinos eu tenho registrados?",  # sem CPF nenhum
        canal="Email",
        email="ana@example.com",
    )

    assert resultado["auditoria"].acao == "enviar"
    assert "CPF" in resultado["resposta"]
    assert resultado["dados"] == {}


# --------------------------------------------------------------------
# 3. "Não consegui consultar" nunca vira "não há registro"
# --------------------------------------------------------------------

def test_consultas_sem_implementacao_real_recusam_em_vez_de_simular(modo_real):
    """Com o modo real ligado, estas três ainda não sabem consultar de
    verdade. Devolver o simulado aqui faria o sistema responder a um
    atirador de verdade que ele não tem CR, nem arma, nem guia de
    tráfego -- porque o CPF dele não está na tabela de teste."""
    for consulta in (consultar_cr, consultar_armas, consultar_documentos_vencimento):
        with pytest.raises(ShootingHouseIndisponivel):
            consulta(CPF_DE_TESTE)


def test_sem_modo_real_o_simulado_continua_valendo():
    """Controle positivo: o desenvolvimento inteiro depende do simulado
    continuar funcionando enquanto a chave geral está desligada."""
    assert consultar_armas(CPF_DE_TESTE)
    assert consultar_cr(CPF_DE_TESTE)
    assert consultar_habitualidade(CPF_DE_TESTE)["simulado"] is True


def test_fonte_indisponivel_nao_deixa_chave_parecendo_resposta():
    resultado = {}

    def _falha():
        raise ShootingHouseIndisponivel("API fora do ar")

    _buscar_externo(resultado, "armas", "Armas registradas", _falha)

    # A chave NÃO existe -- "armas": [] seria uma afirmação ("consultei,
    # não tem nenhuma"), e ninguém consultou nada.
    assert "armas" not in resultado
    assert resultado["fontes_indisponiveis"][0]["fonte"] == "Armas registradas"


def test_auditor_freia_fonte_indisponivel_sem_chamar_a_openai(monkeypatch):
    """Mesmo espírito de test_auditor_freio.py: se este teste falhar com
    'OpenAI foi chamada', alguém moveu a checagem pra depois da IA."""
    monkeypatch.setattr(
        "motor_ia.auditor.OpenAI",
        lambda *a, **k: pytest.fail("OpenAI foi chamada -- o freio deixou de ser determinístico"),
    )

    resultado = auditar(
        EMPRESA_A,
        resposta="Você não possui nenhuma arma registrada, está tudo em dia!",
        dados={"fontes_indisponiveis": [
            {"fonte": "Armas registradas", "motivo": "API fora do ar"}
        ]},
        cliente_nome="Ana",
        plano=Plano(
            rota="consulta_habitualidade",
            fontes=["SHOOTING_HOUSE_ARMAS"],
            encaminhar_humano=False,
            motivo_humano=None,
        ),
    )

    assert resultado.acao == "encaminhar_humano"
    assert resultado.aprovado is False


# --------------------------------------------------------------------
# 3b. Número de série nunca chega ao prompt da OpenAI
# --------------------------------------------------------------------

SERIE = "ABA212416"


def test_numero_de_serie_nao_entra_no_bloco_de_dados():
    """O bloco é o texto que vai literalmente pro prompt do Redator e do
    Auditor. Nenhuma resposta legítima precisa recitar número de série --
    e o que o modelo nunca recebe, ele nunca repete numa resposta nem
    entrega a uma mensagem construída pra extraí-lo."""
    dados = {
        "cliente": {},
        "armas": [
            {"type": "Pistola", "brand": "Taurus", "model": "TH380",
             "caliber": "380 ACP", "serie": SERIE},
        ],
        "habitualidade": {"simulado": False, "habitualidades": {"ACLP": {
            "count": 1,
            "eventos": [{
                "data_participacao": "09/10/2025",
                # É assim que a API real manda: a série embutida no texto.
                "arma": f"({SERIE}) Pistola - TH380 CLUBE  - 380 ACP",
                "modalidade": "Treino",
            }],
        }}},
    }

    bloco = montar_bloco_dados(dados, "Ana", config={})

    assert SERIE not in bloco
    # O resto da descrição sobrevive -- sem ela a IA não sabe de qual
    # arma está falando quando o cliente tem mais de uma.
    assert "TH380" in bloco
    assert "380 ACP" in bloco


def test_serie_embutida_no_texto_da_arma_e_removida():
    """Mascarar um campo chamado "serie" não bastaria: a API manda
    arma_formatada como "(ABA212416) Pistola - ...", com a série dentro
    de um campo descritivo."""
    assert _arma_sem_serie(f"({SERIE}) Pistola - TH380  - 380 ACP") == "Pistola - TH380  - 380 ACP"
    assert _arma_sem_serie("Pistola sem série no texto") == "Pistola sem série no texto"
    assert _arma_sem_serie(None) == ""


# --------------------------------------------------------------------
# 4. CPF não vaza por mensagem de erro
# --------------------------------------------------------------------

def test_data_de_participacao_real_vem_com_hora_e_e_separada():
    """A API real manda "09/10/2025 16:30" no mesmo campo. Todo o resto
    do projeto trata data_participacao como só o dia -- portal/app.py faz
    strptime(..., "%d/%m/%Y") pra ordenar a lista, e com a hora colada
    isso levanta ValueError e derruba a tela de Habitualidade inteira, na
    primeira consulta real."""
    bruto = {
        "idatirador": 1, "atirador": "X", "cpf": CPF_DE_TESTE,
        "habitualidades": {"ACLP": {"91335": {
            "data_participacao": ["09/10/2025 16:30", "15/01/2026"],
            "modalidades_simples": ["Treino", "Treino"],
            "local": ["Associação XXX", "Associação XXX"],
            "arma_formatada": ["(ABA212416) Pistola", "(ABA212416) Pistola"],
            "competicao": ["TREINO", "TREINO"],
        }}},
    }

    eventos = _normalizar_habitualidade_real(bruto)["habitualidades"]["ACLP"]["eventos"]

    assert eventos[0]["data_participacao"] == "09/10/2025"
    assert eventos[0]["hora_participacao"] == "16:30"
    # Data sem hora continua funcionando (é o formato do simulado).
    assert eventos[1]["data_participacao"] == "15/01/2026"
    assert eventos[1]["hora_participacao"] is None
    # E o formato resultante é o que o Portal consegue ordenar.
    datetime.strptime(eventos[0]["data_participacao"], "%d/%m/%Y")


def test_lista_vazia_e_zero_participacoes_nao_e_falha(modo_real, monkeypatch):
    """A API devolve [] para quem não tem nenhuma participação. Isso é
    resposta legítima, e é o caso MAIS importante do panorama: é quem
    está atrasado.

    Tratar como falha invertia o princípio do projeto ao contrário --
    transformava "sei que não treinou" em "não sei", e a pessoa sumia da
    lista de quem precisa de atenção. Achado na primeira sincronização
    real: 3 das 25 pessoas consultadas eram assim."""
    monkeypatch.setattr(shooting_house, "_chamar_api", lambda caminho, params=None: [])

    resultado = consultar_habitualidade(CPF_DE_TESTE)

    assert resultado["simulado"] is False
    assert resultado["habitualidades"] == {}
    assert resultado["cpf"] == CPF_DE_TESTE


def test_formato_realmente_estranho_continua_sendo_falha(modo_real, monkeypatch):
    """Controle positivo: afrouxar a lista vazia não pode fazer o código
    engolir qualquer coisa. "Não sei" ainda precisa existir."""
    monkeypatch.setattr(shooting_house, "_chamar_api", lambda caminho, params=None: "vixe")

    with pytest.raises(ShootingHouseIndisponivel):
        consultar_habitualidade(CPF_DE_TESTE)


def test_mascara_de_cpf_esconde_o_suficiente():
    mascarado = _mascarar_cpf("123.456.789-00")

    assert CPF_DE_TESTE not in mascarado
    assert "123" not in mascarado
    assert mascarado == "***.***.789-**"


def test_falha_de_rede_nao_carrega_o_cpf_na_mensagem(modo_real, monkeypatch):
    """A URL da API tem o CPF no caminho, e a exceção crua do requests
    traz a URL inteira dentro. Sem isto, um fora-do-ar da API escreveria
    CPF de cliente real em três lugares que ninguém trata como sensível:
    atendimento/poller.log, a coluna log_ia.erro do banco, e o e-mail de
    alerta disparado por atendimento/alertas.py."""
    def _cai(*args, **kwargs):
        raise requests.ConnectionError(
            f"Failed to establish connection to "
            f"https://apibeta.shootinghouse.com.br/v1/partners/registers/"
            f"habitualities/{CPF_DE_TESTE}"
        )

    monkeypatch.setattr(shooting_house.requests, "get", _cai)

    with pytest.raises(ShootingHouseIndisponivel) as erro:
        consultar_habitualidade(CPF_DE_TESTE)

    texto_completo = repr(erro.value) + str(erro.value.__cause__ or "")
    assert CPF_DE_TESTE not in texto_completo
