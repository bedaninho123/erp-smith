"""Painel administrativo do ERP Smith: status do banco/módulos, testador
do pipeline do Motor IA, e fila de aprovações pendentes. Protegido por
login (usuario.senha_hash) -- ver webapp/definir_senha.py para cadastrar
a senha de um usuário antes do primeiro acesso.
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

from atendimento.processar import aprovar_mensagem_pendente, rejeitar_mensagem_pendente
from core import motor_mensagens
from core.motor_casos import STATUS_VALIDOS, atualizar_responsavel, atualizar_status
from integracoes.config import shooting_house_configurado
from motor_ia.atualizador_memoria import atualizar_memoria
from motor_ia.auditor import auditar
from motor_ia.classificador import classificar
from motor_ia.conexao import CORE_DB, DOMAIN_DB, conectar
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

app = Flask(__name__)
app.secret_key = os.environ["WEBAPP_SECRET_KEY"]


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            if request.path.startswith("/api/"):
                return jsonify(erro="Não autenticado."), 401
            return redirect(url_for("login", proximo=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        con = sqlite3.connect(CORE_DB)
        con.row_factory = sqlite3.Row
        linha = con.execute(
            "SELECT usuario_id, nome, senha_hash FROM usuario "
            "WHERE lower(email) = ? AND ativo = 'Sim'",
            (email,),
        ).fetchone()
        con.close()
        if linha and linha["senha_hash"] and check_password_hash(linha["senha_hash"], senha):
            session["usuario_id"] = linha["usuario_id"]
            session["usuario_nome"] = linha["nome"]
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
    return render_template("index.html", usuario_nome=session.get("usuario_nome"))


@app.route("/api/status")
@login_required
def status():
    con = sqlite3.connect(CORE_DB)
    tabelas_core = [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    tabelas = []
    for nome in tabelas_core:
        n = con.execute(f"SELECT COUNT(*) FROM {nome}").fetchone()[0]
        tabelas.append({"nome": nome, "linhas": n, "camada": "Core"})
    con.close()

    con_dom = sqlite3.connect(DOMAIN_DB)
    tabelas_dom = [
        r[0] for r in con_dom.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    for nome in tabelas_dom:
        n = con_dom.execute(f"SELECT COUNT(*) FROM {nome}").fetchone()[0]
        tabelas.append({"nome": nome, "linhas": n, "camada": "Domínio"})
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

    con_log = sqlite3.connect(CORE_DB)
    con_log.row_factory = sqlite3.Row
    por_modulo = [
        dict(r) for r in con_log.execute(
            "SELECT prompt_key, COUNT(*) AS chamadas, "
            "SUM(tokens_entrada) AS tokens_entrada, SUM(tokens_saida) AS tokens_saida, "
            "SUM(CASE WHEN resultado = 'Erro' THEN 1 ELSE 0 END) AS erros "
            "FROM log_ia GROUP BY prompt_key ORDER BY prompt_key"
        ).fetchall()
    ]
    totais = con_log.execute(
        "SELECT COUNT(*) AS chamadas, SUM(tokens_entrada) AS tokens_entrada, "
        "SUM(tokens_saida) AS tokens_saida FROM log_ia"
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
def casos():
    status = request.args.get("status") or None
    categoria = request.args.get("categoria") or None

    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    query = (
        "SELECT c.caso_id, c.titulo, c.categoria, c.status, c.prioridade, "
        "c.atualizado_em, c.criado_em, cl.cliente_id, cl.nome AS cliente_nome, "
        "u.nome AS responsavel_nome "
        "FROM caso c "
        "JOIN cliente cl ON cl.cliente_id = c.cliente_id "
        "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.ativo = 'Sim'"
    )
    params = []
    if status:
        query += " AND c.status = ?"
        params.append(status)
    if categoria:
        query += " AND c.categoria = ?"
        params.append(categoria)
    query += " ORDER BY c.atualizado_em DESC"

    casos = [dict(r) for r in con.execute(query, params).fetchall()]
    status_disponiveis = [
        r[0] for r in con.execute(
            "SELECT DISTINCT status FROM caso WHERE ativo = 'Sim' ORDER BY status"
        ).fetchall()
    ]
    categorias_disponiveis = [
        r[0] for r in con.execute(
            "SELECT DISTINCT categoria FROM caso WHERE ativo = 'Sim' ORDER BY categoria"
        ).fetchall()
    ]
    con.close()

    return jsonify(
        casos=casos, status_disponiveis=status_disponiveis,
        categorias_disponiveis=categorias_disponiveis,
    )


@app.route("/api/casos/<caso_id>")
@login_required
def caso_detalhe(caso_id):
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row

    caso = con.execute(
        "SELECT c.*, cl.nome AS cliente_nome, cl.cpf AS cliente_cpf, "
        "cl.email AS cliente_email, cl.telefone AS cliente_telefone, "
        "u.nome AS responsavel_nome "
        "FROM caso c "
        "JOIN cliente cl ON cl.cliente_id = c.cliente_id "
        "LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.caso_id = ?",
        (caso_id,),
    ).fetchone()
    if not caso:
        con.close()
        return jsonify(erro=f"Caso não encontrado: {caso_id}"), 404

    processos = con.execute(
        "SELECT p.*, s.nome_servico FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id "
        "WHERE p.caso_id = ? ORDER BY p.data_abertura",
        (caso_id,),
    ).fetchall()

    documentos = con.execute(
        "SELECT * FROM documento WHERE caso_id = ? "
        "OR processo_id IN (SELECT processo_id FROM processo WHERE caso_id = ?) "
        "ORDER BY data_envio",
        (caso_id, caso_id),
    ).fetchall()

    historico = con.execute(
        "SELECT * FROM historico WHERE caso_id = ? ORDER BY criado_em",
        (caso_id,),
    ).fetchall()

    mensagens = con.execute(
        "SELECT * FROM mensagem WHERE caso_id = ? ORDER BY data_hora",
        (caso_id,),
    ).fetchall()

    usuarios = con.execute(
        "SELECT usuario_id, nome FROM usuario WHERE ativo = 'Sim' ORDER BY nome"
    ).fetchall()

    con.close()
    return jsonify(
        caso=dict(caso),
        processos=[dict(r) for r in processos],
        documentos=[dict(r) for r in documentos],
        historico=[dict(r) for r in historico],
        mensagens=[dict(r) for r in mensagens],
        status_validos=sorted(STATUS_VALIDOS),
        usuarios=[dict(r) for r in usuarios],
    )


@app.route("/api/casos/<caso_id>/status", methods=["POST"])
@login_required
def caso_atualizar_status(caso_id):
    corpo = request.get_json(force=True)
    novo_status = (corpo.get("status") or "").strip()
    motivo = (corpo.get("motivo") or "").strip() or None
    if not novo_status:
        return jsonify(erro="Informe o novo status."), 400
    try:
        atualizar_status(
            caso_id, novo_status, motivo=motivo,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/casos/<caso_id>/responsavel", methods=["POST"])
@login_required
def caso_atualizar_responsavel(caso_id):
    corpo = request.get_json(force=True)
    novo_responsavel_id = (corpo.get("responsavel_id") or "").strip() or None
    try:
        atualizar_responsavel(
            caso_id, novo_responsavel_id,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/documentos/<documento_id>/arquivo")
@login_required
def documento_arquivo(documento_id):
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    doc = con.execute(
        "SELECT nome_arquivo, link_arquivo FROM documento WHERE documento_id = ?",
        (documento_id,),
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
    return send_file(caminho, as_attachment=True, download_name=nome_sugerido)


@app.route("/api/clientes")
@login_required
def clientes():
    con = sqlite3.connect(CORE_DB)
    linhas = con.execute(
        "SELECT cliente_id, nome FROM cliente ORDER BY nome"
    ).fetchall()
    con.close()
    return jsonify([{"cliente_id": r[0], "nome": r[1]} for r in linhas])


@app.route("/api/clientes/lista")
@login_required
def clientes_lista():
    busca = (request.args.get("busca") or "").strip()

    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    query = (
        "SELECT cl.cliente_id, cl.nome, cl.cpf, cl.email, cl.telefone, cl.cidade, "
        "cl.status, cl.data_cadastro, cl.ultima_interacao, "
        "(SELECT COUNT(*) FROM caso c WHERE c.cliente_id = cl.cliente_id "
        " AND c.ativo = 'Sim' AND c.status NOT IN ('Encerrado', 'Cancelado')) AS casos_abertos "
        "FROM cliente cl"
    )
    params = []
    if busca:
        query += " WHERE cl.nome LIKE ? OR cl.cpf LIKE ? OR cl.email LIKE ?"
        curinga = f"%{busca}%"
        params += [curinga, curinga, curinga]
    query += " ORDER BY cl.nome"

    clientes = [dict(r) for r in con.execute(query, params).fetchall()]
    con.close()
    return jsonify(clientes=clientes)


@app.route("/api/clientes/<cliente_id>")
@login_required
def cliente_detalhe(cliente_id):
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row

    cliente = con.execute(
        "SELECT * FROM cliente WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()
    if not cliente:
        con.close()
        return jsonify(erro=f"Cliente não encontrado: {cliente_id}"), 404

    casos = con.execute(
        "SELECT c.caso_id, c.titulo, c.categoria, c.status, c.prioridade, "
        "c.atualizado_em, u.nome AS responsavel_nome "
        "FROM caso c LEFT JOIN usuario u ON u.usuario_id = c.responsavel_id "
        "WHERE c.cliente_id = ? AND c.ativo = 'Sim' ORDER BY c.atualizado_em DESC",
        (cliente_id,),
    ).fetchall()

    con.close()
    return jsonify(cliente=dict(cliente), casos=[dict(r) for r in casos])


@app.route("/api/configuracoes")
@login_required
def configuracoes_lista():
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    linhas = con.execute(
        "SELECT * FROM configuracoes ORDER BY categoria, chave"
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in linhas])


@app.route("/api/configuracoes/<config_id>", methods=["POST"])
@login_required
def configuracoes_atualizar(config_id):
    corpo = request.get_json(force=True)
    valor = corpo.get("valor")
    ativo = corpo.get("ativo")
    if valor is None or not str(valor).strip():
        return jsonify(erro="O valor não pode ficar vazio."), 400
    if ativo not in ("Sim", "Não"):
        return jsonify(erro="Campo 'ativo' inválido."), 400

    con = sqlite3.connect(CORE_DB)
    existe = con.execute(
        "SELECT 1 FROM configuracoes WHERE config_id = ?", (config_id,)
    ).fetchone()
    if not existe:
        con.close()
        return jsonify(erro=f"Configuração não encontrada: {config_id}"), 404

    con.execute(
        "UPDATE configuracoes SET valor = ?, ativo = ? WHERE config_id = ?",
        (str(valor).strip(), ativo, config_id),
    )
    con.commit()
    con.close()
    return jsonify(ok=True)


@app.route("/api/identificar_cliente", methods=["POST"])
@login_required
def identificar():
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip() or None
    cpf = (corpo.get("cpf") or "").strip() or None
    email = (corpo.get("email") or "").strip() or None

    if not (nome or cpf or email):
        return jsonify(erro="Informe nome, CPF ou e-mail."), 400

    cliente = identificar_cliente(nome=nome, cpf=cpf, email=email)
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
def pipeline():
    corpo = request.get_json(force=True)
    mensagem = (corpo.get("mensagem") or "").strip()
    cliente_id = corpo.get("cliente_id")

    if not mensagem or not cliente_id:
        return jsonify(erro="Preencha a mensagem e escolha um cliente."), 400

    try:
        classificacao = classificar(mensagem)
        plano = planejar(classificacao)
        dados = consultar(plano, cliente_id=cliente_id, classificacao=classificacao)
        cliente_nome = (dados.get("cliente") or {}).get("nome", "Cliente")
        resposta = redigir(dados, cliente_nome=cliente_nome)
        resultado = auditar(resposta, dados, cliente_nome, plano)

        memoria_id = None
        if resultado.acao == "enviar":
            memoria_id = atualizar_memoria(cliente_id, classificacao, dados, resposta)
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
def pendentes():
    return jsonify(motor_mensagens.listar_pendentes())


@app.route("/api/pendentes/<mensagem_id>/aprovar", methods=["POST"])
@login_required
def aprovar(mensagem_id):
    corpo = request.get_json(silent=True) or {}
    texto_final = corpo.get("texto")
    resultado = aprovar_mensagem_pendente(
        mensagem_id, texto_final=texto_final, responsavel_id=session.get("usuario_id")
    )
    if "erro" in resultado:
        return jsonify(resultado), 400
    return jsonify(resultado)


@app.route("/api/pendentes/<mensagem_id>/rejeitar", methods=["POST"])
@login_required
def rejeitar(mensagem_id):
    resultado = rejeitar_mensagem_pendente(mensagem_id, responsavel_id=session.get("usuario_id"))
    if "erro" in resultado:
        return jsonify(resultado), 400
    return jsonify(resultado)


if __name__ == "__main__":
    # debug=False desliga o debugger interativo do Werkzeug (permite
    # rodar codigo Python arbitrario pelo navegador em qualquer excecao
    # nao tratada -- risco serio se este processo for exposto alem de
    # localhost). use_reloader continua ligado so pra reiniciar sozinho
    # quando o codigo muda, sem esse risco.
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=True)
