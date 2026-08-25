"""Painel administrativo do ERP Smith: status do banco/módulos, testador
do pipeline do Motor IA, e fila de aprovações pendentes. Protegido por
login (usuario.senha_hash) -- ver webapp/definir_senha.py para cadastrar
a senha de um usuário antes do primeiro acesso.

MULTI-TENANT (docs/schema_multi_tenant.md §6): a empresa vem do usuário
que logou (`usuario.empresa_id` → `session["empresa_id"]`) e nunca da
requisição. Toda rota chama `empresa_atual()` e passa esse valor adiante.

Aqui as views do Core não protegem nada: este arquivo consulta tabela
crua o tempo todo, então cada `WHERE` precisa do filtro de empresa
escrito à mão. Os dois lugares em que esquecer doeria mais são
`/api/documentos/<id>/arquivo` (baixaria arquivo de outra empresa) e
`/api/clientes/buscar-cpf` (o mesmo CPF agora pode existir em duas
empresas, de propósito -- ver a UNIQUE composta em core/db/schema.sql).
"""
import os
import secrets
import sqlite3
import subprocess
import traceback
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash

from atendimento.processar import (
    aprovar_mensagem_pendente, entregar_resposta, rejeitar_mensagem_pendente,
)
from core import motor_checklist, motor_conversas, motor_documentos, motor_mensagens
from core.conexao import conectar
from core.configuracoes import atualizar_configuracao, obter_configuracoes
from core.limitador_tentativas import excedeu_limite
from core.motor_casos import STATUS_VALIDOS, atualizar_descricao, atualizar_responsavel, atualizar_status
from core.motor_notificacoes import destinatario_para_notificar
from core.motor_processos import atualizar_processo, criar_processo
from core.motor_usuarios import (
    FUNCOES_VALIDAS, atualizar_ativo, atualizar_papel, atualizar_permissoes,
    criar_usuario, listar_permissoes, listar_usuarios, tem_permissao,
)
from domain.clube_tiro.motor_campeonatos import (
    atualizar_campeonato, criar_campeonato, listar_campeonatos, remover_campeonato,
)
from domain.clube_tiro.motor_resultados import (
    atualizar_resultado, criar_resultado, listar_resultados, remover_resultado,
)
from integracoes.config import shooting_house_configurado
from integracoes.gmail import enviar_email, gmail_configurado
from integracoes.whatsapp import status_integracao as status_whatsapp
from motor_ia.atualizador_memoria import atualizar_memoria
from motor_ia.auditor import auditar
from motor_ia.classificador import classificar
from motor_ia.conexao import CORE_DB, DOMAIN_DB
from motor_ia.consultor import consultar
from motor_ia.identificador_cliente import identificar_cliente
from motor_ia.planejador import planejar
from motor_ia.redator import redigir

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

MODULOS_MOTOR_IA = [
    ("Identificador de Cliente", "motor_ia/identificador_cliente.py"),
    ("Classificador", "motor_ia/classificador.py"),
    ("Planejador", "motor_ia/planejador.py"),
    ("Consultor", "motor_ia/consultor.py"),
    ("Montador de Contexto", "motor_ia/montador_contexto.py"),
    ("Redator", "motor_ia/redator.py"),
    ("Auditor", "motor_ia/auditor.py"),
    ("Atualizador de Memória", "motor_ia/atualizador_memoria.py"),
]

load_dotenv(ENV_PATH)
if not os.getenv("WEBAPP_SECRET_KEY"):
    # Primeira vez rodando o painel -- gera a chave de sessão sozinho e
    # salva no .env, sem precisar que ninguém digite nada.
    _chave = secrets.token_hex(32)
    set_key(str(ENV_PATH), "WEBAPP_SECRET_KEY", _chave)
    os.environ["WEBAPP_SECRET_KEY"] = _chave

# Mesma variável de portal/app.py -- o link do e-mail de notificação de
# mudança de status aponta pro Portal do Cliente (porta própria, 5002).
PORTAL_URL_BASE = os.environ.get("PORTAL_URL_BASE", "http://127.0.0.1:5002")

# Limite de tentativas de login por IP -- dificulta força bruta de senha
# (core/limitador_tentativas.py). Por IP, não por e-mail: o risco real aqui
# é alguém tentando várias senhas contra a mesma máquina, não distribuído.
LOGIN_MAX_TENTATIVAS = 5
LOGIN_JANELA_SEGUNDOS = 300

app = Flask(__name__)
app.secret_key = os.environ["WEBAPP_SECRET_KEY"]
# Cookie de sessão só trafega em HTTPS quando COOKIE_HTTPS=Sim no .env --
# desligado por padrão porque hoje o painel roda em HTTP puro
# (127.0.0.1); ligar em True sem HTTPS de verdade na frente quebraria o
# login (o navegador simplesmente não manda o cookie de volta).
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_HTTPS", "").strip().lower() == "sim"
# Recarrega o template (.html) a cada requisição mesmo sem o modo debug
# do Flask ligado -- TEMPLATES_AUTO_RELOAD por padrão segue app.debug, e
# desligamos debug (ver comentário no app.run() no fim do arquivo) pelo
# risco do debugger interativo. Isso aqui é só cache de template, não
# reabre esse risco -- sem isso, editar index.html/login.html exige
# reiniciar o servidor pra fazer efeito.
app.config["TEMPLATES_AUTO_RELOAD"] = True


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Exige empresa_id junto do usuario_id: sessão antiga, criada
        # antes do multi-tenant, não tem a empresa e não pode continuar
        # valendo -- sem isso, empresa_atual() estouraria dentro da rota.
        if not (session.get("usuario_id") and session.get("empresa_id")):
            if request.path.startswith("/api/"):
                return jsonify(erro="Não autenticado."), 401
            return redirect(url_for("login", proximo=request.path))
        return f(*args, **kwargs)
    # Marcador lido por tests/test_controle_acesso_propagado.py -- não
    # tem efeito em runtime, só permite a suíte varrer app.url_map e
    # confirmar que toda rota /api/* tem os decorators certos, sem
    # precisar reimplementar a lógica de autorização no teste.
    wrapper._login_protegido = True
    return wrapper


def empresa_atual() -> str:
    """A empresa do usuário logado. Só é seguro chamar dentro de uma rota
    com @login_required -- é ele que garante que a chave existe."""
    return session["empresa_id"]


def gestor_required(f):
    """Some depois de @login_required -- ele já garante que existe sessão.
    Papéis e permissões de verdade (core/motor_usuarios.py): Gestor tem
    acesso total, Atendente opera casos/clientes/documentos sem acesso
    administrativo. Sessão antiga (de antes desta mudança) não tem
    'papel' -- session.get() trata isso como não-Gestor, não como erro."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("papel") != "Gestor":
            if request.path.startswith("/api/"):
                return jsonify(erro="Acesso restrito a Gestor."), 403
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    wrapper._controle_acesso = "gestor"  # ver marcador em login_required
    return wrapper


def funcao_required(*funcoes):
    """Some depois de @login_required, nunca junto de @gestor_required
    (são exclusivos: uma rota é administrativa OU operacional). Gestor
    passa sempre, sem consultar a tabela. Atendente passa se
    tem_permissao() disser sim para PELO MENOS UMA das funções passadas
    -- por padrão é True quando não há linha (core/motor_usuarios.py).

    Aceita mais de uma função porque uma rota pode ser pré-requisito de
    duas telas: GET /api/campeonatos é a lista de campeonatos da tela
    Campeonatos, mas também o seletor de campeonato dentro da tela
    Resultados -- travar só em "campeonatos" quebrava Resultados pra
    quem tem só essa função ligada (achado testando como a Ana)."""
    # Falha na hora de SUBIR o app, não só num teste -- um typo aqui
    # (ex.: "caso" em vez de "casos") faria tem_permissao() nunca achar
    # linha nenhuma pra essa chave e devolver sempre True (permitido),
    # liberando a rota pra qualquer Atendente em silêncio. Ver também
    # tests/test_controle_acesso_propagado.py, que confere isso de novo
    # sem precisar registrar cada rota manualmente.
    for funcao in funcoes:
        assert funcao in FUNCOES_VALIDAS, (
            f"funcao_required: '{funcao}' não existe em "
            f"core.motor_usuarios.FUNCOES_VALIDAS -- typo?"
        )

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("papel") != "Gestor":
                empresa_id, usuario_id = empresa_atual(), session.get("usuario_id")
                if not any(tem_permissao(empresa_id, usuario_id, funcao) for funcao in funcoes):
                    if request.path.startswith("/api/"):
                        return jsonify(erro="Você não tem permissão para esta função."), 403
                    return redirect(url_for("index"))
            return f(*args, **kwargs)
        wrapper._controle_acesso = ("funcao", funcoes)  # ver login_required
        return wrapper
    return decorator


def _notificar_cliente_mudanca_status(empresa_id: str, caso_id: str) -> None:
    """E-mail genérico (nunca revela o novo status no corpo -- domínio
    regulado de arma de fogo) avisando o cliente que algo mudou no
    atendimento dele, com link pro Portal. Silencioso quando a
    notificação está desligada, o cliente não tem e-mail cadastrado, ou
    o Gmail ainda não foi autorizado nesta máquina -- nenhum desses
    casos deve impedir a mudança de status em si de ter acontecido."""
    destinatario = destinatario_para_notificar(empresa_id, caso_id)
    if not destinatario or not gmail_configurado():
        return
    # O nome da empresa sai das configurações dela, não de um literal:
    # com mais de um despachante no sistema, um "Smith Clube de Tiro"
    # fixo aqui assinaria e-mail no nome da empresa errada.
    config = obter_configuracoes(empresa_id)
    nome_empresa = config.get("nome_empresa", "nosso escritório")
    enviar_email(
        destinatario=destinatario["email"],
        assunto=f"Atualização no seu atendimento -- {nome_empresa}",
        corpo=(
            f"Olá {destinatario['nome']},\n\n"
            "Houve uma atualização no seu atendimento. Acesse o Portal do "
            "Cliente para ver os detalhes:\n\n"
            f"{PORTAL_URL_BASE}\n\n"
            f"{config.get('assinatura_email', f'Equipe {nome_empresa}')}"
        ),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        if excedeu_limite(f"login_webapp:{request.remote_addr}", LOGIN_MAX_TENTATIVAS, LOGIN_JANELA_SEGUNDOS):
            return render_template(
                "login.html",
                erro="Muitas tentativas de login. Aguarde alguns minutos e tente novamente.",
            )
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        # Única consulta do painel sem filtro de empresa, e não tem como
        # ser diferente: é justamente o login que descobre de que empresa
        # a pessoa é. O e-mail agora só é único DENTRO de uma empresa
        # (UNIQUE(empresa_id, email)), então o mesmo endereço pode
        # aparecer em duas -- por isso a empresa vem da linha encontrada,
        # nunca de algo digitado na tela.
        con = sqlite3.connect(CORE_DB)
        con.row_factory = sqlite3.Row
        linha = con.execute(
            "SELECT u.usuario_id, u.nome, u.senha_hash, u.empresa_id, u.papel FROM usuario u "
            "JOIN empresa e ON e.empresa_id = u.empresa_id "
            "WHERE lower(u.email) = ? AND u.ativo = 'Sim' AND e.ativo = 'Sim'",
            (email,),
        ).fetchone()
        con.close()
        if linha and linha["senha_hash"] and check_password_hash(linha["senha_hash"], senha):
            session["usuario_id"] = linha["usuario_id"]
            session["usuario_nome"] = linha["nome"]
            session["empresa_id"] = linha["empresa_id"]
            session["papel"] = linha["papel"]
            return redirect(request.args.get("proximo") or url_for("index"))
        erro = "E-mail ou senha incorretos."
    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    # Funções ativas do usuário logado, só pra decidir o que o menu
    # mostra -- a trava de verdade é o decorator funcao_required, que
    # consulta o banco de novo a cada rota (a sessão não é fonte de
    # verdade de permissão, só de identidade).
    if session.get("papel") == "Gestor":
        funcoes_ativas = list(FUNCOES_VALIDAS)
    elif session.get("usuario_id"):
        funcoes_ativas = [
            p["funcao"] for p in listar_permissoes(session["empresa_id"], session["usuario_id"])
            if p["ativo"] == "Sim"
        ]
    else:
        funcoes_ativas = []
    return render_template(
        "index.html",
        usuario_nome=session.get("usuario_nome"),
        usuario_id=session.get("usuario_id"),
        usuario_papel=session.get("papel"),
        funcoes_ativas=funcoes_ativas,
    )


@app.route("/api/status")
@login_required
@funcao_required("status_projeto")
def status():
    empresa_id = empresa_atual()

    # Contagem por empresa, não do banco inteiro: o número de linhas de
    # outra empresa não é informação desta aqui -- e o painel existe pra
    # mostrar "quanto dado EU tenho". Tabela sem empresa_id (empresa, e
    # conhecimento no Domínio) conta tudo mesmo, porque aí o total é
    # compartilhado de propósito.
    def _contar(con, tabela: str) -> int:
        colunas = [c[1] for c in con.execute(f"PRAGMA table_info({tabela})")]
        if "empresa_id" in colunas:
            return con.execute(
                f"SELECT COUNT(*) FROM {tabela} WHERE empresa_id = ?", (empresa_id,)
            ).fetchone()[0]
        return con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]

    con = sqlite3.connect(CORE_DB)
    tabelas_core = [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    tabelas = []
    for nome in tabelas_core:
        tabelas.append({"nome": nome, "linhas": _contar(con, nome), "camada": "Core"})
    con.close()

    con_dom = sqlite3.connect(DOMAIN_DB)
    tabelas_dom = [
        r[0] for r in con_dom.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    for nome in tabelas_dom:
        tabelas.append({"nome": nome, "linhas": _contar(con_dom, nome), "camada": "Domínio"})
    con_dom.close()

    log = subprocess.run(
        ["git", "log", "--pretty=format:%h|%ad|%s", "--date=format:%Y-%m-%d %H:%M"],
        cwd=BASE_DIR, capture_output=True, text=True, check=True,
    ).stdout.strip()
    commits = []
    if log:
        for linha in log.split("\n"):
            hash_, data, mensagem = linha.split("|", 2)
            commits.append({"hash": hash_, "data": data, "mensagem": mensagem})

    modulos = [
        {"nome": nome, "existe": (BASE_DIR / caminho).exists()}
        for nome, caminho in MODULOS_MOTOR_IA
    ]

    integracoes = [
        {"nome": "Shooting House (habitualidade)", "configurado": shooting_house_configurado()},
    ]

    # Consumo de IA por empresa -- é este número que vira base de
    # cobrança de assinatura um dia (docs/schema_multi_tenant.md §3), então
    # misturar empresa aqui seria errado de duas formas ao mesmo tempo.
    con_log = conectar(empresa_id)
    por_modulo = [
        dict(r) for r in con_log.execute(
            "SELECT prompt_key, COUNT(*) AS chamadas, "
            "SUM(tokens_entrada) AS tokens_entrada, SUM(tokens_saida) AS tokens_saida, "
            "SUM(CASE WHEN resultado = 'Erro' THEN 1 ELSE 0 END) AS erros "
            "FROM log_ia WHERE empresa_id = ? GROUP BY prompt_key ORDER BY prompt_key",
            (empresa_id,),
        ).fetchall()
    ]
    totais = con_log.execute(
        "SELECT COUNT(*) AS chamadas, SUM(tokens_entrada) AS tokens_entrada, "
        "SUM(tokens_saida) AS tokens_saida FROM log_ia WHERE empresa_id = ?",
        (empresa_id,),
    ).fetchone()
    con_log.close()
    log_ia_resumo = {
        "total_chamadas": totais["chamadas"] or 0,
        "total_tokens_entrada": totais["tokens_entrada"] or 0,
        "total_tokens_saida": totais["tokens_saida"] or 0,
        "por_modulo": por_modulo,
    }

    return jsonify(
        tabelas=tabelas, commits=commits, modulos=modulos, integracoes=integracoes,
        log_ia=log_ia_resumo,
    )


@app.route("/api/casos")
@login_required
@funcao_required("casos")
def casos():
    empresa_id = empresa_atual()
    status = request.args.get("status") or None
    categoria = request.args.get("categoria") or None

    con = conectar(empresa_id)
    query = (
        "SELECT c.caso_id, c.titulo, c.categoria, c.status, c.prioridade, "
        "c.atualizado_em, c.criado_em, cl.cliente_id, cl.nome AS cliente_nome, "
        "u.nome AS responsavel_nome "
        "FROM caso c "
        "JOIN cliente cl ON cl.cliente_id = c.cliente_id "
        "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.ativo = 'Sim' AND c.empresa_id = ?"
    )
    params = [empresa_id]
    if status:
        query += " AND c.status = ?"
        params.append(status)
    if categoria:
        query += " AND c.categoria = ?"
        params.append(categoria)
    query += " ORDER BY c.atualizado_em DESC"

    casos = [dict(r) for r in con.execute(query, params).fetchall()]
    # Os filtros da tela também são por empresa: uma categoria que só
    # existe na empresa vizinha não deve nem aparecer na lista suspensa.
    status_disponiveis = [
        r[0] for r in con.execute(
            "SELECT DISTINCT status FROM caso WHERE ativo = 'Sim' AND empresa_id = ? "
            "ORDER BY status", (empresa_id,),
        ).fetchall()
    ]
    categorias_disponiveis = [
        r[0] for r in con.execute(
            "SELECT DISTINCT categoria FROM caso WHERE ativo = 'Sim' AND empresa_id = ? "
            "ORDER BY categoria", (empresa_id,),
        ).fetchall()
    ]
    con.close()

    return jsonify(
        casos=casos, status_disponiveis=status_disponiveis,
        categorias_disponiveis=categorias_disponiveis,
    )


@app.route("/api/casos/<caso_id>")
@login_required
@funcao_required("casos")
def caso_detalhe(caso_id):
    empresa_id = empresa_atual()
    con = conectar(empresa_id)

    # O filtro por empresa aqui já decide tudo: caso de outra empresa dá
    # 404 e a rota nem chega nas consultas de baixo. Mesmo assim elas
    # repetem o filtro -- é a mesma escolha do schema (§3 do doc), custa
    # uma linha e tira a dependência de a checagem de cima estar certa.
    caso = con.execute(
        "SELECT c.*, cl.nome AS cliente_nome, cl.cpf AS cliente_cpf, "
        "cl.email AS cliente_email, cl.telefone AS cliente_telefone, "
        "u.nome AS responsavel_nome "
        "FROM caso c "
        "JOIN cliente cl ON cl.cliente_id = c.cliente_id "
        "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.caso_id = ? AND c.empresa_id = ?",
        (caso_id, empresa_id),
    ).fetchone()
    if not caso:
        con.close()
        return jsonify(erro=f"Caso não encontrado: {caso_id}"), 404

    processos = con.execute(
        "SELECT p.*, s.nome_servico FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id "
        "WHERE p.caso_id = ? AND p.empresa_id = ? ORDER BY p.data_abertura",
        (caso_id, empresa_id),
    ).fetchall()
    processos_list = []
    for r in processos:
        p = dict(r)
        p["checklist"] = motor_checklist.status_checklist(con, empresa_id, p["processo_id"])
        processos_list.append(p)

    documentos = con.execute(
        "SELECT * FROM documento WHERE empresa_id = ? AND (caso_id = ? "
        "OR processo_id IN (SELECT processo_id FROM processo WHERE caso_id = ?)) "
        "ORDER BY data_envio",
        (empresa_id, caso_id, caso_id),
    ).fetchall()

    historico = con.execute(
        "SELECT * FROM historico WHERE caso_id = ? AND empresa_id = ? ORDER BY criado_em",
        (caso_id, empresa_id),
    ).fetchall()

    mensagens = con.execute(
        "SELECT * FROM mensagem WHERE caso_id = ? AND empresa_id = ? ORDER BY data_hora",
        (caso_id, empresa_id),
    ).fetchall()

    usuarios = con.execute(
        "SELECT usuario_id, nome FROM usuario WHERE ativo = 'Sim' AND empresa_id = ? "
        "ORDER BY nome", (empresa_id,),
    ).fetchall()

    servicos = con.execute(
        "SELECT service_id, nome_servico FROM servico WHERE ativo = 'Sim' "
        "AND empresa_id = ? ORDER BY nome_servico", (empresa_id,),
    ).fetchall()

    con.close()
    return jsonify(
        caso=dict(caso),
        processos=processos_list,
        documentos=[dict(r) for r in documentos],
        historico=[dict(r) for r in historico],
        mensagens=[dict(r) for r in mensagens],
        status_validos=sorted(STATUS_VALIDOS),
        usuarios=[dict(r) for r in usuarios],
        servicos=[dict(r) for r in servicos],
    )


@app.route("/api/casos/<caso_id>/status", methods=["POST"])
@login_required
@funcao_required("casos")
def caso_atualizar_status(caso_id):
    corpo = request.get_json(force=True)
    novo_status = (corpo.get("status") or "").strip()
    motivo = (corpo.get("motivo") or "").strip() or None
    if not novo_status:
        return jsonify(erro="Informe o novo status."), 400
    empresa_id = empresa_atual()
    try:
        status_antigo = atualizar_status(
            empresa_id, caso_id, novo_status, motivo=motivo,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    if status_antigo != novo_status:
        _notificar_cliente_mudanca_status(empresa_id, caso_id)
    return jsonify(ok=True)


@app.route("/api/casos/<caso_id>/responsavel", methods=["POST"])
@login_required
@funcao_required("casos")
def caso_atualizar_responsavel(caso_id):
    corpo = request.get_json(force=True)
    novo_responsavel_id = (corpo.get("responsavel_id") or "").strip() or None
    try:
        atualizar_responsavel(
            empresa_atual(), caso_id, novo_responsavel_id,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/casos/<caso_id>/descricao", methods=["POST"])
@login_required
@funcao_required("casos")
def caso_atualizar_descricao(caso_id):
    corpo = request.get_json(force=True)
    nova_descricao = (corpo.get("descricao") or "").strip()
    try:
        atualizar_descricao(
            empresa_atual(), caso_id, nova_descricao,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/casos/<caso_id>/processos", methods=["POST"])
@login_required
@funcao_required("casos")
def processo_criar(caso_id):
    corpo = request.get_json(force=True)
    servico_id = (corpo.get("servico_id") or "").strip()
    if not servico_id:
        return jsonify(erro="Selecione um serviço."), 400

    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    caso = con.execute(
        "SELECT cliente_id FROM caso WHERE caso_id = ? AND empresa_id = ?",
        (caso_id, empresa_id),
    ).fetchone()
    con.close()
    if not caso:
        return jsonify(erro=f"Caso não encontrado: {caso_id}"), 404

    try:
        novo_id = criar_processo(
            empresa_id, caso_id, caso["cliente_id"], servico_id,
            protocolo=(corpo.get("protocolo") or "").strip() or None,
            status=(corpo.get("status") or "Aberto").strip(),
            prazo_estimado=(corpo.get("prazo_estimado") or "").strip() or None,
            proxima_acao=(corpo.get("proxima_acao") or "").strip() or None,
            responsavel_id=(corpo.get("responsavel_id") or "").strip() or None,
            observacoes=(corpo.get("observacoes") or "").strip() or None,
            criado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, processo_id=novo_id)


@app.route("/api/processos/<processo_id>", methods=["POST"])
@login_required
@funcao_required("casos")
def processo_atualizar(processo_id):
    corpo = request.get_json(force=True)
    novo_status = (corpo.get("status") or "").strip()
    if not novo_status:
        return jsonify(erro="Informe o status."), 400
    empresa_id = empresa_atual()
    try:
        status_antigo, caso_id = atualizar_processo(
            empresa_id,
            processo_id,
            status=novo_status,
            protocolo=(corpo.get("protocolo") or "").strip() or None,
            prazo_estimado=(corpo.get("prazo_estimado") or "").strip() or None,
            proxima_acao=(corpo.get("proxima_acao") or "").strip() or None,
            responsavel_id=(corpo.get("responsavel_id") or "").strip() or None,
            observacoes=(corpo.get("observacoes") or "").strip() or None,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    if status_antigo != novo_status:
        _notificar_cliente_mudanca_status(empresa_id, caso_id)
    return jsonify(ok=True)


@app.route("/api/processos/<processo_id>/checklist", methods=["POST"])
@login_required
@funcao_required("casos")
def checklist_marcar(processo_id):
    corpo = request.get_json(force=True)
    documento_exigido_id = (corpo.get("documento_exigido_id") or "").strip()
    documento_id = (corpo.get("documento_id") or "").strip()
    if not documento_exigido_id or not documento_id:
        return jsonify(erro="Informe o item do checklist e o documento."), 400
    try:
        novo_id = motor_checklist.marcar_documento(
            empresa_atual(), processo_id, documento_exigido_id, documento_id,
            marcado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_checklist_id=novo_id)


def _notificar_documento_recusado(empresa_id: str, caso_id: str, item: str) -> None:
    """Aviso de recusa. Diferente da notificação de mudança de status,
    este e-mail diz **qual** documento precisa ser reenviado -- sem isso
    o cliente teria que adivinhar o que corrigir. O motivo em si não vai
    no corpo: pode conter observação interna da equipe, e o lugar de ler
    isso é o Portal, atrás de login (domínio regulado)."""
    destinatario = destinatario_para_notificar(empresa_id, caso_id)
    if not destinatario or not gmail_configurado():
        return
    config = obter_configuracoes(empresa_id)
    nome_empresa = config.get("nome_empresa", "nosso escritório")
    enviar_email(
        destinatario=destinatario["email"],
        assunto=f"Documento precisa ser reenviado -- {nome_empresa}",
        corpo=(
            f"Olá {destinatario['nome']},\n\n"
            f"O documento enviado para \"{item}\" não pôde ser aceito. "
            "Acesse o Portal do Cliente para ver o motivo e enviar outro "
            "arquivo:\n\n"
            f"{PORTAL_URL_BASE}\n\n"
            f"{config.get('assinatura_email', f'Equipe {nome_empresa}')}"
        ),
    )


@app.route("/api/documentos-pendentes")
@login_required
@funcao_required("documentos_aprovar")
def documentos_pendentes():
    """Fila de documentos que clientes enviaram pelo Portal e ninguém
    conferiu ainda."""
    return jsonify(motor_checklist.listar_pendentes(empresa_atual()))


@app.route("/api/checklist/<documento_checklist_id>/aprovar", methods=["POST"])
@login_required
@funcao_required("documentos_aprovar")
def checklist_aprovar(documento_checklist_id):
    try:
        motor_checklist.aprovar(
            empresa_atual(), documento_checklist_id,
            revisado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    # Aprovação não gera e-mail de propósito (decisão de 2026-07-29): num
    # processo de 10 documentos seriam 10 avisos. O cliente vê no Portal.
    return jsonify(ok=True)


@app.route("/api/checklist/<documento_checklist_id>/recusar", methods=["POST"])
@login_required
@funcao_required("documentos_aprovar")
def checklist_recusar(documento_checklist_id):
    corpo = request.get_json(force=True)
    motivo = (corpo.get("motivo") or "").strip()
    try:
        pendencia = motor_checklist.recusar(
            empresa_atual(), documento_checklist_id, motivo,
            revisado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400

    # Recusa exige ação do cliente, então avisa -- mas o e-mail não pode
    # desfazer a recusa se falhar: ela já está gravada.
    try:
        _notificar_documento_recusado(
            empresa_atual(), pendencia["caso_id"], pendencia["item"]
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=True, aviso=f"Recusado, mas o e-mail falhou: {e}")
    return jsonify(ok=True)


@app.route("/api/checklist/<documento_checklist_id>/remover", methods=["POST"])
@login_required
@gestor_required
def checklist_desmarcar(documento_checklist_id):
    try:
        motor_checklist.desmarcar(empresa_atual(), documento_checklist_id)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


# Mesmo allowlist/limite de integracoes/gmail.py -- duplicado de propósito
# (mesmo padrão do projeto de não compartilhar infra entre "canais"
# diferentes: e-mail vs. upload manual pelo painel são fontes distintas
# do mesmo tipo de documento).
DOCUMENTO_EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
DOCUMENTO_TAMANHO_MAXIMO = 15 * 1024 * 1024  # 15 MB


@app.route("/api/casos/<caso_id>/documentos", methods=["POST"])
@login_required
@funcao_required("casos")
def documento_upload(caso_id):
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(erro="Selecione um arquivo."), 400

    extensao = Path(arquivo.filename).suffix.lower()
    if extensao not in DOCUMENTO_EXTENSOES_ACEITAS:
        return jsonify(erro=f"Tipo de arquivo não aceito: {extensao or '(sem extensão)'}. Use PDF ou foto."), 400

    conteudo = arquivo.read()
    if not conteudo:
        return jsonify(erro="Arquivo vazio."), 400
    if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
        return jsonify(erro="Arquivo maior que 15MB."), 400

    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    caso = con.execute(
        "SELECT cliente_id FROM caso WHERE caso_id = ? AND empresa_id = ?",
        (caso_id, empresa_id),
    ).fetchone()
    con.close()
    if not caso:
        return jsonify(erro=f"Caso não encontrado: {caso_id}"), 404

    processo_id = (request.form.get("processo_id") or "").strip() or None
    tipo_documento = (request.form.get("tipo_documento") or "").strip() or "Anexo enviado pelo painel"
    observacoes = (request.form.get("observacoes") or "").strip() or None

    try:
        documento_id = motor_documentos.salvar_documento(
            empresa_id, caso["cliente_id"], conteudo, arquivo.filename,
            caso_id=caso_id, processo_id=processo_id,
            tipo_documento=tipo_documento, observacoes=observacoes,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_id=documento_id)


@app.route("/api/documentos/<documento_id>/arquivo")
@login_required
def documento_arquivo(documento_id):
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    # Rota de download: sem o filtro por empresa, bastaria adivinhar um
    # DOC-000123 pra baixar documento de arma de fogo de cliente de outro
    # despachante. É o mesmo cuidado que o Portal já toma por cliente.
    doc = con.execute(
        "SELECT nome_arquivo, link_arquivo FROM documento "
        "WHERE documento_id = ? AND empresa_id = ?",
        (documento_id, empresa_id),
    ).fetchone()
    con.close()

    if not doc or not doc["link_arquivo"]:
        return jsonify(erro="Documento não encontrado."), 404

    # O caminho vem do nosso próprio banco (gravado por
    # core/motor_documentos.py), nunca de algo que o cliente da requisição
    # controla -- não há risco de path traversal aqui.
    caminho = Path(doc["link_arquivo"])
    if not caminho.is_file():
        return jsonify(erro="Arquivo não encontrado no disco."), 404

    # nome_arquivo é o nome original que o remetente usou (guardado só
    # pra exibição) -- pode conter "../" ou coisa parecida; Path(...).name
    # descarta qualquer componente de diretório antes de virar o nome de
    # download sugerido ao navegador.
    nome_sugerido = Path(doc["nome_arquivo"] or "").name or caminho.name
    # ?inline=1 -- usado pra mostrar a foto direto no painel (ex.: prévia
    # em Aprovações Pendentes) em vez de forçar download.
    inline = request.args.get("inline") == "1"
    return send_file(caminho, as_attachment=not inline, download_name=nome_sugerido)


@app.route("/api/clientes")
@login_required
@funcao_required("clientes")
def clientes():
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    linhas = con.execute(
        "SELECT cliente_id, nome FROM cliente WHERE empresa_id = ? ORDER BY nome",
        (empresa_id,),
    ).fetchall()
    con.close()
    return jsonify([{"cliente_id": r[0], "nome": r[1]} for r in linhas])


@app.route("/api/clientes/lista")
@login_required
@funcao_required("clientes")
def clientes_lista():
    empresa_id = empresa_atual()
    busca = (request.args.get("busca") or "").strip()

    con = conectar(empresa_id)
    query = (
        "SELECT cl.cliente_id, cl.nome, cl.cpf, cl.email, cl.telefone, cl.cidade, "
        "cl.status, cl.data_cadastro, cl.ultima_interacao, "
        "(SELECT COUNT(*) FROM caso c WHERE c.cliente_id = cl.cliente_id "
        " AND c.ativo = 'Sim' AND c.status NOT IN ('Encerrado', 'Cancelado')) AS casos_abertos "
        "FROM cliente cl WHERE cl.empresa_id = ?"
    )
    params = [empresa_id]
    if busca:
        # Parênteses obrigatórios: sem eles o OR da busca se espalharia
        # por cima do filtro de empresa e a busca por nome passaria a
        # varrer o banco inteiro.
        query += " AND (cl.nome LIKE ? OR cl.cpf LIKE ? OR cl.email LIKE ?)"
        curinga = f"%{busca}%"
        params += [curinga, curinga, curinga]
    query += " ORDER BY cl.nome"

    clientes = [dict(r) for r in con.execute(query, params).fetchall()]
    con.close()
    return jsonify(clientes=clientes)


@app.route("/api/clientes/<cliente_id>")
@login_required
@funcao_required("clientes")
def cliente_detalhe(cliente_id):
    empresa_id = empresa_atual()
    con = conectar(empresa_id)

    cliente = con.execute(
        "SELECT * FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()
    if not cliente:
        con.close()
        return jsonify(erro=f"Cliente não encontrado: {cliente_id}"), 404

    casos = con.execute(
        "SELECT c.caso_id, c.titulo, c.categoria, c.status, c.prioridade, "
        "c.atualizado_em, u.nome AS responsavel_nome "
        "FROM caso c LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.cliente_id = ? AND c.empresa_id = ? AND c.ativo = 'Sim' "
        "ORDER BY c.atualizado_em DESC",
        (cliente_id, empresa_id),
    ).fetchall()

    # Todos os arquivos deste cliente, de qualquer canal (e-mail, upload
    # do painel, Portal) e de qualquer caso -- é o "arquivo morto" dele.
    # O LEFT JOIN traz o estado de conferência quando o documento foi
    # ligado a um item de checklist; documento solto (anexo de e-mail que
    # ninguém classificou) aparece com esses campos em NULL, e é isso que
    # deixa visível o que está largado sem uso.
    documentos = con.execute(
        "SELECT d.documento_id, d.tipo_documento, d.nome_arquivo, d.status, "
        "       d.data_envio, d.caso_id, d.link_arquivo, "
        "       dck.status AS status_conferencia, dex.item AS item_checklist "
        "FROM documento d "
        "LEFT JOIN documento_checklist dck ON dck.documento_id = d.documento_id "
        "     AND dck.empresa_id = d.empresa_id "
        "LEFT JOIN documento_exigido dex ON dex.documento_exigido_id = dck.documento_exigido_id "
        "     AND dex.empresa_id = d.empresa_id "
        "WHERE d.cliente_id = ? AND d.empresa_id = ? "
        "ORDER BY d.data_envio DESC",
        (cliente_id, empresa_id),
    ).fetchall()

    con.close()

    # `tem_arquivo` evita oferecer "baixar" pra linha que só tem metadado:
    # os documentos migrados da planilha antiga têm link_arquivo apontando
    # pra um example.com que nunca existiu. Clicar num botão que sempre dá
    # erro é pior do que não ter o botão.
    lista_documentos = []
    for linha in documentos:
        doc = dict(linha)
        caminho = doc.pop("link_arquivo", None)
        doc["tem_arquivo"] = bool(caminho) and Path(caminho).is_file()
        lista_documentos.append(doc)

    return jsonify(
        cliente=dict(cliente),
        casos=[dict(r) for r in casos],
        documentos=lista_documentos,
    )


@app.route("/api/configuracoes")
@login_required
@gestor_required
def configuracoes_lista():
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    linhas = con.execute(
        "SELECT * FROM configuracoes WHERE empresa_id = ? ORDER BY categoria, chave",
        (empresa_id,),
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in linhas])


@app.route("/api/configuracoes/<config_id>", methods=["POST"])
@login_required
@gestor_required
def configuracoes_atualizar(config_id):
    corpo = request.get_json(force=True)
    try:
        atualizar_configuracao(
            empresa_atual(), config_id, corpo.get("valor"), corpo.get("ativo"),
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/usuarios")
@login_required
@gestor_required
def usuarios_lista():
    return jsonify(listar_usuarios(empresa_atual()))


@app.route("/api/usuarios", methods=["POST"])
@login_required
@gestor_required
def usuarios_criar():
    corpo = request.get_json(force=True)
    try:
        usuario = criar_usuario(
            empresa_atual(), corpo.get("nome"), corpo.get("email"), corpo.get("papel"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(usuario), 201


@app.route("/api/usuarios/<usuario_id>", methods=["POST"])
@login_required
@gestor_required
def usuarios_atualizar(usuario_id):
    # Gestor não pode mexer no próprio acesso -- senão a empresa fica sem
    # ninguém que consiga reverter um engano (rebaixar ou desativar a si
    # mesmo por acidente e trancar a própria saída da tela de Usuários).
    if usuario_id == session.get("usuario_id"):
        return jsonify(erro="Você não pode alterar seu próprio acesso."), 400

    corpo = request.get_json(force=True)
    empresa_id = empresa_atual()
    alterado_por = session.get("usuario_nome", "Painel administrativo")
    try:
        if "papel" in corpo:
            atualizar_papel(empresa_id, usuario_id, corpo["papel"], alterado_por=alterado_por)
        if "ativo" in corpo:
            atualizar_ativo(empresa_id, usuario_id, corpo["ativo"], alterado_por=alterado_por)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/usuarios/<usuario_id>/permissoes")
@login_required
@gestor_required
def usuarios_permissoes_lista(usuario_id):
    return jsonify(listar_permissoes(empresa_atual(), usuario_id))


@app.route("/api/usuarios/<usuario_id>/permissoes", methods=["POST"])
@login_required
@gestor_required
def usuarios_permissoes_atualizar(usuario_id):
    corpo = request.get_json(force=True)
    try:
        atualizar_permissoes(
            empresa_atual(), usuario_id, corpo,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/campeonatos")
@login_required
@funcao_required("campeonatos", "resultados")
def campeonatos_lista():
    ano = request.args.get("ano", type=int)
    return jsonify(listar_campeonatos(empresa_atual(), ano=ano))


@app.route("/api/campeonatos", methods=["POST"])
@login_required
@funcao_required("campeonatos")
def campeonatos_criar():
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip()
    data_inicio = (corpo.get("data_inicio") or "").strip()
    data_fim = (corpo.get("data_fim") or "").strip() or None
    local = (corpo.get("local") or "").strip() or None
    observacoes = (corpo.get("observacoes") or "").strip() or None
    if not nome or not data_inicio:
        return jsonify(erro="Nome e data de início são obrigatórios."), 400

    campeonato_id = criar_campeonato(
        empresa_atual(), nome, data_inicio, data_fim=data_fim, local=local,
        observacoes=observacoes,
    )
    return jsonify(ok=True, campeonato_id=campeonato_id)


@app.route("/api/campeonatos/<campeonato_id>", methods=["POST"])
@login_required
@funcao_required("campeonatos")
def campeonatos_atualizar(campeonato_id):
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip()
    data_inicio = (corpo.get("data_inicio") or "").strip()
    data_fim = (corpo.get("data_fim") or "").strip() or None
    local = (corpo.get("local") or "").strip() or None
    observacoes = (corpo.get("observacoes") or "").strip() or None
    if not nome or not data_inicio:
        return jsonify(erro="Nome e data de início são obrigatórios."), 400

    try:
        atualizar_campeonato(
            empresa_atual(), campeonato_id, nome, data_inicio, data_fim=data_fim,
            local=local, observacoes=observacoes,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 404
    return jsonify(ok=True)


@app.route("/api/campeonatos/<campeonato_id>/remover", methods=["POST"])
@login_required
@gestor_required
def campeonatos_remover(campeonato_id):
    try:
        remover_campeonato(empresa_atual(), campeonato_id)
    except ValueError as e:
        return jsonify(erro=str(e)), 404
    return jsonify(ok=True)


@app.route("/api/clientes/buscar-cpf/<cpf>")
@login_required
@funcao_required("clientes")
def clientes_buscar_cpf(cpf):
    """Autocompletar nome + cliente_id ao digitar um CPF na tela de
    Resultados -- o cliente_id resolvido aqui é o que o formulário manda
    de volta ao salvar (nunca recalculado a partir do CPF no servidor,
    pra editar um resultado sem re-digitar o CPF não desvincular o
    cliente por engano).

    O filtro por empresa aqui não é formalidade: a UNIQUE de cpf virou
    composta (UNIQUE(empresa_id, cpf)) justamente porque a mesma pessoa
    pode ser cliente de dois despachantes. Sem o filtro, esta busca
    devolveria o cliente_id da empresa errada -- e ele iria parar
    gravado num resultado de campeonato desta aqui."""
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    cliente = con.execute(
        "SELECT cliente_id, nome FROM cliente WHERE cpf = ? AND empresa_id = ?",
        (cpf.strip(), empresa_id),
    ).fetchone()
    con.close()
    if not cliente:
        return jsonify(erro="Nenhum cliente com esse CPF."), 404
    return jsonify(cliente_id=cliente["cliente_id"], nome=cliente["nome"])


@app.route("/api/campeonatos/<campeonato_id>/resultados")
@login_required
@funcao_required("resultados")
def resultados_lista(campeonato_id):
    return jsonify(listar_resultados(empresa_atual(), campeonato_id))


@app.route("/api/campeonatos/<campeonato_id>/resultados", methods=["POST"])
@login_required
@funcao_required("resultados")
def resultados_criar(campeonato_id):
    corpo = request.get_json(force=True)
    nome_atirador = (corpo.get("nome_atirador") or "").strip()
    if not nome_atirador:
        return jsonify(erro="Nome do atirador é obrigatório."), 400

    colocacao = corpo.get("colocacao")
    try:
        resultado_id = criar_resultado(
            empresa_atual(),
            campeonato_id,
            nome_atirador,
            cliente_id=(corpo.get("cliente_id") or "").strip() or None,
            modalidade=(corpo.get("modalidade") or "").strip() or None,
            colocacao=int(colocacao) if colocacao not in (None, "") else None,
            pontuacao=(corpo.get("pontuacao") or "").strip() or None,
            observacoes=(corpo.get("observacoes") or "").strip() or None,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, resultado_id=resultado_id)


@app.route("/api/resultados/<resultado_id>", methods=["POST"])
@login_required
@funcao_required("resultados")
def resultados_atualizar(resultado_id):
    corpo = request.get_json(force=True)
    nome_atirador = (corpo.get("nome_atirador") or "").strip()
    if not nome_atirador:
        return jsonify(erro="Nome do atirador é obrigatório."), 400

    colocacao = corpo.get("colocacao")
    try:
        atualizar_resultado(
            empresa_atual(),
            resultado_id,
            nome_atirador,
            cliente_id=(corpo.get("cliente_id") or "").strip() or None,
            modalidade=(corpo.get("modalidade") or "").strip() or None,
            colocacao=int(colocacao) if colocacao not in (None, "") else None,
            pontuacao=(corpo.get("pontuacao") or "").strip() or None,
            observacoes=(corpo.get("observacoes") or "").strip() or None,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 404
    return jsonify(ok=True)


@app.route("/api/resultados/<resultado_id>/remover", methods=["POST"])
@login_required
@gestor_required
def resultados_remover(resultado_id):
    try:
        remover_resultado(empresa_atual(), resultado_id)
    except ValueError as e:
        return jsonify(erro=str(e)), 404
    return jsonify(ok=True)


@app.route("/api/identificar_cliente", methods=["POST"])
@login_required
@funcao_required("testar_pipeline")
def identificar():
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip() or None
    cpf = (corpo.get("cpf") or "").strip() or None
    email = (corpo.get("email") or "").strip() or None

    if not (nome or cpf or email):
        return jsonify(erro="Informe nome, CPF ou e-mail."), 400

    cliente = identificar_cliente(empresa_atual(), nome=nome, cpf=cpf, email=email)
    if not cliente:
        return jsonify(encontrado=False), 200

    return jsonify(
        encontrado=True,
        cliente_id=cliente["cliente_id"],
        nome=cliente["nome"],
        cpf=cliente["cpf"],
        email=cliente["email"],
    )


@app.route("/api/pipeline", methods=["POST"])
@login_required
@funcao_required("testar_pipeline")
def pipeline():
    corpo = request.get_json(force=True)
    mensagem = (corpo.get("mensagem") or "").strip()
    cliente_id = corpo.get("cliente_id")

    if not mensagem or not cliente_id:
        return jsonify(erro="Preencha a mensagem e escolha um cliente."), 400

    empresa_id = empresa_atual()
    try:
        classificacao = classificar(empresa_id, mensagem)
        plano = planejar(classificacao)
        dados = consultar(
            plano, empresa_id=empresa_id, cliente_id=cliente_id,
            classificacao=classificacao,
        )
        cliente_nome = (dados.get("cliente") or {}).get("nome", "Cliente")
        resposta = redigir(empresa_id, dados, cliente_nome=cliente_nome)
        resultado = auditar(empresa_id, resposta, dados, cliente_nome, plano)

        memoria_id = None
        if resultado.acao == "enviar":
            memoria_id = atualizar_memoria(
                empresa_id, cliente_id, classificacao, dados, resposta
            )
    except Exception as e:
        traceback.print_exc()
        return jsonify(erro=f"{type(e).__name__}: {e}"), 500

    return jsonify(
        classificacao=classificacao.model_dump(),
        plano={
            "rota": plano.rota,
            "fontes": plano.fontes,
            "encaminhar_humano": plano.encaminhar_humano,
            "motivo_humano": plano.motivo_humano,
        },
        dados=dados,
        resposta_gerada=resposta,
        auditoria=resultado.model_dump(),
        memoria_atualizada=memoria_id,
    )


@app.route("/api/pendentes")
@login_required
@funcao_required("aprovacoes_pendentes")
def pendentes():
    empresa_id = empresa_atual()
    itens = motor_mensagens.listar_pendentes(empresa_id)
    for item in itens:
        item["documentos"] = motor_documentos.listar_por_mensagem(
            empresa_id, item["mensagem_id"]
        )
    return jsonify(itens)


@app.route("/api/pendentes/<mensagem_id>/aprovar", methods=["POST"])
@login_required
@funcao_required("aprovacoes_pendentes")
def aprovar(mensagem_id):
    corpo = request.get_json(silent=True) or {}
    texto_final = corpo.get("texto")
    resultado = aprovar_mensagem_pendente(
        empresa_atual(), mensagem_id, texto_final=texto_final,
        responsavel_id=session.get("usuario_id"),
    )
    if "erro" in resultado:
        return jsonify(resultado), 400
    return jsonify(resultado)


@app.route("/api/pendentes/<mensagem_id>/rejeitar", methods=["POST"])
@login_required
@funcao_required("aprovacoes_pendentes")
def rejeitar(mensagem_id):
    resultado = rejeitar_mensagem_pendente(
        empresa_atual(), mensagem_id, responsavel_id=session.get("usuario_id")
    )
    if "erro" in resultado:
        return jsonify(resultado), 400
    return jsonify(resultado)


# --------------------------------------------------------------------
# Atendimentos (CRM) -- caixa de entrada unificada de E-mail e WhatsApp.
# Lê a tabela `conversa` (core/motor_conversas.py), que passou a ser
# alimentada pelo pipeline. Todo filtro por empresa vem de
# empresa_atual(), nunca da query string: o conversa_id é global, então
# sem esse filtro dava pra abrir a conversa de outra empresa sabendo o ID.
# --------------------------------------------------------------------

@app.route("/api/conversas")
@login_required
@funcao_required("atendimentos")
def conversas_lista():
    empresa_id = empresa_atual()
    canal = (request.args.get("canal") or "").strip() or None
    if canal and canal not in motor_conversas.CANAIS_VALIDOS:
        return jsonify(erro=f"Canal inválido: {canal}."), 400
    status = (request.args.get("status") or "").strip() or None
    busca = (request.args.get("busca") or "").strip() or None

    return jsonify({
        "conversas": motor_conversas.listar_conversas(
            empresa_id, canal=canal, status=status, busca=busca
        ),
        "contadores": motor_conversas.contar_por_canal(empresa_id),
        "canais": [
            {"chave": c, "rotulo": motor_conversas.CANAIS_ROTULO.get(c, c)}
            for c in motor_conversas.CANAIS_VALIDOS
        ],
        "status_validos": list(motor_conversas.STATUS_VALIDOS),
        # A tela avisa em cima quando o WhatsApp está simulado -- sem
        # isso o usuário só descobriria ao ver um cliente real não
        # receber a resposta que o painel diz ter enviado.
        "whatsapp": status_whatsapp(),
    })


@app.route("/api/conversas/<conversa_id>")
@login_required
@funcao_required("atendimentos")
def conversa_detalhe(conversa_id):
    conversa = motor_conversas.obter_conversa(empresa_atual(), conversa_id)
    if not conversa:
        return jsonify(erro="Conversa não encontrada."), 404

    con = conectar(empresa_atual())
    try:
        usuarios = [
            dict(linha) for linha in con.execute(
                "SELECT usuario_id, nome FROM usuario WHERE empresa_id = ? "
                "AND ativo = 'Sim' ORDER BY nome",
                (empresa_atual(),),
            ).fetchall()
        ]
    finally:
        con.close()

    conversa["usuarios"] = usuarios
    conversa["status_validos"] = list(motor_conversas.STATUS_VALIDOS)
    return jsonify(conversa)


@app.route("/api/conversas/<conversa_id>/responder", methods=["POST"])
@login_required
@funcao_required("atendimentos")
def conversa_responder(conversa_id):
    """Resposta escrita por uma PESSOA no painel -- não passa pelo Motor
    IA nem pelo Auditor de propósito: quem digitou já é o humano que a
    revisão humana existe para garantir."""
    empresa_id = empresa_atual()
    conversa = motor_conversas.obter_conversa(empresa_id, conversa_id)
    if not conversa:
        return jsonify(erro="Conversa não encontrada."), 404

    texto = ((request.get_json(silent=True) or {}).get("texto") or "").strip()
    if not texto:
        return jsonify(erro="Escreva uma mensagem antes de enviar."), 400

    canal = conversa["canal"]
    destino = (
        conversa["cliente_telefone"] if canal == "WhatsApp" else conversa["cliente_email"]
    )
    if not destino:
        rotulo = "telefone" if canal == "WhatsApp" else "e-mail"
        return jsonify(
            erro=f"O cliente não tem {rotulo} cadastrado -- não há para onde enviar."
        ), 400

    try:
        entrega = entregar_resposta(
            canal, destino, texto, assunto=conversa.get("assunto_principal")
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify(erro=f"{type(e).__name__}: {e}"), 400

    if not entrega["enviado"]:
        return jsonify(erro=entrega["motivo"] or "Não foi possível enviar."), 400

    mensagem_id = motor_conversas.registrar_saida(
        empresa_id,
        conversa_id,
        cliente_id=conversa["cliente_id"],
        texto=texto,
        canal=canal,
        caso_id=conversa.get("caso_id"),
        destino=destino,
        assunto=conversa.get("assunto_principal"),
        responsavel_id=session.get("usuario_id"),
    )
    return jsonify(
        mensagem_id=mensagem_id, enviado=True, simulado=entrega["simulado"], canal=canal
    )


@app.route("/api/conversas/<conversa_id>/status", methods=["POST"])
@login_required
@funcao_required("atendimentos")
def conversa_atualizar_status(conversa_id):
    empresa_id = empresa_atual()
    if not motor_conversas.obter_conversa(empresa_id, conversa_id):
        return jsonify(erro="Conversa não encontrada."), 404
    status = ((request.get_json(silent=True) or {}).get("status") or "").strip()
    try:
        motor_conversas.atualizar_status(
            empresa_id, conversa_id, status,
            atualizado_por=session.get("usuario_id") or "Painel administrativo",
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(conversa_id=conversa_id, status=status)


@app.route("/api/conversas/<conversa_id>/responsavel", methods=["POST"])
@login_required
@funcao_required("atendimentos")
def conversa_atualizar_responsavel(conversa_id):
    empresa_id = empresa_atual()
    if not motor_conversas.obter_conversa(empresa_id, conversa_id):
        return jsonify(erro="Conversa não encontrada."), 404
    responsavel_id = ((request.get_json(silent=True) or {}).get("responsavel_id") or "").strip() or None
    try:
        motor_conversas.atualizar_responsavel(
            empresa_id, conversa_id, responsavel_id,
            atualizado_por=session.get("usuario_id") or "Painel administrativo",
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(conversa_id=conversa_id, responsavel_id=responsavel_id)


if __name__ == "__main__":
    # debug=False desliga o debugger interativo do Werkzeug (permite
    # rodar codigo Python arbitrario pelo navegador em qualquer excecao
    # nao tratada -- risco serio se este processo for exposto alem de
    # localhost).
    #
    # use_reloader=False de proposito (2026-07-29): mesmo motivo ja
    # aplicado em atendimento/webhook.py e portal/app.py, que o painel
    # ficou de fora na primeira passada. Nesta maquina o python.exe do
    # .venv e um lancador que executa o Python global como filho, e o
    # reloader do Werkzeug reinicia usando esse interpretador de fora do
    # .venv -- a cadeia observada alternava .venv -> global -> .venv ->
    # global sem convergir, deixando 4 processos por instancia do painel.
    # Custo de deixar desligado: editar o codigo exige reiniciar o
    # processo na mao (o template .html continua recarregando sozinho,
    # via TEMPLATES_AUTO_RELOAD la no topo do arquivo).
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
