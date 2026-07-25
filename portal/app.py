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
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv, set_key
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from core import motor_checklist, motor_documentos
from core.conexao import CORE_DB
from core.motor_portal_auth import criar_token, localizar_cliente_por_cpf_ou_email, validar_e_consumir_token
from domain.clube_tiro.motor_campeonatos import listar_campeonatos, obter_campeonato
from domain.clube_tiro.motor_resultados import listar_resultados
from integracoes.gmail import enviar_email, gmail_configurado
from integracoes.shooting_house import consultar_cr, consultar_habitualidade

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Mesmo allowlist/limite de integracoes/gmail.py e webapp/app.py --
# duplicado de propósito, mesmo padrão já usado no projeto (canais
# diferentes não compartilham infra de validação).
DOCUMENTO_EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
DOCUMENTO_TAMANHO_MAXIMO = 15 * 1024 * 1024  # 15 MB

MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
MESES_PT_ABREV = [m[:3].upper() for m in MESES_PT]

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


def _data_br(data_iso: Optional[str]) -> Optional[str]:
    """Converte um datetime ISO (ex.: '2026-08-09T00:00:00Z') pro formato
    dd/mm/aaaa usado no resto do Portal (Campeonatos, Habitualidade) --
    sem isso, prazo_estimado aparecia cru só nesta tela, único lugar do
    Portal com data no formato errado."""
    if not data_iso:
        return None
    return datetime.strptime(data_iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def _classe_selo(status: str) -> str:
    """Cor do selo de status na UI (ver portal/templates/_portal_estilo.html)
    -- puramente de apresentação, não é regra de negócio (não decide o
    que o status significa, só como ele aparece na tela)."""
    s = (status or "").lower()
    if "cancel" in s or "encerr" in s:
        return "neutro"
    if "aguardando cliente" in s or "aguardando documentos" in s:
        return "signal"
    return "padrao"


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
        return render_template("portal_expirado.html")
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


def _processos_com_checklist(con, caso_id: str) -> list:
    """Processos de um caso, cada um já com o checklist de documentos e
    as contagens pra o alvo de progresso -- usado tanto no resumo do
    dashboard (agregado por caso) quanto na tela de detalhe (completo)."""
    processos = con.execute(
        "SELECT p.processo_id, p.protocolo, p.status, p.prazo_estimado, "
        "p.proxima_acao, s.nome_servico "
        "FROM processo p JOIN servico s ON s.service_id = p.servico_id "
        "WHERE p.caso_id = ? ORDER BY p.data_abertura",
        (caso_id,),
    ).fetchall()
    resultado = []
    for linha_processo in processos:
        processo = dict(linha_processo)
        processo["status_classe"] = _classe_selo(processo["status"])
        processo["prazo_estimado_fmt"] = _data_br(processo["prazo_estimado"])
        checklist = motor_checklist.status_checklist(con, processo["processo_id"])
        processo["checklist"] = checklist
        processo["checklist_total"] = len(checklist)
        processo["checklist_recebidos"] = sum(1 for item in checklist if item["recebido"])
        processo["checklist_pct"] = (
            round(100 * processo["checklist_recebidos"] / processo["checklist_total"])
            if checklist else 0
        )
        resultado.append(processo)
    return resultado


def _casos_com_resumo(con, cliente_id: str) -> list:
    casos = con.execute(
        "SELECT caso_id, titulo, status, categoria "
        "FROM caso WHERE cliente_id = ? ORDER BY atualizado_em DESC",
        (cliente_id,),
    ).fetchall()

    casos_resumo = []
    for linha_caso in casos:
        caso = dict(linha_caso)
        caso["status_classe"] = _classe_selo(caso["status"])
        processos = _processos_com_checklist(con, caso["caso_id"])
        caso["checklist_total"] = sum(p["checklist_total"] for p in processos)
        caso["checklist_recebidos"] = sum(p["checklist_recebidos"] for p in processos)
        caso["checklist_pct"] = (
            round(100 * caso["checklist_recebidos"] / caso["checklist_total"])
            if caso["checklist_total"] else 0
        )
        casos_resumo.append(caso)
    return casos_resumo


def _resumo_habitualidade(cpf: str) -> dict:
    """Status de CR + contagem de participações (habitualidade) do
    cliente no clube -- consulta ao vivo o Shooting House (ou dado
    simulado enquanto a credencial não existe), nunca guarda cópia
    própria (integracoes/shooting_house.py). Devolve tem_registro=False
    sem erro pra quem nunca foi atirador -- cliente cadastrado não
    implica atirador ativo."""
    cr = consultar_cr(cpf)
    hab = consultar_habitualidade(cpf)
    eventos = []
    for dados in (hab.get("habitualidades") or {}).values():
        eventos.extend(dados.get("eventos", []))
    return {"cr": cr, "total_participacoes": len(eventos), "tem_registro": bool(cr) or bool(eventos)}


@app.route("/portal")
@cliente_login_required
def dashboard():
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row

    cliente = con.execute("SELECT cpf FROM cliente WHERE cliente_id = ?", (cliente_id,)).fetchone()

    casos_resumo = _casos_com_resumo(con, cliente_id)
    casos_abertos = [c for c in casos_resumo if c["status"] not in ("Encerrado", "Cancelado")]

    processos_rows = con.execute(
        "SELECT p.processo_id, p.status, p.proxima_acao, p.prazo_estimado, "
        "s.nome_servico, ca.caso_id, ca.titulo AS caso_titulo "
        "FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id "
        "JOIN caso ca ON ca.caso_id = p.caso_id "
        "WHERE p.cliente_id = ? ORDER BY p.ultima_atualizacao DESC",
        (cliente_id,),
    ).fetchall()

    processos_em_andamento = []
    documentos_pendentes = 0
    for linha in processos_rows:
        proc = dict(linha)
        checklist = motor_checklist.status_checklist(con, proc["processo_id"])
        documentos_pendentes += sum(1 for item in checklist if not item["recebido"])
        if proc["status"] not in ("Concluído", "Cancelado"):
            proc["status_classe"] = _classe_selo(proc["status"])
            processos_em_andamento.append(proc)
    con.close()

    proximos_campeonatos = _proximos_campeonatos()

    habitualidade_resumo = None
    if cliente and cliente["cpf"]:
        habitualidade_resumo = _resumo_habitualidade(cliente["cpf"])

    return render_template(
        "portal_home.html",
        ativo="home",
        cliente_nome=session.get("cliente_nome"),
        primeiro_nome=(session.get("cliente_nome") or "").split(" ")[0],
        casos_abertos=len(casos_abertos),
        documentos_pendentes=documentos_pendentes,
        processos_em_andamento=processos_em_andamento[:4],
        total_processos_em_andamento=len(processos_em_andamento),
        proximo_campeonato=proximos_campeonatos[0] if proximos_campeonatos else None,
        habitualidade_resumo=habitualidade_resumo,
    )


@app.route("/portal/casos")
@cliente_login_required
def casos_lista():
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    casos_resumo = _casos_com_resumo(con, cliente_id)
    con.close()

    return render_template(
        "portal_casos.html",
        ativo="casos",
        cliente_nome=session.get("cliente_nome"),
        casos=casos_resumo,
    )


@app.route("/portal/processos")
@cliente_login_required
def processos():
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    linhas = con.execute(
        "SELECT p.processo_id, p.protocolo, p.status, p.prazo_estimado, p.proxima_acao, "
        "s.nome_servico, ca.caso_id, ca.titulo AS caso_titulo "
        "FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id "
        "JOIN caso ca ON ca.caso_id = p.caso_id "
        "WHERE p.cliente_id = ? ORDER BY p.ultima_atualizacao DESC",
        (cliente_id,),
    ).fetchall()

    processos_lista = []
    for linha in linhas:
        proc = dict(linha)
        proc["status_classe"] = _classe_selo(proc["status"])
        proc["prazo_estimado_fmt"] = _data_br(proc["prazo_estimado"])
        checklist = motor_checklist.status_checklist(con, proc["processo_id"])
        proc["checklist_total"] = len(checklist)
        proc["checklist_recebidos"] = sum(1 for item in checklist if item["recebido"])
        processos_lista.append(proc)
    con.close()

    return render_template(
        "portal_processos.html",
        ativo="processos",
        cliente_nome=session.get("cliente_nome"),
        processos=processos_lista,
    )


@app.route("/portal/habitualidade")
@cliente_login_required
def habitualidade():
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    cliente = con.execute("SELECT cpf FROM cliente WHERE cliente_id = ?", (cliente_id,)).fetchone()
    con.close()

    cpf = cliente["cpf"] if cliente else None
    cr = None
    eventos = []
    if cpf:
        cr = consultar_cr(cpf)
        hab = consultar_habitualidade(cpf)
        for modalidade, dados in (hab.get("habitualidades") or {}).items():
            for ev in dados.get("eventos", []):
                eventos.append({**ev, "modalidade_grupo": modalidade})
        eventos.sort(key=lambda e: datetime.strptime(e["data_participacao"], "%d/%m/%Y"), reverse=True)

    return render_template(
        "portal_habitualidade.html",
        ativo="habitualidade",
        cliente_nome=session.get("cliente_nome"),
        cr=cr,
        eventos=eventos,
        tem_cpf=bool(cpf),
    )


def _proximos_campeonatos(hoje=None) -> list:
    """Campeonatos de hoje em diante, já formatados pra exibição (dia,
    mês abreviado, intervalo por extenso, rótulo de contagem regressiva)
    -- datas e contas nunca são feitas no template/IA, sempre aqui em
    Python, o texto final só fraseia o número pronto (mesmo princípio de
    integracoes/shooting_house.py). Compartilhado entre a Home (só o
    próximo) e a tela de Campeonatos (a lista inteira)."""
    hoje = hoje or datetime.now().date()
    eventos = []
    for c in listar_campeonatos():
        data_inicio = datetime.strptime(c["data_inicio"], "%Y-%m-%d").date()
        data_fim = datetime.strptime(c["data_fim"], "%Y-%m-%d").date()
        if data_fim < hoje:
            continue
        dias_ate = (data_inicio - hoje).days
        if dias_ate == 0:
            rotulo = "Hoje"
        elif dias_ate < 0:
            rotulo = "Termina hoje" if data_fim == hoje else "Em andamento"
        elif dias_ate == 1:
            rotulo = "Amanhã"
        elif dias_ate <= 6:
            rotulo = f"Em {dias_ate} dias"
        else:
            rotulo = None

        if data_fim == data_inicio:
            intervalo = f"{data_inicio.day:02d} de {MESES_PT[data_inicio.month - 1]}"
        elif data_inicio.month == data_fim.month:
            intervalo = f"{data_inicio.day:02d} a {data_fim.day:02d} de {MESES_PT[data_inicio.month - 1]}"
        else:
            intervalo = (
                f"{data_inicio.day:02d} de {MESES_PT_ABREV[data_inicio.month - 1]} "
                f"a {data_fim.day:02d} de {MESES_PT_ABREV[data_fim.month - 1]}"
            )
        if data_fim.year != hoje.year or data_inicio.year != hoje.year:
            intervalo += f" de {data_fim.year}"

        eventos.append({
            **c,
            "dia": f"{data_inicio.day:02d}",
            "mes_abrev": MESES_PT_ABREV[data_inicio.month - 1],
            "data_inicio_obj": data_inicio,
            "duracao_dias": (data_fim - data_inicio).days + 1,
            "rotulo_contagem": rotulo,
            "intervalo": intervalo,
        })
    return eventos


def _intervalo_campeonato(c: dict, hoje) -> str:
    """Mesmo formato de texto de _proximos_campeonatos, reaproveitado
    aqui pra manter a data com a mesma cara em qualquer tela do Portal
    que mostre campeonato (calendário, resultados)."""
    data_inicio = datetime.strptime(c["data_inicio"], "%Y-%m-%d").date()
    data_fim = datetime.strptime(c["data_fim"], "%Y-%m-%d").date()
    if data_fim == data_inicio:
        intervalo = f"{data_inicio.day:02d} de {MESES_PT[data_inicio.month - 1]}"
    else:
        intervalo = f"{data_inicio.day:02d} a {data_fim.day:02d} de {MESES_PT[data_inicio.month - 1]}"
    if data_fim.year != hoje.year:
        intervalo += f" de {data_fim.year}"
    return intervalo


def _campeonatos_com_resultado(hoje=None) -> list:
    """Campeonatos já ocorridos que têm classificação cadastrada -- lista
    enxuta (nome/data/local), sem a classificação em si: cada um vira só
    um link pra tela própria de resultado (/portal/resultados/<id>),
    não um bloco inteiro dentro da tela de Campeonatos."""
    hoje = hoje or datetime.now().date()
    resultado = []
    for c in listar_campeonatos():
        data_fim = datetime.strptime(c["data_fim"], "%Y-%m-%d").date()
        if data_fim >= hoje:
            continue
        if not listar_resultados(c["campeonato_id"]):
            continue
        resultado.append({**c, "intervalo": _intervalo_campeonato(c, hoje)})

    resultado.sort(key=lambda c: c["data_inicio"], reverse=True)
    return resultado


@app.route("/portal/campeonatos")
@cliente_login_required
def campeonatos():
    hoje = datetime.now().date()
    eventos = _proximos_campeonatos(hoje)
    proximo = eventos[0] if eventos else None
    restantes = eventos[1:]

    meses_grupos = []
    for ev in restantes:
        chave = (ev["data_inicio_obj"].year, ev["data_inicio_obj"].month)
        if not meses_grupos or meses_grupos[-1]["chave"] != chave:
            nome_mes = MESES_PT[ev["data_inicio_obj"].month - 1]
            rotulo_mes = nome_mes if chave[0] == hoje.year else f"{nome_mes} de {chave[0]}"
            meses_grupos.append({"chave": chave, "nome": rotulo_mes, "eventos": []})
        meses_grupos[-1]["eventos"].append(ev)

    return render_template(
        "portal_campeonatos.html",
        ativo="campeonatos",
        cliente_nome=session.get("cliente_nome"),
        proximo=proximo,
        meses_grupos=meses_grupos,
    )


@app.route("/portal/resultados")
@cliente_login_required
def resultados():
    return render_template(
        "portal_resultados.html",
        ativo="resultados",
        cliente_nome=session.get("cliente_nome"),
        campeonatos_com_resultado=_campeonatos_com_resultado(),
    )


@app.route("/portal/resultados/<campeonato_id>")
@cliente_login_required
def resultado_detalhe(campeonato_id):
    campeonato = obter_campeonato(campeonato_id)
    resultados_lista = listar_resultados(campeonato_id) if campeonato else []
    if not campeonato or not resultados_lista:
        flash("Resultado não encontrado.", "erro")
        return redirect(url_for("resultados"))

    cliente_id = session.get("cliente_id")
    modalidades = []
    for res in resultados_lista:
        res["eh_voce"] = bool(cliente_id) and res["cliente_id"] == cliente_id
        chave = res["modalidade"] or "Geral"
        if not modalidades or modalidades[-1]["nome"] != chave:
            modalidades.append({"nome": chave, "resultados": []})
        modalidades[-1]["resultados"].append(res)

    return render_template(
        "portal_resultado_detalhe.html",
        ativo="resultados",
        cliente_nome=session.get("cliente_nome"),
        campeonato={**campeonato, "intervalo": _intervalo_campeonato(campeonato, datetime.now().date())},
        modalidades=modalidades,
    )


@app.route("/portal/casos/<caso_id>")
@cliente_login_required
def caso_detalhe(caso_id):
    cliente_id = session["cliente_id"]
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row

    # Mesmo princípio de isolamento do resto do Portal: o caso só é
    # encontrado se pertencer a este cliente -- nunca confia no caso_id
    # da URL sozinho.
    linha_caso = con.execute(
        "SELECT caso_id, titulo, descricao, status, categoria "
        "FROM caso WHERE caso_id = ? AND cliente_id = ?",
        (caso_id, cliente_id),
    ).fetchone()
    if not linha_caso:
        con.close()
        flash("Caso não encontrado.", "erro")
        return redirect(url_for("casos_lista"))

    caso = dict(linha_caso)
    caso["status_classe"] = _classe_selo(caso["status"])
    caso["processos"] = _processos_com_checklist(con, caso_id)

    # Documentos que ainda faltam, agrupados por processo -- alimenta o
    # <select> do formulário de envio (o cliente escolhe da lista em vez
    # de escrever de cabeça o nome do documento exigido).
    itens_faltando = []
    for processo in caso["processos"]:
        faltando = [item["item"] for item in processo["checklist"] if not item["recebido"]]
        if faltando:
            itens_faltando.append({"processo_label": processo["nome_servico"], "itens": faltando})

    documentos = con.execute(
        "SELECT documento_id, tipo_documento, nome_arquivo, status, data_envio "
        "FROM documento WHERE cliente_id = ? AND ("
        "  caso_id = ? OR processo_id IN (SELECT processo_id FROM processo WHERE caso_id = ?)"
        ") ORDER BY data_envio DESC",
        (cliente_id, caso_id, caso_id),
    ).fetchall()
    con.close()

    return render_template(
        "portal_caso.html",
        ativo="casos",
        cliente_nome=session.get("cliente_nome"),
        caso=caso,
        itens_faltando=itens_faltando,
        documentos=[dict(d) for d in documentos],
    )


@app.route("/portal/documentos", methods=["POST"])
@cliente_login_required
def upload_documento():
    cliente_id = session["cliente_id"]
    caso_id = (request.form.get("caso_id") or "").strip() or None

    def _voltar():
        if caso_id:
            return redirect(url_for("caso_detalhe", caso_id=caso_id))
        return redirect(url_for("casos_lista"))

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo.", "erro")
        return _voltar()

    extensao = Path(arquivo.filename).suffix.lower()
    if extensao not in DOCUMENTO_EXTENSOES_ACEITAS:
        flash(f"Tipo de arquivo não aceito: {extensao or '(sem extensão)'}.", "erro")
        return _voltar()

    conteudo = arquivo.read()
    if not conteudo:
        flash("Arquivo vazio.", "erro")
        return _voltar()
    if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
        flash("Arquivo maior que 15MB.", "erro")
        return _voltar()

    if not caso_id:
        flash("Selecione a qual caso este documento pertence.", "erro")
        return redirect(url_for("casos_lista"))

    # Nunca confiar no caso_id vindo do formulário sem checar que
    # pertence a este cliente -- ponto central de isolamento de dado do
    # Portal (docs/portal_cliente_arquitetura.md, seção 3). Sem essa
    # checagem, um cliente poderia anexar (ou pior, associar) um
    # documento ao caso de outra pessoa só trocando o ID na requisição.
    # Redirecionar de volta pro caso_id "cru" é seguro mesmo assim:
    # caso_detalhe() faz essa mesma checagem de novo antes de mostrar
    # qualquer coisa.
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    dono = con.execute("SELECT cliente_id FROM caso WHERE caso_id = ?", (caso_id,)).fetchone()
    con.close()
    if not dono or dono["cliente_id"] != cliente_id:
        flash("Caso não encontrado.", "erro")
        return redirect(url_for("casos_lista"))

    # "__outro__" é o valor do <select> quando o documento não está na
    # lista de faltantes (portal_caso.html) -- nesse caso o texto de
    # verdade vem do campo livre que aparece ao lado.
    tipo_documento = (request.form.get("tipo_documento") or "").strip()
    if tipo_documento == "__outro__":
        tipo_documento = (request.form.get("tipo_documento_outro") or "").strip()
    tipo_documento = tipo_documento or "Anexo enviado pelo cliente (Portal)"

    motor_documentos.salvar_documento(
        cliente_id, conteudo, arquivo.filename,
        caso_id=caso_id,
        tipo_documento=tipo_documento,
    )
    flash("Documento enviado.", "sucesso")
    return redirect(url_for("caso_detalhe", caso_id=caso_id))


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
