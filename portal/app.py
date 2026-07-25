"""Portal do Cliente -- autoatendimento pros clientes reais (não staff).
App Flask separado do painel administrativo (webapp/), rodando em porta
própria (5002), com secret key e nome de cookie de sessão totalmente
separados -- ver docs/portal_cliente_arquitetura.md, seção 3
(isolamento de dado é o risco central desta peça: primeira superfície
pública do sistema, domínio regulado de arma de fogo).

Login sem senha, link mágico por e-mail (core/motor_portal_auth.py).
MVP (decisão 1 do documento de arquitetura): status do caso + checklist
de documentos + upload -- sem chat com a IA pelo Portal por enquanto.
"""
import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for

from core import motor_checklist, motor_documentos
from core.conexao import CORE_DB
from core.motor_portal_auth import criar_token, localizar_cliente_por_cpf_ou_email, validar_e_consumir_token
from integracoes.gmail import enviar_email, gmail_configurado

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Mesmo allowlist/limite de integracoes/gmail.py e webapp/app.py --
# duplicado de propósito, mesmo padrão já usado no projeto (canais
# diferentes não compartilham infra de validação).
DOCUMENTO_EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
DOCUMENTO_TAMANHO_MAXIMO = 15 * 1024 * 1024  # 15 MB

load_dotenv(ENV_PATH)
if not os.getenv("PORTAL_SECRET_KEY"):
    _chave = secrets.token_hex(32)
    set_key(str(ENV_PATH), "PORTAL_SECRET_KEY", _chave)
    os.environ["PORTAL_SECRET_KEY"] = _chave

app = Flask(__name__)
app.secret_key = os.environ["PORTAL_SECRET_KEY"]
app.config["TEMPLATES_AUTO_RELOAD"] = True
# Nome de cookie próprio -- por padrão o Flask usa "session" pros dois
# apps, e como painel admin (porta 5000) e Portal (porta 5002) podem
# rodar no mesmo navegador ao mesmo tempo em localhost, cookies com o
# mesmo nome se sobrescreveriam entre si.
app.config["SESSION_COOKIE_NAME"] = "portal_session"

URL_BASE = os.environ.get("PORTAL_URL_BASE", "http://127.0.0.1:5002")


def cliente_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("cliente_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/", methods=["GET", "POST"])
def login():
    mensagem = None
    if request.method == "POST":
        identificador = (request.form.get("identificador") or "").strip()
        cliente = localizar_cliente_por_cpf_ou_email(identificador) if identificador else None
        if cliente:
            token = criar_token(cliente["cliente_id"])
            link = f"{URL_BASE}/entrar/{token}"
            if gmail_configurado():
                enviar_email(
                    destinatario=cliente["email"],
                    assunto="Acesso ao Portal do Cliente -- Smith Clube de Tiro",
                    corpo=(
                        f"Olá {cliente['nome']},\n\n"
                        "Use o link abaixo para acessar o Portal (válido por 15 minutos, "
                        "uso único):\n\n"
                        f"{link}\n\n"
                        "Se você não solicitou esse acesso, é só ignorar este e-mail.\n\n"
                        "Equipe Smith Clube de Tiro"
                    ),
                )
            else:
                # Gmail ainda não autorizado nesta máquina (uso local/dev)
                # -- imprime o link no console pra dar pra testar sem
                # depender de e-mail real chegando.
                print(f"[PORTAL] Gmail não configurado -- link de acesso: {link}")
        # Mensagem sempre igual, ache ou não o cliente -- não dá pista se
        # um CPF/e-mail está cadastrado (evita enumeração de clientes).
        mensagem = "Se encontrarmos esse CPF ou e-mail no nosso cadastro, enviamos um link de acesso por e-mail."
    return render_template("portal_login.html", mensagem=mensagem)


@app.route("/entrar/<token>")
def entrar(token):
    cliente_id = validar_e_consumir_token(token)
    if not cliente_id:
        return render_template(
            "portal_login.html",
            erro="Link inválido ou expirado. Solicite um novo acesso abaixo.",
        )
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    cliente = con.execute("SELECT nome FROM cliente WHERE cliente_id = ?", (cliente_id,)).fetchone()
    con.close()
    session.clear()
    session["cliente_id"] = cliente_id
    session["cliente_nome"] = cliente["nome"] if cliente else ""
    return redirect(url_for("dashboard"))


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/portal")
@cliente_login_required
def dashboard():
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row

    casos = con.execute(
        "SELECT caso_id, titulo, descricao, status, categoria, criado_em, atualizado_em "
        "FROM caso WHERE cliente_id = ? ORDER BY atualizado_em DESC",
        (cliente_id,),
    ).fetchall()

    casos_completos = []
    for linha_caso in casos:
        caso = dict(linha_caso)
        processos = con.execute(
            "SELECT p.processo_id, p.protocolo, p.status, p.prazo_estimado, "
            "p.proxima_acao, s.nome_servico "
            "FROM processo p JOIN servico s ON s.service_id = p.servico_id "
            "WHERE p.caso_id = ? ORDER BY p.data_abertura",
            (caso["caso_id"],),
        ).fetchall()
        processos_completos = []
        for linha_processo in processos:
            processo = dict(linha_processo)
            processo["checklist"] = motor_checklist.status_checklist(con, processo["processo_id"])
            processos_completos.append(processo)
        caso["processos"] = processos_completos
        casos_completos.append(caso)

    documentos = con.execute(
        "SELECT documento_id, tipo_documento, nome_arquivo, status, data_envio "
        "FROM documento WHERE cliente_id = ? ORDER BY data_envio DESC",
        (cliente_id,),
    ).fetchall()
    con.close()

    return render_template(
        "portal_dashboard.html",
        cliente_nome=session.get("cliente_nome"),
        casos=casos_completos,
        documentos=[dict(d) for d in documentos],
    )


@app.route("/portal/documentos", methods=["POST"])
@cliente_login_required
def upload_documento():
    cliente_id = session["cliente_id"]
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(erro="Selecione um arquivo."), 400

    extensao = Path(arquivo.filename).suffix.lower()
    if extensao not in DOCUMENTO_EXTENSOES_ACEITAS:
        return jsonify(erro=f"Tipo de arquivo não aceito: {extensao or '(sem extensão)'}."), 400

    conteudo = arquivo.read()
    if not conteudo:
        return jsonify(erro="Arquivo vazio."), 400
    if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
        return jsonify(erro="Arquivo maior que 15MB."), 400

    caso_id = (request.form.get("caso_id") or "").strip() or None
    if not caso_id:
        return jsonify(erro="Selecione a qual caso este documento pertence."), 400

    # Nunca confiar no caso_id vindo do formulário sem checar que
    # pertence a este cliente -- ponto central de isolamento de dado do
    # Portal (docs/portal_cliente_arquitetura.md, seção 3). Sem essa
    # checagem, um cliente poderia anexar (ou pior, associar) um
    # documento ao caso de outra pessoa só trocando o ID na requisição.
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    dono = con.execute("SELECT cliente_id FROM caso WHERE caso_id = ?", (caso_id,)).fetchone()
    con.close()
    if not dono or dono["cliente_id"] != cliente_id:
        return jsonify(erro="Caso não encontrado."), 404

    documento_id = motor_documentos.salvar_documento(
        cliente_id, conteudo, arquivo.filename,
        caso_id=caso_id,
        tipo_documento=(request.form.get("tipo_documento") or "").strip() or "Anexo enviado pelo cliente (Portal)",
    )
    return jsonify(ok=True, documento_id=documento_id)


@app.route("/portal/documentos/<documento_id>/arquivo")
@cliente_login_required
def download_documento(documento_id):
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    doc = con.execute(
        "SELECT cliente_id, nome_arquivo, link_arquivo FROM documento WHERE documento_id = ?",
        (documento_id,),
    ).fetchone()
    con.close()
    # Mesma checagem de posse do upload -- documento de outro cliente
    # nunca é servido, mesmo se o ID for adivinhado.
    if not doc or doc["cliente_id"] != cliente_id or not doc["link_arquivo"]:
        return jsonify(erro="Documento não encontrado."), 404

    caminho = Path(doc["link_arquivo"])
    if not caminho.is_file():
        return jsonify(erro="Arquivo não encontrado no disco."), 404
    nome_sugerido = Path(doc["nome_arquivo"] or "").name or caminho.name
    return send_file(caminho, as_attachment=True, download_name=nome_sugerido)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5002, debug=False, use_reloader=True)
