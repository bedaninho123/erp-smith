"""Infraestrutura compartilhada da suíte de testes.

Regra número um deste arquivo: **nenhum teste toca o banco real.** A
variável ERP_CORE_DB é definida logo abaixo, ANTES de qualquer import do
projeto, porque core/conexao.py lê o caminho do banco uma única vez na
importação (ver o comentário lá). Se este bloco descer para depois dos
imports, a suíte inteira passa a rodar contra core/db/erp_smith.db.

O banco de teste é recriado do zero a cada teste a partir do schema real
(core/db/schema.sql + views.sql) -- nunca de uma cópia desatualizada do
schema escrita à mão aqui, que sairia de sincronia sem ninguém perceber.

MULTI-TENANT: o banco nasce com DUAS empresas, e os clientes estão
dispostos de propósito para cobrir os dois vazamentos possíveis, que são
problemas diferentes:

    EMP-000001  Ana (CLI-000001)  |  Bruno (CLI-000002)   <- mesma empresa
    EMP-000002  Carla (CLI-000003)                        <- outra empresa

Ana x Bruno testa isolamento ENTRE CLIENTES (o Portal já tinha isso).
Ana x Carla testa isolamento ENTRE EMPRESAS. Um código pode acertar um e
errar o outro -- filtrar por cliente_id e esquecer empresa_id passa nos
testes antigos e ainda assim vaza dado entre despachantes.
"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_PASTA_TEMP = Path(tempfile.mkdtemp(prefix="erp_smith_testes_"))

# --- precisa vir antes dos imports do projeto (ver docstring) ---
os.environ["ERP_CORE_DB"] = str(_PASTA_TEMP / "erp_smith_teste.db")
# O banco de DOMÍNIO ganhou o mesmo isolamento em 2026-08-27, quando o
# Dashboard passou a ler filiado/habitualidade numa rota do painel.
# Antes disso a suíte só não tocava o domínio real por sorte: nenhum
# teste chegava a executar corpo de rota que o lesse (o aviso no topo de
# tests/test_papeis.py registrava exatamente esse risco). Sorte não é
# isolamento -- e aqui o banco real tem 1.525 pessoas de verdade.
os.environ["ERP_DOMAIN_DB"] = str(_PASTA_TEMP / "dominio_teste.db")
# Evita que portal/app.py e webapp/app.py gerem uma chave nova e a
# gravem no .env de verdade durante os testes.
os.environ.setdefault("PORTAL_SECRET_KEY", "chave-de-teste-portal")
os.environ.setdefault("WEBAPP_SECRET_KEY", "chave-de-teste-webapp")

# --- A integração externa fica DESLIGADA na suíte, sempre ---
# Também antes dos imports: integracoes/config.py lê estas variáveis uma
# vez, na importação, e `load_dotenv()` não sobrescreve o que já está no
# ambiente -- então definir aqui vence o .env.
#
# Isto não é zelo teórico: no dia em que SHOOTING_HOUSE_ATIVO=Sim entrou
# no .env de verdade (2026-08-26), cinco testes quebraram de uma vez,
# porque a suíte passou a enxergar o modo real. O estrago maior seria o
# que NÃO quebrou: um teste chamando a API do fornecedor com a credencial
# de produção, consultando CPF de gente real como efeito colateral de
# rodar pytest.
os.environ["SHOOTING_HOUSE_ATIVO"] = ""
os.environ["SHOOTING_HOUSE_USER"] = ""
os.environ["SHOOTING_HOUSE_PASSWORD"] = ""

import pytest  # noqa: E402

from core.conexao import CORE_DB  # noqa: E402
from motor_ia.conexao import DOMAIN_DB  # noqa: E402

# --- todos os módulos precisam apontar para o MESMO banco de domínio ---
# Este arquivo é importado DUAS vezes numa execução de pytest: uma pelo
# próprio pytest (como conftest) e outra pelos testes que fazem
# `from tests.conftest import EMPRESA_A`. Cada carga roda mkdtemp() de
# novo e sobrescreve ERP_DOMAIN_DB -- então quem leu a variável na
# importação (motor_ia/conexao.py, motor_campeonatos.py e
# motor_resultados.py leem cada um por conta) podia acabar em pastas
# temporárias DIFERENTES, dependendo da ordem dos imports.
#
# O sintoma foi um teste que passava sozinho e falhava na suíte, com
# "no such table: campeonato": o fixture criava o schema num arquivo e a
# rota lia outro. Nenhum dos dois era o banco real, mas o próximo caso
# desse tipo pode ser -- então em vez de confiar na ordem, todo mundo é
# realinhado aqui com o valor que o motor_ia já capturou.
os.environ["ERP_DOMAIN_DB"] = DOMAIN_DB

from domain.clube_tiro import motor_campeonatos, motor_resultados  # noqa: E402

motor_campeonatos.DB_PATH = DOMAIN_DB
motor_resultados.DB_PATH = DOMAIN_DB

# Rede de segurança da regra número um deste arquivo. Se algum dia um
# import subir para antes do bloco de os.environ, isto estoura na coleta
# -- alto e cedo -- em vez de a suíte inteira rodar contra o banco de
# verdade em silêncio.
# A conferência é pelo PREFIXO da pasta descartável, e não por
# _PASTA_TEMP: como este arquivo é importado duas vezes (ver acima), a
# segunda carga tem uma pasta nova em mãos enquanto os módulos já
# capturaram a da primeira -- comparar com _PASTA_TEMP acusaria isso
# como erro sendo que os dois são temporários.
for _nome, _caminho in (("Core", CORE_DB), ("Domínio", DOMAIN_DB)):
    assert "erp_smith_testes_" in str(_caminho), (
        f"O banco de {_nome} da suíte aponta para {_caminho}, que não é uma "
        "pasta descartável. Algum import do projeto subiu para antes da "
        "definição das variáveis de ambiente no topo deste arquivo, e a suíte "
        "rodaria contra o banco de VERDADE."
    )

AGORA = "2026-07-28T12:00:00Z"

EMPRESA_A = "EMP-000001"
EMPRESA_B = "EMP-000002"

# Cada empresa tem o catálogo dela -- service_key repetida de propósito,
# pra que a UNIQUE composta (empresa_id, service_key) seja exercitada.
SERVICO_DA_EMPRESA = {EMPRESA_A: "SER-000001", EMPRESA_B: "SER-000002"}


def _criar_schema(con: sqlite3.Connection) -> None:
    con.executescript((BASE_DIR / "core" / "db" / "schema.sql").read_text(encoding="utf-8"))
    con.executescript((BASE_DIR / "core" / "db" / "views.sql").read_text(encoding="utf-8"))


def _apagar_banco(caminho: Path) -> None:
    """Apaga o arquivo do banco E os companheiros do modo WAL.

    O -wal não é detalhe: apagar só o .db e recriar deixa o journal
    antigo no disco, e o SQLite trata isso como jornal quente -- ele
    recupera o conteúdo velho por cima do banco novo, e o schema que o
    teste acabou de criar simplesmente some. O sintoma é lindo de
    enganoso: o teste passa sozinho e falha na suíte inteira, com
    "no such table" numa tabela que o script de schema claramente cria.
    """
    for sufixo in ("", "-wal", "-shm"):
        Path(str(caminho) + sufixo).unlink(missing_ok=True)


def _criar_dominio() -> None:
    """Banco de Domínio limpo, do schema REAL -- nunca de uma cópia
    escrita à mão aqui, que sairia de sincronia sem ninguém perceber
    (mesma regra do schema do Core, logo acima).

    Nasce VAZIO de propósito: nenhum filiado semeado. Assim o caminho
    "ninguém sincronizado ainda" -- que é o estado real de quase todo o
    clube hoje -- é o padrão que os testes percorrem, em vez de um caso
    de borda que ninguém lembra de escrever.
    """
    _apagar_banco(Path(DOMAIN_DB))
    con = sqlite3.connect(DOMAIN_DB)
    con.executescript(
        (BASE_DIR / "domain" / "clube_tiro" / "db" / "schema.sql").read_text(encoding="utf-8")
    )
    con.commit()
    con.close()


def _inserir_empresa(con: sqlite3.Connection, empresa_id: str, nome: str) -> None:
    con.execute(
        "INSERT INTO empresa (empresa_id, nome, dominio, ativo, criado_em) "
        "VALUES (?,?,?,?,?)",
        (empresa_id, nome, "clube_tiro", "Sim", AGORA),
    )


def _inserir_cliente(
    con: sqlite3.Connection, empresa_id: str, cliente_id: str, nome: str, cpf: str, email: str
) -> None:
    con.execute(
        "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, telefone, cidade, "
        "status, atendimento_ia, data_cadastro) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cliente_id, empresa_id, nome, cpf, email, "14999990000", "Marília", "Ativo",
         "Sim", AGORA),
    )


def _inserir_caso(
    con: sqlite3.Connection, empresa_id: str, caso_id: str, cliente_id: str, titulo: str
) -> None:
    con.execute(
        "INSERT INTO caso (caso_id, empresa_id, cliente_id, titulo, descricao, categoria, "
        "tipo_caso, origem, canal_origem, status, prioridade, criado_em, atualizado_em, "
        "criado_por, alterado_por, versao, ativo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (caso_id, empresa_id, cliente_id, titulo, "Caso de teste", "Transferência",
         "Solicitação", "Atendimento", "Email", "Aberto", "Normal", AGORA, AGORA,
         "testes", "testes", 1, "Sim"),
    )


def _inserir_processo(
    con: sqlite3.Connection, empresa_id: str, processo_id: str, caso_id: str, cliente_id: str
) -> None:
    con.execute(
        "INSERT INTO processo (processo_id, empresa_id, caso_id, cliente_id, servico_id, "
        "protocolo, status, data_abertura, ultima_atualizacao) VALUES (?,?,?,?,?,?,?,?,?)",
        (processo_id, empresa_id, caso_id, cliente_id, SERVICO_DA_EMPRESA[empresa_id],
         f"PROTO-{processo_id}", "Em andamento", AGORA, AGORA),
    )


def _inserir_documento(
    con: sqlite3.Connection, empresa_id: str, documento_id: str, cliente_id: str,
    caso_id: str, caminho: Path,
) -> None:
    con.execute(
        "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
        "tipo_documento, nome_arquivo, link_arquivo, status, data_envio) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (documento_id, empresa_id, cliente_id, caso_id, "RG", f"{documento_id}.pdf",
         str(caminho), "Recebido", AGORA),
    )


@pytest.fixture(autouse=True)
def _gmail_desligado_nos_testes(monkeypatch):
    """Nenhum teste manda e-mail de verdade, nunca.

    Não é hipotético: esta máquina tem token.json de verdade, e os
    testes do painel mudam status de caso -- o que dispara a notificação
    ao cliente. Hoje isso não sai porque o banco de teste nasce sem a
    linha de configuração que liga a notificação; ou seja, a única coisa
    separando a suíte de mandar e-mail para 'ana@example.com' é um
    detalhe do fixture. Isso é fino demais para depender dele.

    Mexer em TOKEN_PATH (e não em gmail_configurado) cobre todo mundo de
    uma vez: os módulos importam a função por referência, mas ela lê o
    caminho do próprio módulo na hora da chamada, e todo ponto de envio
    do projeto passa por gmail_configurado() antes.
    """
    from integracoes import gmail

    monkeypatch.setattr(gmail, "TOKEN_PATH", Path("nao-existe-nos-testes.json"))


@pytest.fixture(autouse=True)
def _shooting_house_nunca_sai_pela_rede(monkeypatch):
    """Nenhum teste chama a API do Shooting House de verdade, nunca.

    As variáveis já são zeradas antes dos imports (topo deste arquivo),
    o que basta em condições normais. Isto é o segundo cadeado, pelo
    mesmo motivo do fixture do Gmail: a única coisa separando a suíte de
    consultar o CPF de uma pessoa real na API de produção seria alguém
    lembrar. Um teste que tente sair pela rede falha aqui, alto, em vez
    de bater no fornecedor em silêncio.

    Teste que precisa exercitar o caminho real substitui `_chamar_api` ou
    `requests.get` por conta própria -- monkeypatch do teste vence este.
    """
    from integracoes import shooting_house

    def _nao_sai_pela_rede(*args, **kwargs):
        raise AssertionError(
            "Um teste tentou chamar a API do Shooting House de verdade. "
            "Substitua _chamar_api ou requests.get no próprio teste."
        )

    monkeypatch.setattr(shooting_house.requests, "get", _nao_sai_pela_rede)


@pytest.fixture(autouse=True)
def _pasta_de_documentos_isolada(tmp_path, monkeypatch):
    """Redireciona a pasta de anexos pro tmp do teste, sempre.

    autouse de propósito: descobrimos na prática que um teste de
    isolamento *falhando* (código quebrado deixando o upload passar)
    gravava arquivo de verdade em atendimento/documentos_recebidos/.
    Deixar isso na mão de cada teste lembrar não é garantia nenhuma.
    """
    from core import motor_documentos

    monkeypatch.setattr(motor_documentos, "PASTA_DOCUMENTOS", tmp_path / "documentos_recebidos")


@pytest.fixture
def banco(tmp_path):
    """Banco limpo com duas empresas e três clientes -- é essa separação
    que os testes de isolamento tentam furar.

    EMP-000001  Ana   CLI-000001 / CAS-000001 / PRO-000001 / DOC-000001
                Bruno CLI-000002 / CAS-000002 / PRO-000002 / DOC-000002
    EMP-000002  Carla CLI-000003 / CAS-000003 / PRO-000003 / DOC-000003

    Ana e Carla têm o MESMO CPF de propósito (11111111111): é a situação
    real que a UNIQUE composta passou a permitir -- a mesma pessoa sendo
    cliente de dois despachantes -- e é o que faz uma busca por CPF sem
    filtro de empresa devolver a pessoa errada.
    """
    _apagar_banco(Path(CORE_DB))
    _criar_dominio()

    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    _criar_schema(con)

    _inserir_empresa(con, EMPRESA_A, "Despachante A")
    _inserir_empresa(con, EMPRESA_B, "Despachante B")

    for empresa_id, service_id in SERVICO_DA_EMPRESA.items():
        con.execute(
            "INSERT INTO servico (service_id, empresa_id, service_key, nome_servico, "
            "categoria, documentos_obrigatorios, ativo) VALUES (?,?,?,?,?,?,?)",
            (service_id, empresa_id, "transferencia_arma", "Transferência de Arma",
             "Transferência", "RG, CPF, CR", "Sim"),
        )
    con.execute(
        "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, ativo, criado_em) "
        "VALUES (?,?,?,?,?,?,?)",
        ("USR-000001", EMPRESA_A, "Gestor Teste", "gestor@example.com",
         "Gestor", "Sim", AGORA),
    )
    con.execute(
        "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, ativo, criado_em) "
        "VALUES (?,?,?,?,?,?,?)",
        ("USR-000002", EMPRESA_B, "Atendente da Outra", "atendente@example.com",
         "Atendente", "Sim", AGORA),
    )
    con.execute(
        "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, ativo, criado_em) "
        "VALUES (?,?,?,?,?,?,?)",
        ("USR-000003", EMPRESA_A, "Atendente Teste", "atendente@example.com",
         "Atendente", "Sim", AGORA),
    )

    arquivo_a = tmp_path / "documento_do_cliente_a.pdf"
    arquivo_a.write_bytes(b"%PDF-1.4 conteudo secreto do cliente A")
    arquivo_b = tmp_path / "documento_do_cliente_b.pdf"
    arquivo_b.write_bytes(b"%PDF-1.4 conteudo secreto do cliente B")
    arquivo_c = tmp_path / "documento_da_outra_empresa.pdf"
    arquivo_c.write_bytes(b"%PDF-1.4 conteudo secreto da empresa B")

    _inserir_cliente(con, EMPRESA_A, "CLI-000001", "Ana Teste", "11111111111", "ana@example.com")
    _inserir_caso(con, EMPRESA_A, "CAS-000001", "CLI-000001", "Caso da Ana")
    _inserir_processo(con, EMPRESA_A, "PRO-000001", "CAS-000001", "CLI-000001")
    _inserir_documento(con, EMPRESA_A, "DOC-000001", "CLI-000001", "CAS-000001", arquivo_a)

    _inserir_cliente(con, EMPRESA_A, "CLI-000002", "Bruno Teste", "22222222222", "bruno@example.com")
    _inserir_caso(con, EMPRESA_A, "CAS-000002", "CLI-000002", "Caso do Bruno")
    _inserir_processo(con, EMPRESA_A, "PRO-000002", "CAS-000002", "CLI-000002")
    _inserir_documento(con, EMPRESA_A, "DOC-000002", "CLI-000002", "CAS-000002", arquivo_b)

    _inserir_cliente(con, EMPRESA_B, "CLI-000003", "Carla Outra", "11111111111", "carla@example.com")
    _inserir_caso(con, EMPRESA_B, "CAS-000003", "CLI-000003", "Caso da Carla")
    _inserir_processo(con, EMPRESA_B, "PRO-000003", "CAS-000003", "CLI-000003")
    _inserir_documento(con, EMPRESA_B, "DOC-000003", "CLI-000003", "CAS-000003", arquivo_c)

    con.commit()
    con.close()

    yield {"arquivo_a": arquivo_a, "arquivo_b": arquivo_b, "arquivo_c": arquivo_c}

    _apagar_banco(Path(CORE_DB))


@pytest.fixture
def portal(banco):
    """Cliente HTTP do Portal já logado como Ana (CLI-000001, EMP-000001).

    Logar direto na sessão (em vez de passar pelo link mágico) é
    proposital: o alvo destes testes é o isolamento das rotas, não o
    fluxo de login -- esse tem testes próprios em test_portal_auth.py.
    """
    from portal.app import app

    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    cliente_http = app.test_client()
    with cliente_http.session_transaction() as sessao:
        sessao["cliente_id"] = "CLI-000001"
        sessao["cliente_nome"] = "Ana Teste"
        sessao["empresa_id"] = EMPRESA_A
    return cliente_http


@pytest.fixture
def painel(banco):
    """Cliente HTTP do painel administrativo logado na EMPRESA_A, como
    Gestor (USR-000001) -- acesso total, é o papel usado por padrão em
    todo teste que não é sobre a restrição em si. Vale a mesma observação
    do fixture do Portal: a sessão é montada na mão porque o alvo aqui é
    o filtro por empresa nas rotas, não o formulário de login.
    """
    from webapp.app import app

    app.config.update(TESTING=True)
    cliente_http = app.test_client()
    with cliente_http.session_transaction() as sessao:
        sessao["usuario_id"] = "USR-000001"
        sessao["usuario_nome"] = "Gestor Teste"
        sessao["empresa_id"] = EMPRESA_A
        sessao["papel"] = "Gestor"
    return cliente_http


@pytest.fixture
def painel_atendente(banco):
    """Cliente HTTP do painel logado na EMPRESA_A como Atendente
    (USR-000003) -- usado só pelos testes de restrição por papel
    (tests/test_papeis.py)."""
    from webapp.app import app

    app.config.update(TESTING=True)
    cliente_http = app.test_client()
    with cliente_http.session_transaction() as sessao:
        sessao["usuario_id"] = "USR-000003"
        sessao["usuario_nome"] = "Atendente Teste"
        sessao["empresa_id"] = EMPRESA_A
        sessao["papel"] = "Atendente"
    return cliente_http


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_PASTA_TEMP, ignore_errors=True)
