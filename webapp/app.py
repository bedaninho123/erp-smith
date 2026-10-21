"""Painel administrativo do ERP Smith: status do banco/módulos, testador
do pipeline do Motor IA, e fila de aprovações pendentes. Protegido por
login (usuario.senha_hash). A senha é criada pela própria pessoa, pelo
link do e-mail de convite (core/motor_convite_usuario.py) ou por
webapp/definir_senha.py no terminal.

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
import re
import secrets
import sqlite3
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash

from atendimento.processar import (
    aprovar_mensagem_pendente, entregar_resposta, rejeitar_mensagem_pendente,
)
from core import (
    motor_checklist,
    motor_convite_usuario,
    motor_conversas,
    motor_documentos,
    motor_log_administrativo,
    motor_mensagens,
    motor_tarefas,
)
from core.motor_identidade import mascarar_cpf
from core.conexao import conectar
from core.configuracoes import atualizar_configuracao, obter_configuracoes
from core.limitador_tentativas import excedeu_limite
from core import motor_credenciais, motor_indicadores
from core.motor_casos import (
    CANAIS_ORIGEM, PRIORIDADES_VALIDAS, STATUS_VALIDOS, atualizar_descricao,
    atualizar_responsavel, atualizar_status, criar_caso,
)
from core.motor_notificacoes import destinatario_para_notificar
from core.motor_processos import atualizar_processo, criar_processo
from core.motor_usuarios import (
    FUNCOES_VALIDAS, atualizar_ativo, atualizar_papel, atualizar_permissoes,
    criar_usuario, listar_permissoes, listar_usuarios, tem_permissao,
)
from domain.clube_tiro import (
    documentos_cac, motor_anotacoes_filiado, motor_filiados, motor_indicadores_clube,
    motor_modalidades,
)
from domain.clube_tiro.categorias_marketplace import CATEGORIAS as CATEGORIAS_MARKETPLACE
from domain.clube_tiro.motor_campeonatos import (
    atualizar_campeonato, criar_campeonato, listar_campeonatos, remover_campeonato,
)
from domain.clube_tiro.motor_resultados import (
    atualizar_resultado, criar_resultado, listar_resultados, remover_resultado,
)
from core.motor_clientes import ClienteInvalido, ClienteJaExiste, criar_cliente, informar_cpf
from core.motor_marketplace import (
    AnuncioInvalido, aprovar as aprovar_anuncio, editar_anuncio,
    listar_anuncios, obter_anuncio, recusar as recusar_anuncio,
    remover as remover_anuncio,
)
from integracoes.config import shooting_house_ativo
from integracoes.shooting_house import (
    ShootingHouseIndisponivel,
    completar_arma_via_habitualidade,
    consultar_armas,
    consultar_cadastro,
    consultar_ficha_completa,
    consultar_habitualidade,
)
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
# SameSite=Lax (2026-10-14): sem ele, o Flask manda o cookie sem a
# marcação, e Safari e Firefox o enviam também em POST vindo de OUTRO
# site -- uma página qualquer aberta por quem está logado podia disparar
# ação no painel em nome dela (CSRF). Lax e não Strict: Strict faria
# o link para o painel, aberto de um e-mail, chegar sem login.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
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
    casos deve impedir a mudança de status em si de ter acontecido.

    Nem uma FALHA do Gmail (2026-09-24). Antes, token revogado
    (`invalid_grant`, que já aconteceu) virava HTTP 500 DEPOIS de o
    status estar gravado: o banco mudava, a tela recebia erro em HTML, o
    `r.json()` estourava e ela ficava parada em "Salvando…" mostrando o
    status antigo. Para quem usa, "o status não muda". Mesmo cuidado que
    a recusa de documento já tinha (ver documento_recusar)."""
    try:
        _enviar_notificacao_mudanca_status(empresa_id, caso_id)
    except Exception:
        traceback.print_exc()


def _enviar_notificacao_mudanca_status(empresa_id: str, caso_id: str) -> None:
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
        nome_remetente=config.get("nome_empresa"),
        corpo=(
            f"Olá {destinatario['nome']},\n\n"
            "Houve uma atualização no seu atendimento. Acesse o Portal do "
            "Cliente para ver os detalhes:\n\n"
            f"{PORTAL_URL_BASE}/portal/login\n\n"
            f"{config.get('assinatura_email', f'Equipe {nome_empresa}')}"
        ),
    )


@app.route("/saude")
def saude_sistema():
    """Para o monitor externo (2026-10-14), por isso SEM login: ele não
    tem como entrar. Mostra só o nome de cada parte e se está bem -- nada
    de dado, contagem ou mensagem de erro (erro pode carregar CPF, ver
    _mascarar_cpf em integracoes/shooting_house.py).

    503 quando qualquer parte falha: o monitor gratuito só olha o código
    de resposta. As rotinas de fundo só existem no processo de produção
    (webapp/servir.py); rodando o painel sozinho no PC, e-mail e backup
    viram "atrasado" depois do prazo, e está certo que virem."""
    from core import saude
    from core.conexao import conectar_admin

    estado = saude.avaliar()
    try:
        con = conectar_admin()
        try:
            con.execute("SELECT 1 FROM empresa LIMIT 1").fetchone()
        finally:
            con.close()
        estado["banco"] = "ok"
    except Exception:
        estado["banco"] = "falha"
    bom = all(v in ("ok", "aguardando") for v in estado.values())
    resposta = jsonify(status="ok" if bom else "falha", partes=estado)
    resposta.status_code = 200 if bom else 503
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


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
    aviso = "Senha criada. Agora é só entrar com o seu e-mail e a nova senha." \
        if request.args.get("senha") == "criada" else None
    return render_template("login.html", erro=erro, aviso=aviso)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Senha criada pela própria pessoa, por link no e-mail (2026-10-20) --
# ver core/motor_convite_usuario.py. Convite de usuário novo e "Esqueci
# minha senha" são o mesmo mecanismo.
# ---------------------------------------------------------------------
ESQUECI_MAX_POR_IP = 5
ESQUECI_MAX_POR_EMAIL = 3
ESQUECI_JANELA_SEGUNDOS = 3600


def _url_base_painel() -> str:
    """Endereço do painel para o link do e-mail. Em produção sai da
    configuração (PAINEL_HOST), nunca do cabeçalho da requisição: no
    "Esqueci minha senha" quem faz a requisição pode ser qualquer um, e um
    Host forjado mandaria o link de outra pessoa para um site alheio."""
    configurado = os.environ.get("PAINEL_URL_BASE", "").strip().rstrip("/")
    if configurado:
        return configurado
    host = os.environ.get("PAINEL_HOST", "").strip()
    if host:
        return f"https://{host}"
    return request.url_root.rstrip("/")


def _enviar_link_senha(empresa_id: str, link: dict) -> bool:
    """Manda o e-mail com o link. False quando não deu para mandar
    (Gmail não autorizado nesta máquina, ou falha dele) -- quem chamou
    decide o que fazer, nunca vira erro 500."""
    if not gmail_configurado():
        return False
    config = obter_configuracoes(empresa_id)
    nome_empresa = config.get("nome_empresa", "nosso escritório")
    url = f"{_url_base_painel()}/definir-senha/{link['token']}"
    validade = datetime.strptime(link["expira_em"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).astimezone().strftime("%d/%m às %H:%M")
    if link["motivo"] == motor_convite_usuario.MOTIVO_CONVITE:
        assunto = f"Seu acesso ao painel -- {nome_empresa}"
        abertura = (f"Você foi cadastrado(a) no painel de {nome_empresa}. "
                    "Para entrar, crie a sua senha neste link:")
    else:
        assunto = f"Nova senha do painel -- {nome_empresa}"
        abertura = "Recebemos um pedido para criar uma nova senha do painel. Use este link:"
    try:
        enviar_email(
            destinatario=link["email"],
            assunto=assunto,
            nome_remetente=config.get("nome_empresa"),
            corpo=(
                f"Olá {link['nome']},\n\n{abertura}\n\n{url}\n\n"
                f"O link vale até {validade} e funciona uma vez só. "
                "Se você não esperava este e-mail, pode ignorá-lo: "
                "nada muda sem que alguém abra o link.\n\n"
                f"{config.get('assinatura_email', f'Equipe {nome_empresa}')}"
            ),
        )
        return True
    except Exception:
        traceback.print_exc()
        return False


@app.route("/definir-senha/<token>")
def definir_senha_link(token):
    """Tira o link da barra de endereço logo na chegada: guarda na sessão
    e redireciona. Assim ele não fica no histórico do navegador nem vai no
    Referer de nada que a página carregar."""
    session["token_senha"] = token
    return redirect(url_for("definir_senha_tela"))


@app.route("/definir-senha", methods=["GET", "POST"])
def definir_senha_tela():
    token = session.get("token_senha") or ""
    dados = motor_convite_usuario.conferir_link(token) if token else None
    if not dados:
        session.pop("token_senha", None)
        return render_template("definir_senha.html", invalido=True)

    erro = None
    if request.method == "POST":
        if excedeu_limite(f"definir_senha:{request.remote_addr}", LOGIN_MAX_TENTATIVAS, LOGIN_JANELA_SEGUNDOS):
            erro = "Muitas tentativas. Aguarde alguns minutos e tente novamente."
        elif (request.form.get("senha") or "") != (request.form.get("confirmacao") or ""):
            erro = "As duas senhas não são iguais."
        else:
            try:
                motor_convite_usuario.definir_senha(token, request.form.get("senha") or "")
            except ValueError as e:
                erro = str(e)
            else:
                session.pop("token_senha", None)
                return redirect(url_for("login", senha="criada"))
    return render_template("definir_senha.html", nome=dados["nome"], email=dados["email"], erro=erro)


@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "GET":
        return render_template("esqueci_senha.html")

    email = (request.form.get("email") or "").strip().lower()
    # Mesma resposta para tudo: cadastrado ou não, enviado ou não, limite
    # estourado ou não. Qualquer diferença transformaria esta tela num
    # jeito de descobrir quem tem acesso ao painel.
    estourou = (
        excedeu_limite(f"esqueci_senha_ip:{request.remote_addr}", ESQUECI_MAX_POR_IP, ESQUECI_JANELA_SEGUNDOS)
        or excedeu_limite(f"esqueci_senha_email:{email}", ESQUECI_MAX_POR_EMAIL, ESQUECI_JANELA_SEGUNDOS)
    )
    usuario = None if estourou or "@" not in email else motor_convite_usuario.usuario_para_redefinir(email)
    if usuario:
        try:
            link = motor_convite_usuario.criar_link(
                usuario["empresa_id"], usuario["usuario_id"],
                motor_convite_usuario.MOTIVO_REDEFINICAO,
                pedido_por="Esqueci minha senha (tela de login)",
                pela_tela_de_login=True,
            )
            _enviar_link_senha(usuario["empresa_id"], link)
        except Exception:
            traceback.print_exc()
    return render_template("esqueci_senha.html", enviado=True)


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
        categorias_marketplace=CATEGORIAS_MARKETPLACE,
    )


def _pode(funcao: str) -> bool:
    """Gestor sempre pode; Atendente depende do catálogo. Mesma decisão
    de funcao_required, mas usável DENTRO de uma rota -- a tela inicial
    junta blocos de várias telas, e cada bloco tem que sumir sozinho pra
    quem não tem aquela função."""
    if session.get("papel") == "Gestor":
        return True
    return tem_permissao(empresa_atual(), session.get("usuario_id"), funcao)


@app.route("/api/inicio")
@login_required
@funcao_required(
    "casos", "tarefas", "atendimentos", "aprovacoes_pendentes", "documentos_aprovar",
)
def inicio():
    """Tela inicial: o que precisa de atenção hoje.

    O decorator aceita as cinco funções porque a tela é um resumo de
    cinco telas -- quem tem qualquer uma delas tem o que ver aqui. Mas
    ele passar não basta: como funcao_required libera se QUALQUER função
    bater, cada bloco abaixo é conferido de novo com _pode(). Sem isso,
    um Atendente com só "casos" ligado receberia a fila de aprovações
    pendentes de brinde.
    """
    empresa_id = empresa_atual()
    resumo: dict = {}

    if _pode("tarefas"):
        resumo["tarefas"] = motor_tarefas.contar_tarefas(empresa_id)
        # Só as cinco primeiras: a tela inicial é um lugar de decidir
        # pra onde ir, não de trabalhar. A lista inteira mora em Tarefas.
        resumo["tarefas"]["proximas"] = motor_tarefas.listar_tarefas(
            empresa_id, somente_abertas=True,
        )[:5]

    if _pode("aprovacoes_pendentes"):
        resumo["aprovacoes_pendentes"] = len(motor_mensagens.listar_pendentes(empresa_id))

    if _pode("documentos_aprovar"):
        resumo["documentos_a_conferir"] = len(motor_checklist.listar_pendentes(empresa_id))

    if _pode("atendimentos"):
        resumo["conversas_abertas"] = len(
            motor_conversas.listar_conversas(empresa_id, status=motor_conversas.STATUS_ABERTA)
        )

    if _pode("casos"):
        con = conectar(empresa_id)
        # "Parado" é caso vivo sem nenhuma atualização há 7 dias. A tela
        # de Casos promete mostrar "o que está parado" desde sempre, mas
        # ordenada por data ela mostra o que é RECENTE -- o que está
        # parado fica no fim da lista, que é onde ninguém olha.
        # Em UTC, como todo criado_em/atualizado_em do projeto -- comparar
        # com hora local aqui deslocaria a régua em 3 horas.
        limite_parado = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        parados = [
            dict(r) for r in con.execute(
                "SELECT c.caso_id, c.titulo, c.status, c.atualizado_em, "
                "cl.nome AS cliente_nome FROM caso c "
                "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = c.empresa_id "
                "WHERE c.empresa_id = ? AND c.ativo = 'Sim' "
                "AND c.status NOT IN ('Encerrado', 'Cancelado') AND c.atualizado_em < ? "
                "ORDER BY c.atualizado_em",
                (empresa_id, limite_parado),
            ).fetchall()
        ]
        abertos = con.execute(
            "SELECT COUNT(*) FROM caso WHERE empresa_id = ? AND ativo = 'Sim' "
            "AND status NOT IN ('Encerrado', 'Cancelado')",
            (empresa_id,),
        ).fetchone()[0]
        con.close()
        resumo["casos"] = {
            "abertos": abertos,
            "parados": len(parados),
            "lista_parados": parados[:5],
            "dias_parado": 7,
        }

    return jsonify(resumo)


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

    # "configurado" aqui significa MODO REAL LIGADO, não "tem credencial
    # no .env" -- os dois deixaram de ser a mesma coisa quando a chave
    # geral SHOOTING_HOUSE_ATIVO passou a existir (2026-08-25). Credencial
    # guardada com a chave desligada aparece como não configurado de
    # propósito: o que a tela precisa responder é "esta consulta está
    # trazendo dado real de pessoa?", e nesse caso a resposta é não.
    integracoes = [
        {"nome": "Shooting House (dado real de atirador)", "configurado": shooting_house_ativo()},
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
    busca = (request.args.get("busca") or "").strip()

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
    if busca:
        # Uma caixa só, e não três. Quem procura já sabe o que tem na mão
        # -- o nome, o CPF ou o número do caso -- e não deveria ter que
        # acertar em qual campo digitar. Os três viram OR.
        condicoes = ["cl.nome LIKE ?", "c.caso_id LIKE ?"]
        params_busca = [f"%{busca}%", f"%{busca}%"]
        # `caso_id` é CAS-000012, então digitar só "12" encontra -- o LIKE
        # do SQLite já ignora maiúscula em ASCII, então "cas-12" também.
        digitos = re.sub(r"\D", "", busca)
        # A coluna guarda só dígitos (a tela é que formata), então o CPF
        # digitado com ponto e traço precisa ser limpo antes de comparar.
        # Menos de 3 dígitos não entra: "12" casaria com quase todo CPF e
        # encheria o resultado de gente que não tem nada a ver com a busca.
        if len(digitos) >= 3:
            condicoes.append("cl.cpf LIKE ?")
            params_busca.append(f"%{digitos}%")
        query += " AND (" + " OR ".join(condicoes) + ")"
        params.extend(params_busca)
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


@app.route("/api/casos", methods=["POST"])
@login_required
@funcao_required("casos")
def caso_criar():
    """Abre um caso à mão -- cliente ligou, apareceu na porta, mandou
    mensagem por fora. Até aqui todo caso nascia da IA ou da migração, e
    não havia como o despachante abrir um.

    Usa o MESMO `criar_caso` do orquestrador: duas formas de um caso
    nascer, com regras diferentes, seria a primeira divergência a
    aparecer no histórico.
    """
    corpo = request.get_json(force=True)
    cliente_id = (corpo.get("cliente_id") or "").strip()
    if not cliente_id:
        return jsonify(erro="Selecione o cliente."), 400

    canal = (corpo.get("canal_origem") or "Email").strip()
    if canal not in CANAIS_ORIGEM:
        return jsonify(erro=f"Canal inválido: {canal}."), 400

    try:
        novo_id = criar_caso(
            empresa_atual(),
            cliente_id,
            titulo=corpo.get("titulo"),
            categoria=corpo.get("categoria"),
            descricao=(corpo.get("descricao") or "").strip() or None,
            prioridade=(corpo.get("prioridade") or "Normal").strip(),
            canal_origem=canal,
            responsavel_id=(corpo.get("responsavel_id") or "").strip() or None,
            origem="Painel",
            criado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, caso_id=novo_id)


@app.route("/api/casos/novo")
@login_required
@funcao_required("casos")
def caso_novo_opcoes():
    """O que o formulário de novo caso precisa para desenhar.

    A lista oferecida é a de SERVIÇOS da empresa -- o nome do trabalho
    que vai ser feito ("Renovação do CR"), não o balde em que ele cai.
    Até 2026-08-27 aqui vinha `SELECT DISTINCT categoria`, e como quatro
    dos sete serviços moram em "Regularização documental", quem abria um
    caso não achava na lista nem "Primeiro CR" nem "Renovação do CR":
    escolhia um agrupamento abstrato em vez de dizer o que ia fazer.

    Continua saindo do catálogo, e não de uma lista fixa no código: é o
    mesmo vocabulário que o checklist e os processos já usam, e uma
    lista à parte divergiria na primeira vez que alguém cadastrasse um
    serviço novo.
    """
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    clientes = [
        dict(r) for r in con.execute(
            "SELECT cliente_id, nome, cpf FROM cliente WHERE empresa_id = ? "
            "AND status = 'Ativo' ORDER BY nome COLLATE NOCASE", (empresa_id,),
        ).fetchall()
    ]
    servicos = [
        r[0] for r in con.execute(
            "SELECT nome_servico FROM servico WHERE empresa_id = ? AND ativo = 'Sim' "
            "ORDER BY nome_servico COLLATE NOCASE", (empresa_id,),
        ).fetchall()
    ]
    usuarios = [
        dict(r) for r in con.execute(
            "SELECT usuario_id, nome FROM usuario WHERE empresa_id = ? AND ativo = 'Sim' "
            "ORDER BY nome", (empresa_id,),
        ).fetchall()
    ]
    con.close()

    return jsonify(
        clientes=clientes,
        servicos=servicos,
        usuarios=usuarios,
        prioridades=list(PRIORIDADES_VALIDAS),
        canais=list(CANAIS_ORIGEM),
        # Cadastrar cliente é outra função do catálogo, e a tela de abrir
        # caso é alcançável por quem só tem "casos". Sem isto o formulário
        # de cliente novo apareceria para essa pessoa e só falharia com
        # 403 depois de ela digitar tudo -- a rota continua sendo a trava
        # de verdade, isto é só não prometer o que não vai cumprir.
        pode_cadastrar_cliente=_pode("clientes"),
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

    # Catálogo completo de tipo de documento -- todo item de checklist de
    # todo serviço da empresa, sem repetir. Alimenta a sugestão de "Tipo
    # de documento" quando o envio manual NÃO está ligado a um processo
    # específico: sem processo pra apontar qual checklist usar, a
    # despachante ainda precisa poder guardar qualquer documento do
    # cliente (um CR antigo, por exemplo), então a lista vira "tudo que
    # já é exigido por algum serviço" em vez de nada.
    catalogo_documentos = con.execute(
        "SELECT DISTINCT item FROM documento_exigido WHERE empresa_id = ? "
        "AND ativo = 'Sim' AND processo_id IS NULL ORDER BY item", (empresa_id,),
    ).fetchall()

    con.close()

    # Fora da conexão de cima de propósito: listar_tarefas abre a própria
    # (é ela que sabe calcular atraso com a data local, ver o motor).
    tarefas = motor_tarefas.listar_tarefas(empresa_id, caso_id=caso_id)

    return jsonify(
        caso=dict(caso),
        processos=processos_list,
        documentos=[dict(r) for r in documentos],
        historico=[dict(r) for r in historico],
        mensagens=[dict(r) for r in mensagens],
        tarefas=tarefas,
        status_validos=sorted(STATUS_VALIDOS),
        tarefa_status_validos=list(motor_tarefas.STATUS_VALIDOS),
        tarefa_prioridades=list(motor_tarefas.PRIORIDADES_VALIDAS),
        tarefa_tipos_sugeridos=list(motor_tarefas.TIPOS_SUGERIDOS),
        usuarios=[dict(r) for r in usuarios],
        servicos=[dict(r) for r in servicos],
        catalogo_documentos=[r["item"] for r in catalogo_documentos],
        # Botão "Ver filiado" (2026-09-24): só o CPF, e só se a pessoa
        # passou pelo clube E quem está logado pode abrir a tela de
        # Filiados -- sem a segunda condição o botão levaria a um 403.
        filiado_cpf=(
            caso["cliente_cpf"]
            if _pode("habitualidade")
            and motor_filiados.obter_por_cpf(empresa_id, caso["cliente_cpf"])
            else None
        ),
        pode_ver_cliente=_pode("clientes"),
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


# ---------------------------------------------------------------------
# Tarefas e prazos
#
# A criação/edição/conclusão aceita as duas funções porque a tarefa é
# alcançável de dois lugares: da tela Tarefas e de dentro da ficha do
# Caso. Travar só em "tarefas" tiraria o bloco de tarefas da ficha do
# Caso de quem tem só a função de casos ligada -- mesma situação já
# documentada em funcao_required (campeonatos x resultados).
# ---------------------------------------------------------------------

@app.route("/api/tarefas")
@login_required
@funcao_required("tarefas")
def tarefas_lista():
    empresa_id = empresa_atual()
    tarefas = motor_tarefas.listar_tarefas(
        empresa_id,
        status=request.args.get("status") or None,
        responsavel_id=request.args.get("responsavel_id") or None,
        vencimento=request.args.get("vencimento") or None,
        somente_abertas=request.args.get("somente_abertas") == "1",
    )

    con = conectar(empresa_id)
    # Só caso ainda vivo alimenta o seletor de "nova tarefa": abrir
    # tarefa em caso encerrado é quase sempre engano, e a lista fica
    # utilizável (o piloto já tem centenas de casos fechados).
    casos_abertos = [
        dict(r) for r in con.execute(
            "SELECT c.caso_id, c.titulo, cl.nome AS cliente_nome FROM caso c "
            "JOIN cliente cl ON cl.cliente_id = c.cliente_id AND cl.empresa_id = c.empresa_id "
            "WHERE c.empresa_id = ? AND c.ativo = 'Sim' "
            "AND c.status NOT IN ('Encerrado', 'Cancelado') "
            "ORDER BY c.atualizado_em DESC",
            (empresa_id,),
        ).fetchall()
    ]
    usuarios = [
        dict(r) for r in con.execute(
            "SELECT usuario_id, nome FROM usuario WHERE ativo = 'Sim' AND empresa_id = ? "
            "ORDER BY nome", (empresa_id,),
        ).fetchall()
    ]
    con.close()

    return jsonify(
        tarefas=tarefas,
        contagem=motor_tarefas.contar_tarefas(empresa_id),
        casos_abertos=casos_abertos,
        usuarios=usuarios,
        status_validos=list(motor_tarefas.STATUS_VALIDOS),
        prioridades_validas=list(motor_tarefas.PRIORIDADES_VALIDAS),
        tipos_sugeridos=list(motor_tarefas.TIPOS_SUGERIDOS),
        hoje=motor_tarefas.hoje_local(),
    )


@app.route("/api/tarefas", methods=["POST"])
@login_required
@funcao_required("tarefas", "casos")
def tarefa_criar():
    corpo = request.get_json(force=True)
    caso_id = (corpo.get("caso_id") or "").strip()
    if not caso_id:
        return jsonify(erro="Selecione o caso da tarefa."), 400
    try:
        novo_id = motor_tarefas.criar_tarefa(
            empresa_atual(),
            caso_id,
            tipo=(corpo.get("tipo") or "").strip(),
            descricao=(corpo.get("descricao") or "").strip() or None,
            responsavel_id=(corpo.get("responsavel_id") or "").strip() or None,
            prazo=(corpo.get("prazo") or "").strip() or None,
            prioridade=(corpo.get("prioridade") or "Normal").strip(),
            processo_id=(corpo.get("processo_id") or "").strip() or None,
            observacoes=(corpo.get("observacoes") or "").strip() or None,
            criado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, tarefa_id=novo_id)


@app.route("/api/tarefas/<tarefa_id>", methods=["POST"])
@login_required
@funcao_required("tarefas", "casos")
def tarefa_atualizar(tarefa_id):
    corpo = request.get_json(force=True)
    try:
        motor_tarefas.atualizar_tarefa(
            empresa_atual(),
            tarefa_id,
            tipo=(corpo.get("tipo") or "").strip(),
            descricao=(corpo.get("descricao") or "").strip() or None,
            responsavel_id=(corpo.get("responsavel_id") or "").strip() or None,
            prazo=(corpo.get("prazo") or "").strip() or None,
            prioridade=(corpo.get("prioridade") or "Normal").strip(),
            status=(corpo.get("status") or "").strip(),
            observacoes=(corpo.get("observacoes") or "").strip() or None,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/tarefas/<tarefa_id>/concluir", methods=["POST"])
@login_required
@funcao_required("tarefas", "casos")
def tarefa_concluir(tarefa_id):
    try:
        motor_tarefas.concluir_tarefa(
            empresa_atual(), tarefa_id,
            alterado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
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


@app.route("/api/processos/<processo_id>/checklist/itens", methods=["POST"])
@login_required
@funcao_required("casos")
def checklist_adicionar_item(processo_id):
    """Mais um item igual a um existente, só neste processo -- a segunda
    capacidade técnica de quem tem pistola e carabina."""
    corpo = request.get_json(force=True) or {}
    try:
        novo_id = motor_checklist.adicionar_item_extra(
            empresa_atual(), processo_id,
            (corpo.get("documento_exigido_id") or "").strip(),
            complemento=corpo.get("complemento") or "",
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_exigido_id=novo_id)


@app.route("/api/processos/<processo_id>/checklist/itens/<documento_exigido_id>/remover", methods=["POST"])
@login_required
@funcao_required("casos")
def checklist_remover_item(processo_id, documento_exigido_id):
    try:
        motor_checklist.remover_item_extra(empresa_atual(), processo_id, documento_exigido_id)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


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
        nome_remetente=config.get("nome_empresa"),
        corpo=(
            f"Olá {destinatario['nome']},\n\n"
            f"O documento enviado para \"{item}\" não pôde ser aceito. "
            "Acesse o Portal do Cliente para ver o motivo e enviar outro "
            "arquivo:\n\n"
            f"{PORTAL_URL_BASE}/portal/login\n\n"
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


@app.route("/api/marketplace")
@login_required
@funcao_required("marketplace")
def marketplace_listar():
    """Fila de moderação do Marketplace -- filtro por status vem da
    query string; sem filtro, devolve todos (Pendente primeiro, é o que
    a tela usa por padrão)."""
    status = request.args.get("status") or None
    return jsonify(listar_anuncios(empresa_atual(), status=status))


@app.route("/api/marketplace/<anuncio_id>/editar", methods=["POST"])
@login_required
@funcao_required("marketplace")
def marketplace_editar(anuncio_id):
    """Correção de texto/preço/contato -- não mexe em status (ver
    editar_anuncio)."""
    corpo = request.get_json(force=True)
    try:
        editar_anuncio(
            empresa_atual(), anuncio_id,
            categoria=corpo.get("categoria", ""),
            titulo=corpo.get("titulo", ""),
            descricao=corpo.get("descricao"),
            valor=corpo.get("valor"),
            contato_telefone=corpo.get("contato_telefone"),
            contato_email=corpo.get("contato_email"),
        )
    except AnuncioInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/marketplace/<anuncio_id>/aprovar", methods=["POST"])
@login_required
@funcao_required("marketplace")
def marketplace_aprovar(anuncio_id):
    try:
        aprovar_anuncio(empresa_atual(), anuncio_id, revisado_por=session.get("usuario_nome", "Painel administrativo"))
    except AnuncioInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/marketplace/<anuncio_id>/recusar", methods=["POST"])
@login_required
@funcao_required("marketplace")
def marketplace_recusar(anuncio_id):
    corpo = request.get_json(force=True)
    motivo = (corpo.get("motivo") or "").strip()
    try:
        recusar_anuncio(
            empresa_atual(), anuncio_id, motivo,
            revisado_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except AnuncioInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/marketplace/<anuncio_id>/remover", methods=["POST"])
@login_required
@funcao_required("marketplace")
def marketplace_remover_painel(anuncio_id):
    try:
        remover_anuncio(empresa_atual(), anuncio_id)
    except AnuncioInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/marketplace/<anuncio_id>/foto/<int:indice>")
@login_required
@funcao_required("marketplace")
def marketplace_foto_painel(anuncio_id, indice):
    """Sem checagem de status -- quem modera precisa ver a foto de um
    anúncio ainda Pendente, que é justamente o que está decidindo."""
    anuncio = obter_anuncio(empresa_atual(), anuncio_id)
    if not anuncio or indice < 0 or indice >= len(anuncio["fotos"]):
        return jsonify(erro="Foto não encontrada."), 404
    caminho = Path(anuncio["fotos"][indice])
    if not caminho.is_file():
        return jsonify(erro="Arquivo não encontrado no disco."), 404
    return send_file(caminho)


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
    # Enviado pelo próprio checklist (2026-10-20): o arquivo já nasce
    # marcado no item. Antes, enviar e marcar eram dois gestos em duas
    # abas, e o item seguia "faltando" no Portal até alguém lembrar do
    # segundo.
    documento_exigido_id = (request.form.get("documento_exigido_id") or "").strip() or None

    # Tudo conferido ANTES de gravar o arquivo: descobrir depois deixaria
    # um arquivo solto no caso.
    if processo_id:
        con = conectar(empresa_id)
        do_caso = con.execute(
            "SELECT 1 FROM processo WHERE processo_id = ? AND caso_id = ? AND empresa_id = ?",
            (processo_id, caso_id, empresa_id),
        ).fetchone()
        con.close()
        if not do_caso:
            return jsonify(erro="Este processo não é deste caso."), 400
        if documento_exigido_id:
            try:
                motor_checklist.conferir_item(empresa_id, processo_id, documento_exigido_id)
            except ValueError as e:
                return jsonify(erro=str(e)), 400
    elif documento_exigido_id:
        return jsonify(erro="Item de checklist sem processo."), 400

    try:
        documento_id = motor_documentos.salvar_documento(
            empresa_id, caso["cliente_id"], conteudo, arquivo.filename,
            caso_id=caso_id, processo_id=processo_id,
            tipo_documento=tipo_documento, observacoes=observacoes,
        )
        if documento_exigido_id:
            motor_checklist.marcar_documento(
                empresa_id, processo_id, documento_exigido_id, documento_id,
                marcado_por=session.get("usuario_nome", "Painel administrativo"),
            )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_id=documento_id)


@app.route("/api/documentos/<documento_id>/excluir", methods=["POST"])
@login_required
@funcao_required("casos")
def documento_excluir(documento_id):
    """Exclui um documento de CASO -- mesma função ("casos") que já
    protege o upload em documento_upload() acima; quem pode anexar pode
    tirar o que anexou errado. Dossiê tem sua própria rota
    (dossie_remover), guardada por "clientes"."""
    empresa_id = empresa_atual()
    try:
        caso_id = motor_documentos.excluir_de_caso(
            empresa_id, documento_id, excluido_por=session.get("usuario_nome", "Painel administrativo"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 404
    return jsonify(ok=True, caso_id=caso_id)


@app.route("/api/clientes/<cliente_id>/dossie")
@login_required
@funcao_required("clientes")
def dossie_listar(cliente_id):
    """O dossiê permanente do cliente, mais o catálogo de tipos.

    O catálogo vem junto na mesma resposta porque a tela precisa dos dois
    para desenhar (lista + formulário), e são dois dados pequenos -- uma
    segunda chamada só para pegar 19 nomes seria round-trip à toa.
    """
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    dono = con.execute(
        "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()
    con.close()
    if not dono:
        return jsonify(erro=f"Cliente não encontrado: {cliente_id}"), 404

    return jsonify(
        documentos=motor_documentos.listar_dossie(empresa_id, cliente_id),
        catalogo=documentos_cac.catalogo(),
        dias_alerta=documentos_cac.DIAS_ALERTA_VALIDADE,
        finalidades_arma=list(documentos_cac.FINALIDADES_ARMA),
    )


@app.route("/api/clientes/<cliente_id>/dossie", methods=["POST"])
@login_required
@funcao_required("clientes")
def dossie_enviar(cliente_id):
    """Sobe um documento permanente para o dossiê da pessoa."""
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(erro="Selecione um arquivo."), 400

    conteudo = arquivo.read()
    if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
        return jsonify(erro="Arquivo maior que 15MB."), 400

    try:
        documento_id = motor_documentos.salvar_no_dossie(
            empresa_atual(),
            cliente_id,
            conteudo,
            arquivo.filename,
            tipo_documento=(request.form.get("tipo_documento") or "").strip(),
            data_validade=(request.form.get("data_validade") or "").strip() or None,
            referencia=(request.form.get("referencia") or "").strip() or None,
            finalidade=(request.form.get("finalidade") or "").strip() or None,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_id=documento_id)


@app.route("/api/dossie/<documento_id>/remover", methods=["POST"])
@login_required
@funcao_required("clientes", "habitualidade")
def dossie_remover(documento_id):
    """Tira um documento do dossiê -- linha e arquivo.

    Só documento de DOSSIÊ sai por aqui. Documento de caso tem outro
    caminho e outras consequências (checklist marcado, histórico do
    processo), e deixar uma rota apagar os dois seria convidar ao
    engano.
    """
    empresa_id = empresa_atual()
    documento = motor_documentos.obter_documento(empresa_id, documento_id)
    if not documento or documento["categoria"] != motor_documentos.CATEGORIA_DOSSIE:
        return jsonify(erro="Documento não encontrado no dossiê."), 404

    con = conectar(empresa_id)
    con.execute(
        "DELETE FROM documento WHERE documento_id = ? AND empresa_id = ?",
        (documento_id, empresa_id),
    )
    con.commit()
    con.close()

    caminho = documento.get("link_arquivo")
    if caminho and os.path.exists(caminho):
        try:
            os.remove(caminho)
        except OSError:
            # Arquivo que não sai não desfaz a remoção do banco -- vira
            # órfão, e core.db.auditar_documentos denuncia depois.
            traceback.print_exc()
    return jsonify(ok=True)


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

    # A outra metade da pessoa: se este CPF também é filiado do clube, a
    # ficha mostra o que o clube sabe dele. Sem isto, o atendente teria
    # que sair da ficha e procurar o mesmo CPF na tela de Filiados.
    #
    # Vem do RETRATO sincronizado, não de consulta ao vivo -- por isso a
    # tela mostra `sincronizado_em` junto. Pergunta de cliente sobre a
    # própria habitualidade continua sendo respondida ao vivo, como o
    # Portal já faz.
    filiado = motor_filiados.obter_por_cpf(empresa_id, cliente["cpf"])

    return jsonify(
        cliente=dict(cliente),
        casos=[dict(r) for r in casos],
        documentos=lista_documentos,
        filiado=filiado,
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
    empresa_id = empresa_atual()
    pendentes = motor_convite_usuario.convites_pendentes(empresa_id)
    usuarios = listar_usuarios(empresa_id)
    for u in usuarios:
        u["convite_valido_ate"] = pendentes.get(u["usuario_id"])
    return jsonify(usuarios)


def _mandar_convite(empresa_id: str, usuario_id: str, motivo: str) -> dict:
    """Cria o link e tenta mandar. Se o e-mail não sair, o link volta
    para a tela: o Gestor copia e entrega por outro caminho, em vez de a
    pessoa ficar sem como entrar. Ele vê o LINK, nunca a senha -- quem
    escolhe a senha continua sendo a pessoa."""
    link = motor_convite_usuario.criar_link(
        empresa_id, usuario_id, motivo,
        pedido_por=session.get("usuario_nome", "Painel administrativo"),
    )
    if _enviar_link_senha(empresa_id, link):
        return {"convite_enviado": True, "email": link["email"]}
    return {
        "convite_enviado": False, "email": link["email"],
        "link": f"{_url_base_painel()}/definir-senha/{link['token']}",
    }


@app.route("/api/usuarios", methods=["POST"])
@login_required
@gestor_required
def usuarios_criar():
    corpo = request.get_json(force=True)
    empresa_id = empresa_atual()
    try:
        usuario = criar_usuario(
            empresa_id, corpo.get("nome"), corpo.get("email"), corpo.get("papel"),
        )
        usuario.update(_mandar_convite(empresa_id, usuario["usuario_id"], motor_convite_usuario.MOTIVO_CONVITE))
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(usuario), 201


@app.route("/api/usuarios/<usuario_id>/convite", methods=["POST"])
@login_required
@gestor_required
def usuarios_reenviar_convite(usuario_id):
    """Reenviar o convite (quem ainda não criou senha) ou mandar o link de
    nova senha (quem esqueceu). Pode ser para si mesmo: não muda papel nem
    acesso, só deixa a própria pessoa trocar a senha."""
    empresa_id = empresa_atual()
    ja_tem_senha = any(
        u["usuario_id"] == usuario_id and u["login_configurado"] for u in listar_usuarios(empresa_id)
    )
    motivo = motor_convite_usuario.MOTIVO_REDEFINICAO if ja_tem_senha else motor_convite_usuario.MOTIVO_CONVITE
    try:
        return jsonify(_mandar_convite(empresa_id, usuario_id, motivo))
    except ValueError as e:
        return jsonify(erro=str(e)), 400


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


@app.route("/api/dashboard")
@login_required
@gestor_required
def dashboard():
    """Dashboard do dono: os números do negócio e do clube.

    @gestor_required, sem entrada no catálogo de permissões -- mesma
    decisão de Configurações e Auditoria. Não é uma tela operacional com
    acesso mais largo: é a visão de faturamento, produtividade e evasão
    do clube. Atendente não vê, e não existe toggle que faça ver.

    A tela junta Core (casos, processos, mensagens, IA) e Domínio
    (filiados, habitualidade). É o único lugar do painel que cruza os
    dois de propósito: os dois motores continuam sem saber um do outro,
    e quem junta é esta rota.
    """
    empresa_id = empresa_atual()

    negocio = motor_indicadores.resumo(empresa_id)
    clube = motor_indicadores_clube.resumo(empresa_id)

    # Penetração: quantos filiados do clube também são clientes do
    # despachante. O cruzamento é por CPF e em Python, trazendo o lado
    # pequeno inteiro -- mesma escolha da tela de Filiados (uma consulta
    # por linha em 1500 filiados, ou um IN com 1500 parâmetros, seriam os
    # dois caminhos errados).
    cpfs_clientes = set(_clientes_por_cpf(empresa_id))
    cpfs_filiados = motor_filiados.cpfs_de_filiados(empresa_id, somente_ativos=True)
    tambem_clientes = len(cpfs_filiados & cpfs_clientes)

    return jsonify(
        negocio=negocio,
        clube=clube,
        penetracao={
            "filiados": len(cpfs_filiados),
            "tambem_clientes": tambem_clientes,
            "so_filiados": len(cpfs_filiados) - tambem_clientes,
        },
        habitualidade_dia=motor_indicadores_clube.serie_por_dia(empresa_id),
        habitualidade_mes=motor_indicadores_clube.serie_por_mes(empresa_id),
        # Pela data REAL de filiação (affiliationDate da API), não mais
        # por "quando o sistema viu a pessoa" -- a ressalva que a tela
        # carregava desde ontem deixou de existir.
        novos_filiados=motor_indicadores_clube.filiacoes_por_mes(empresa_id),
        financeiro=motor_indicadores_clube.financeiro(empresa_id),
        tarefas=motor_tarefas.contar_tarefas(empresa_id),
        # A tela precisa saber se o freio está ligado para escrever a
        # frase certa sobre autonomia da IA -- com revisão humana ligada,
        # "resolveu sozinha" ainda passou pela aprovação de alguém.
        revisao_humana_ativa=obter_configuracoes(empresa_id).get("revisao_humana_ativa") == "Sim",
        shooting_house_real=shooting_house_ativo(),
    )


@app.route("/api/auditoria")
@login_required
@gestor_required
def auditoria():
    """Tela Auditoria: só leitura, só Gestor.

    @gestor_required e não @funcao_required: é área administrativa, como
    Configurações e gestão de usuário -- não entra no catálogo de
    permissões de propósito (CLAUDE.md). Um Atendente poder ver, e ainda
    mais poder ganhar/perder essa visão por um toggle, esvaziaria o
    sentido do registro.
    """
    empresa_id = empresa_atual()
    limite = min(int(request.args.get("limite") or 200), 1000)

    registros = motor_log_administrativo.listar(
        empresa_id,
        limite=limite,
        tipo_evento=request.args.get("tipo_evento") or None,
        busca=(request.args.get("busca") or "").strip() or None,
    )

    # Nome de gente no lugar de USR-000003 e CLI-000012. O log guarda o
    # ID de propósito (nome muda, ID não), mas uma tela de auditoria que
    # exige decorar identificador não vai ser lida por ninguém. A
    # tradução é só de exibição -- o ID continua ali, ao lado.
    con = conectar(empresa_id)
    nomes = {
        r["usuario_id"]: r["nome"] for r in con.execute(
            "SELECT usuario_id, nome FROM usuario WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
    }
    nomes.update({
        r["cliente_id"]: r["nome"] for r in con.execute(
            "SELECT cliente_id, nome FROM cliente WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
    })
    chaves_config = {
        r["config_id"]: r["chave"] for r in con.execute(
            "SELECT config_id, chave FROM configuracoes WHERE empresa_id = ?", (empresa_id,)
        ).fetchall()
    }
    con.close()

    for registro in registros:
        registro["alvo_nome"] = nomes.get(registro["alvo"]) or chaves_config.get(registro["alvo"])
        registro["criado_por_nome"] = nomes.get(registro["criado_por"])

    return jsonify(
        registros=registros,
        tipos=motor_log_administrativo.tipos_registrados(empresa_id),
        acessos_negados_7d=motor_log_administrativo.contar_acessos_negados(empresa_id, dias=7),
        limite=limite,
    )


@app.route("/api/modalidades")
@login_required
@funcao_required("campeonatos", "resultados")
def modalidades():
    """Catálogo de modalidades do clube, espelhado do Shooting House.

    Duas funções no decorator porque a tela de Resultados também usa esta
    rota (é dela que sai a lista de sugestões de modalidade) -- mesma
    situação já documentada em funcao_required para /api/campeonatos.

    Não entra no catálogo de permissões como função própria: é dado de
    referência das duas telas que já existem, não uma área nova.
    """
    return jsonify(
        motor_modalidades.agrupado(
            empresa_atual(), busca=(request.args.get("busca") or "").strip() or None
        )
    )


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


def _clientes_por_cpf(empresa_id: str) -> dict:
    """{cpf: cliente_id} dos clientes do despachante desta empresa.

    Uma consulta só, e não uma por linha: a lista de filiados tem mais de
    mil pessoas, e o despachante atende um subconjunto pequeno -- trazer o
    lado pequeno inteiro e cruzar em Python é mais barato que 1500
    consultas, e evita um IN com mais parâmetros do que o SQLite aceita.

    O cruzamento é feito aqui, no código, porque `core.cliente` e
    `dominio.filiado` vivem em bancos diferentes e o SQLite não aplica FK
    entre bancos anexados -- a integridade cross-domínio sempre foi
    responsabilidade do código neste projeto."""
    con = conectar(empresa_id)
    try:
        return {
            l["cpf"]: l["cliente_id"]
            for l in con.execute(
                "SELECT cliente_id, cpf FROM cliente WHERE empresa_id = ? AND cpf IS NOT NULL",
                (empresa_id,),
            )
        }
    finally:
        con.close()


def _registrar_consulta_externa(empresa_id: str, cpf: str, encontrado: bool) -> None:
    """Rastro de quem consultou o cadastro de qual CPF no Shooting House.

    A tela é autenticada e o funcionário é de confiança -- não é isso que
    está em questão. É que esta consulta alcança QUALQUER pessoa que já
    passou pelo clube, inclusive quem nunca foi cliente do despachante, e
    uma consulta assim precisa deixar rastro por princípio. O CPF vai
    mascarado: o log é pra saber que houve consulta, não pra virar uma
    segunda base de CPFs.

    Falhar aqui não derruba o cadastro (mesmo critério do envelope de
    conversa em atendimento/processar.py), mas não passa calado."""
    try:
        con = conectar(empresa_id)
        try:
            motor_log_administrativo.registrar(
                con, empresa_id,
                tipo_evento="CONSULTA_CADASTRO_EXTERNO",
                alvo=mascarar_cpf(cpf),
                descricao="Busca de cadastro no Shooting House pela tela de Clientes",
                valor_anterior=None,
                valor_novo="encontrado" if encontrado else "sem registro",
                criado_por=session.get("usuario_id", "desconhecido"),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        traceback.print_exc()


@app.route("/api/filiados/panorama")
@login_required
@funcao_required("habitualidade")
def filiados_panorama():
    """Panorama de habitualidade do clube inteiro -- quem está atrasado e
    há quanto tempo.

    Os números NÃO saem daqui ao vivo: vêm da tabela `filiado`, que é um
    retrato sincronizado de tempos em tempos (o Shooting House não avisa
    ninguém quando alguém lança habitualidade, e a consulta é por CPF, uma
    pessoa por vez -- ver domain/clube_tiro/sincronizar_habitualidade.py).

    Por isso `sincronizado_em` vai junto de cada linha e o resumo carrega
    a sincronização mais antiga: a tela precisa dizer o quanto o retrato
    pode estar velho. E nenhuma afirmação a cliente sai daqui -- pergunta
    de cliente continua sendo respondida por consulta ao vivo.
    """
    empresa_id = empresa_atual()
    # Três estados, não dois, e confundi-los custou um bug: o parâmetro
    # AUSENTE significa "não me disseram, use o padrão (ativos)"; presente
    # e VAZIO significa "todos, de propósito"; presente com valor filtra
    # por ele. `x or None` colapsava os dois primeiros, e a opção "Todos"
    # da tela devolvia só os ativos, calada.
    situacao = request.args.get("situacao")
    if situacao is None:
        # `todos=1` continua funcionando pra não quebrar link antigo.
        somente_ativos = request.args.get("todos") != "1"
    else:
        somente_ativos = False
        situacao = situacao or None

    filiados = motor_filiados.listar_panorama(
        empresa_id,
        somente_ativos=somente_ativos,
        busca=request.args.get("busca"),
        situacao=situacao,
        faixa=request.args.get("faixa"),
        participou_de=request.args.get("participou_de"),
        participou_ate=request.args.get("participou_ate"),
        ordenar_por=request.args.get("ordenar_por"),
    )
    # Quem também é cliente do despachante ganha o cliente_id, e a tela
    # vira link pra ficha. As duas populações são separadas de propósito,
    # mas quando são a mesma pessoa o sistema tem que mostrar tudo que
    # sabe dela -- e a ponte é o CPF.
    clientes = _clientes_por_cpf(empresa_id)
    # Vencimento do CR: o que o despachante cadastrou vale; sem isso, a
    # data do Shooting House, marcada como tal -- ela não é
    # confirmadamente o vencimento (ver motor_anotacoes_filiado).
    vencimentos = motor_anotacoes_filiado.vencimentos_cr_por_cpf(empresa_id)
    for filiado in filiados:
        filiado["cliente_id"] = clientes.get(filiado["cpf"])
        manual = vencimentos.get(filiado["cpf"])
        filiado["cr_vencimento"] = manual or filiado.get("cr_validade")
        filiado["cr_vencimento_origem"] = (
            "manual" if manual else ("api" if filiado.get("cr_validade") else None)
        )

    return jsonify(
        # O resumo é do CLUBE inteiro, de propósito -- ele não acompanha
        # a busca. São dois números com perguntas diferentes: "como está
        # o clube" e "achei quem eu procurava". Fazer os cartões
        # encolherem a cada letra digitada tiraria a única referência
        # estável da tela.
        resumo=motor_filiados.resumo_do_clube(empresa_id),
        filiados=filiados,
        total_encontrados=len(filiados),
        total_tambem_clientes=sum(1 for f in filiados if f["cliente_id"]),
        janela_meses=motor_filiados.JANELA_MESES,
    )


def _consultar_ou_indisponivel(buscar):
    """Devolve (valor, motivo_da_falha). Cada bloco da ficha falha
    sozinho: se a consulta de armas cair, habitualidade e cadastro
    continuam aparecendo. Uma tela que some inteira porque um pedaço
    falhou esconde o que estava funcionando."""
    try:
        return buscar(), None
    except ShootingHouseIndisponivel as e:
        return None, str(e)


@app.route("/api/filiados/<cpf>/ficha")
@login_required
@funcao_required("habitualidade")
def filiado_ficha(cpf):
    """Tudo que o Shooting House sabe sobre um filiado, CONSULTADO AO
    VIVO -- não é o retrato guardado na tabela `filiado`.

    É a diferença que a tela precisa deixar clara: o panorama mostra o
    retrato (rápido, serve pra ordenar prioridade); esta ficha pergunta
    na hora (é o que serve pra falar com a pessoa).

    Nada daqui é gravado. `consultar_ficha_completa` existe separada de
    `consultar_cadastro` exatamente por isso -- aquela alimenta o
    formulário de cliente novo e é enxuta de propósito, esta é para
    exibir e descartar.
    """
    empresa_id = empresa_atual()
    digitos = re.sub(r"\D", "", cpf or "")
    if len(digitos) != 11:
        return jsonify(erro="CPF inválido."), 400

    # As três consultas saem AO MESMO TEMPO (2026-09-24). Em sequência, a
    # ficha esperava a soma das três -- e do Railway (Amsterdã) cada
    # chamada ao Shooting House leva 1,3 a 2,2s, contra 0,4s daqui do
    # Brasil (medido com /checkAuth, sem CPF). Eram ~6s por clique; em
    # paralelo, é a mais lenta das três. Nenhuma depende da outra, e
    # nenhuma lê `session` -- por isso rodam fora do contexto da
    # requisição sem problema.
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_ficha = executor.submit(_consultar_ou_indisponivel, lambda: consultar_ficha_completa(digitos))
        f_hab = executor.submit(_consultar_ou_indisponivel, lambda: consultar_habitualidade(digitos))
        f_armas = executor.submit(_consultar_ou_indisponivel, lambda: consultar_armas(digitos))
        ficha, erro_ficha = f_ficha.result()
        habitualidade, erro_hab = f_hab.result()
        armas, erro_armas = f_armas.result()

    # Consulta ao vivo de dado de arma e habitualidade de uma pessoa,
    # por CPF -- deixa rastro, como todo acesso a dado sensível aqui.
    _registrar_consulta_externa(empresa_id, digitos, encontrado=bool(ficha))

    eventos = []
    for grupo, dados in ((habitualidade or {}).get("habitualidades") or {}).items():
        for evento in dados.get("eventos", []):
            eventos.append({**evento, "grupo": grupo})
    # Mais recente primeiro. Data em formato inesperado não derruba a
    # tela: vai pro fim em vez de estourar o sort.
    def _quando(evento):
        try:
            return datetime.strptime(evento.get("data_participacao") or "", "%d/%m/%Y")
        except ValueError:
            return datetime.min
    eventos.sort(key=_quando, reverse=True)

    # Treino x prova, janela de 12 meses (pedido do usuário, 2026-09-23):
    # "tudo que é lançado como treino é treino, todas as outras são
    # provas". Conta em Python sobre o mesmo `habitualidade` já
    # consultado acima -- nunca uma segunda chamada à API.
    treinos_provas = (
        motor_filiados.contar_treinos_e_provas(habitualidade)
        if habitualidade else {"treinos": 0, "provas": 0, "total": 0}
    )

    # SIGMA e acervo (2026-09-24). A API quase nunca devolve o SIGMA por
    # esta rota; a habitualidade já consultada acima recupera o de quem
    # usou a arma num lançamento (mesmo caminho do Portal), e o que
    # continuar faltando o despachante digita. Acervo não existe na API.
    if armas is not None:
        if habitualidade:
            armas = [completar_arma_via_habitualidade(a, habitualidade) for a in armas]
        armas = motor_anotacoes_filiado.mesclar_armas(
            armas, motor_anotacoes_filiado.anotacoes_armas(empresa_id, digitos),
        )

    return jsonify(
        ficha=ficha,
        armas=armas,
        acervos=list(documentos_cac.FINALIDADES_ARMA),
        # Datas do CR como o despachante cadastrou -- a API não tem a de
        # expedição, e a dela de "expiração" não é confirmadamente o
        # vencimento. A tela mostra a da API ao lado, só como referência.
        cr_cadastrado=motor_anotacoes_filiado.obter_cr(empresa_id, digitos),
        eventos=eventos,
        total_participacoes=len(eventos),
        treinos_provas_12m=treinos_provas,
        # Um por bloco: a tela mostra "não foi possível consultar" só na
        # parte que falhou, e nunca como se fosse "não tem".
        indisponivel={"ficha": erro_ficha, "armas": erro_armas, "habitualidade": erro_hab},
        simulado=bool((ficha or {}).get("simulado") or (habitualidade or {}).get("simulado")),
    )


def _cpf_da_rota(cpf: str) -> str:
    digitos = re.sub(r"\D", "", cpf or "")
    return digitos if len(digitos) == 11 else ""


@app.route("/api/filiados/<cpf>/cr", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_salvar_cr(cpf):
    """Expedição e vencimento do CR, digitados pelo despachante."""
    digitos = _cpf_da_rota(cpf)
    empresa_id = empresa_atual()
    # Só de quem passou pelo clube DESTA empresa -- sem isso a rota
    # aceitaria anotar qualquer CPF digitado na URL.
    if not digitos or not motor_filiados.obter_por_cpf(empresa_id, digitos):
        return jsonify(erro="Filiado não encontrado."), 404
    corpo = request.get_json(force=True) or {}
    try:
        cr = motor_anotacoes_filiado.salvar_cr(
            empresa_id, digitos,
            data_expedicao=corpo.get("data_expedicao"),
            data_vencimento=corpo.get("data_vencimento"),
            atualizado_por=session.get("usuario_nome"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, cr=cr)


@app.route("/api/filiados/<cpf>/armas/<arma_id>", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_salvar_arma(cpf, arma_id):
    """SIGMA (quando a API não trouxe) e acervo de uma arma."""
    digitos = _cpf_da_rota(cpf)
    empresa_id = empresa_atual()
    if not digitos or not motor_filiados.obter_por_cpf(empresa_id, digitos):
        return jsonify(erro="Filiado não encontrado."), 404
    corpo = request.get_json(force=True) or {}
    try:
        arma = motor_anotacoes_filiado.salvar_arma(
            empresa_id, digitos, arma_id,
            sigma=corpo.get("sigma"), acervo=corpo.get("acervo"),
            atualizado_por=session.get("usuario_nome"),
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, arma=arma)


def _cliente_do_filiado(empresa_id: str, cpf: str):
    """O cliente_id da pessoa, ou None se ela ainda não é cliente."""
    return _clientes_por_cpf(empresa_id).get(cpf)


def _garantir_cliente_do_filiado(empresa_id: str, filiado: dict, motivo: str):
    """(cliente_id, criado_agora). Filiado que ainda não é cliente ganha
    cadastro -- só num gesto sobre AQUELA pessoa (guardar documento,
    cadastrar senha), nunca em lote. Levanta ClienteInvalido."""
    cliente_id = _cliente_do_filiado(empresa_id, filiado["cpf"])
    if cliente_id:
        return cliente_id, False
    try:
        return criar_cliente(
            empresa_id, nome=filiado["nome"], cpf=filiado["cpf"], email=filiado.get("email"),
            observacoes=f"Cadastro criado {motivo}.",
        )["cliente_id"], True
    except ClienteJaExiste as e:
        return e.cliente_id, False


@app.route("/api/filiados/<cpf>/dossie")
@login_required
@funcao_required("habitualidade")
def filiado_dossie_listar(cpf):
    """Os documentos do filiado (2026-09-24).

    Não é um segundo lugar de guardar arquivo: é o MESMO dossiê da ficha
    do cliente, visto da tela de Filiados. Dois depósitos para a mesma
    pessoa seriam o CR dela em um e o CRAF no outro, e ninguém saberia
    onde procurar. Quem ainda não é cliente ganha cadastro no primeiro
    documento guardado (ver filiado_dossie_enviar)."""
    digitos = _cpf_da_rota(cpf)
    empresa_id = empresa_atual()
    if not digitos or not motor_filiados.obter_por_cpf(empresa_id, digitos):
        return jsonify(erro="Filiado não encontrado."), 404
    cliente_id = _cliente_do_filiado(empresa_id, digitos)
    return jsonify(
        cliente_id=cliente_id,
        documentos=motor_documentos.listar_dossie(empresa_id, cliente_id) if cliente_id else [],
        catalogo=documentos_cac.catalogo(),
        dias_alerta=documentos_cac.DIAS_ALERTA_VALIDADE,
        finalidades_arma=list(documentos_cac.FINALIDADES_ARMA),
    )


@app.route("/api/filiados/<cpf>/dossie", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_dossie_enviar(cpf):
    """Guarda um documento do filiado. Se ele ainda não é cliente do
    despachante, o cadastro nasce aqui -- mesma regra do Portal
    (2026-09-02): só quando há um gesto sobre AQUELA pessoa, nunca em
    lote. Ter documento guardado já é ser atendido."""
    digitos = _cpf_da_rota(cpf)
    empresa_id = empresa_atual()
    filiado = motor_filiados.obter_por_cpf(empresa_id, digitos) if digitos else None
    if not filiado:
        return jsonify(erro="Filiado não encontrado."), 404

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(erro="Selecione um arquivo."), 400
    conteudo = arquivo.read()
    if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
        return jsonify(erro="Arquivo maior que 15MB."), 400

    try:
        cliente_id, cadastro_criado = _garantir_cliente_do_filiado(
            empresa_id, filiado, "ao guardar o primeiro documento pela tela de Filiados",
        )
    except ClienteInvalido as e:
        return jsonify(erro=f"Não foi possível criar o cadastro: {e}"), 400

    try:
        documento_id = motor_documentos.salvar_no_dossie(
            empresa_id, cliente_id, conteudo, arquivo.filename,
            tipo_documento=(request.form.get("tipo_documento") or "").strip(),
            data_validade=(request.form.get("data_validade") or "").strip() or None,
            referencia=(request.form.get("referencia") or "").strip() or None,
            finalidade=(request.form.get("finalidade") or "").strip() or None,
        )
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True, documento_id=documento_id, cliente_id=cliente_id,
                   cadastro_criado=cadastro_criado)


# ---------------------------------------------------------------------
# Senha do gov.br (2026-09-24) -- ver core/motor_credenciais.py.
#
# Dois caminhos para a MESMA senha, como o dossiê: pela ficha do cliente
# e pela do filiado. A senha é do CLIENTE; o filiado que ainda não é
# cliente ganha cadastro ao ter a senha guardada. O valor só sai pela
# rota /revelar, que registra quem pediu, e com Cache-Control: no-store
# para o navegador não guardar a resposta em disco.
# ---------------------------------------------------------------------

def _resposta_senha(fn):
    try:
        return fn()
    except motor_credenciais.ChaveNaoConfigurada as e:
        return jsonify(erro=str(e)), 503
    except ValueError as e:
        return jsonify(erro=str(e)), 400


def _senha_revelada(empresa_id: str, cliente_id: str):
    senha = motor_credenciais.revelar(
        empresa_id, cliente_id, session.get("usuario_nome", "Painel administrativo"),
    )
    resposta = jsonify(senha=senha)
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.route("/api/clientes/<cliente_id>/senha-govbr")
@login_required
@funcao_required("clientes")
def cliente_senha_situacao(cliente_id):
    return jsonify(motor_credenciais.situacao(empresa_atual(), cliente_id))


@app.route("/api/clientes/<cliente_id>/senha-govbr", methods=["POST"])
@login_required
@funcao_required("clientes")
def cliente_senha_salvar(cliente_id):
    senha = (request.get_json(force=True) or {}).get("senha") or ""
    def salvar():
        motor_credenciais.salvar(empresa_atual(), cliente_id, senha,
                                 session.get("usuario_nome", "Painel administrativo"))
        return jsonify(ok=True)
    return _resposta_senha(salvar)


@app.route("/api/clientes/<cliente_id>/senha-govbr/revelar", methods=["POST"])
@login_required
@funcao_required("clientes")
def cliente_senha_revelar(cliente_id):
    return _resposta_senha(lambda: _senha_revelada(empresa_atual(), cliente_id))


@app.route("/api/clientes/<cliente_id>/senha-govbr/remover", methods=["POST"])
@login_required
@funcao_required("clientes")
def cliente_senha_remover(cliente_id):
    return _resposta_senha(lambda: jsonify(ok=motor_credenciais.remover(
        empresa_atual(), cliente_id, session.get("usuario_nome", "Painel administrativo"))))


def _filiado_da_rota(cpf: str):
    digitos = _cpf_da_rota(cpf)
    return motor_filiados.obter_por_cpf(empresa_atual(), digitos) if digitos else None


@app.route("/api/filiados/<cpf>/senha-govbr")
@login_required
@funcao_required("habitualidade")
def filiado_senha_situacao(cpf):
    filiado = _filiado_da_rota(cpf)
    if not filiado:
        return jsonify(erro="Filiado não encontrado."), 404
    empresa_id = empresa_atual()
    return jsonify(motor_credenciais.situacao(
        empresa_id, _cliente_do_filiado(empresa_id, filiado["cpf"])))


@app.route("/api/filiados/<cpf>/senha-govbr", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_senha_salvar(cpf):
    filiado = _filiado_da_rota(cpf)
    if not filiado:
        return jsonify(erro="Filiado não encontrado."), 404
    senha = (request.get_json(force=True) or {}).get("senha") or ""
    empresa_id = empresa_atual()

    def salvar():
        # Confere a chave ANTES de criar cadastro: sem ela a senha seria
        # recusada, e o cliente teria nascido à toa.
        motor_credenciais._fernet()
        if not senha.strip():
            raise ValueError("Digite a senha.")
        try:
            cliente_id, criado = _garantir_cliente_do_filiado(
                empresa_id, filiado, "ao cadastrar a senha do gov.br pela tela de Filiados",
            )
        except ClienteInvalido as e:
            raise ValueError(f"Não foi possível criar o cadastro: {e}") from None
        motor_credenciais.salvar(empresa_id, cliente_id, senha,
                                 session.get("usuario_nome", "Painel administrativo"))
        return jsonify(ok=True, cadastro_criado=criado)
    return _resposta_senha(salvar)


@app.route("/api/filiados/<cpf>/senha-govbr/revelar", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_senha_revelar(cpf):
    filiado = _filiado_da_rota(cpf)
    if not filiado:
        return jsonify(erro="Filiado não encontrado."), 404
    empresa_id = empresa_atual()
    cliente_id = _cliente_do_filiado(empresa_id, filiado["cpf"])
    if not cliente_id:
        return jsonify(senha=None)
    return _resposta_senha(lambda: _senha_revelada(empresa_id, cliente_id))


@app.route("/api/filiados/<cpf>/senha-govbr/remover", methods=["POST"])
@login_required
@funcao_required("habitualidade")
def filiado_senha_remover(cpf):
    filiado = _filiado_da_rota(cpf)
    if not filiado:
        return jsonify(erro="Filiado não encontrado."), 404
    empresa_id = empresa_atual()
    cliente_id = _cliente_do_filiado(empresa_id, filiado["cpf"])
    if not cliente_id:
        return jsonify(ok=False)
    return _resposta_senha(lambda: jsonify(ok=motor_credenciais.remover(
        empresa_id, cliente_id, session.get("usuario_nome", "Painel administrativo"))))


@app.route("/api/clientes/shooting-house/<cpf>")
@login_required
@funcao_required("clientes")
def clientes_consultar_shooting_house(cpf):
    """Busca o cadastro do atirador no Shooting House pra preencher o
    formulário de cliente novo -- evita redigitar nome, e-mail e telefone
    de quem já é filiado, e evita erro de digitação num dado que vai
    virar chave de consulta depois.

    Três estados distintos na resposta, e a tela precisa dos três
    separados (mesmo cuidado de portal/app.py::_resumo_habitualidade):

      encontrado=True   -> preenche o formulário
      encontrado=False  -> não é atirador do clube; cadastra na mão, o
                           que é normal (nem todo cliente do despachante
                           passou pelo clube)
      indisponivel=True -> NÃO se sabe; a consulta falhou. Nunca mostrar
                           isso como "não encontrado", senão o usuário
                           redigita tudo achando que a pessoa não existe.

    Só leitura, e só os campos cadastrais -- ver _CAMPOS_CADASTRO em
    integracoes/shooting_house.py sobre por que arma e CR não vêm junto.
    """
    empresa_id = empresa_atual()
    try:
        cadastro = consultar_cadastro(cpf)
    except ShootingHouseIndisponivel as e:
        return jsonify(indisponivel=True, motivo=str(e)), 200

    # Consulta de dado de pessoa por CPF, feita por um funcionário, sobre
    # alguém que ainda nem é cliente -- deixa rastro, como todo acesso a
    # dado sensível do projeto (ver motor_ia/orquestrador.py).
    _registrar_consulta_externa(empresa_id, cpf, encontrado=bool(cadastro))

    if not cadastro:
        return jsonify(encontrado=False), 200
    return jsonify(encontrado=True, **cadastro), 200


@app.route("/api/clientes", methods=["POST"])
@login_required
@funcao_required("clientes")
def clientes_criar():
    """A empresa vem da sessão, nunca do formulário -- é a regra que
    separa o dado de um despachante do de outro."""
    dados = request.get_json(silent=True) or {}
    try:
        cliente = criar_cliente(
            empresa_atual(),
            nome=dados.get("nome"),
            cpf=dados.get("cpf"),
            email=dados.get("email"),
            telefone=dados.get("telefone"),
            cidade=dados.get("cidade"),
            observacoes=dados.get("observacoes"),
        )
    except ClienteJaExiste as e:
        # 409 e não 400: o formulário usa isso pra oferecer "abrir a
        # ficha existente" em vez de só reclamar.
        return jsonify(erro=str(e), cliente_id=e.cliente_id), 409
    except ClienteInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(cliente), 201


@app.route("/api/clientes/<cliente_id>/cpf", methods=["POST"])
@login_required
@funcao_required("clientes")
def clientes_informar_cpf(cliente_id):
    """Completa o CPF do contato que chegou por e-mail sem informar
    (core/motor_clientes.py::informar_cpf). Só preenche vazio."""
    dados = request.get_json(silent=True) or {}
    try:
        resultado = informar_cpf(empresa_atual(), cliente_id, dados.get("cpf"))
    except ClienteJaExiste as e:
        return jsonify(erro=str(e), cliente_id=e.cliente_id), 409
    except ClienteInvalido as e:
        return jsonify(erro=str(e)), 400
    return jsonify(resultado)


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
    # A porta continua sendo 5000 por padrão -- é o que está no CLAUDE.md
    # e o que a pessoa espera digitar no navegador. A variável PORT existe
    # só para conseguir subir uma segunda instância quando a 5000 já está
    # ocupada (o painel de verdade rodando, por exemplo), em vez de ter
    # que derrubar a que está no ar.
    app.run(
        host="127.0.0.1", port=int(os.getenv("PORT", "5000")),
        debug=False, use_reloader=False,
    )
