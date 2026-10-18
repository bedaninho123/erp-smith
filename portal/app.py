"""Portal do Cliente -- autoatendimento pros clientes reais (não staff).
App Flask separado do painel administrativo (webapp/), rodando em porta
própria (5002), com secret key e nome de cookie de sessão totalmente
separados -- ver docs/portal_cliente_arquitetura.md, seção 3
(isolamento de dado é o risco central desta peça: primeira superfície
pública do sistema, domínio regulado de arma de fogo).

Login sem senha, link mágico por e-mail (core/motor_portal_auth.py).
MVP (decisão 1 do documento de arquitetura): status do caso + checklist
de documentos + upload -- sem chat com a IA pelo Portal por enquanto.

MULTI-TENANT: o Portal tem duas camadas de isolamento empilhadas, e as
duas precisam valer.

1. Por EMPRESA. Esta instalação atende uma empresa (PORTAL_EMPRESA_ID no
   .env, padrão EMP-000001) -- coerente com PORTAL_URL_BASE ser um
   endereço só. Quando cada empresa tiver o endereço dela
   (docs/schema_multi_tenant.md §6), a empresa passa a sair do domínio
   acessado; até lá, sai da configuração, nunca do que o visitante
   digita: quem não está logado ainda não tem identidade nenhuma.
2. Por CLIENTE, que já existia e continua sendo a checagem mais
   importante -- toda rota confere se o dono do caso/documento bate com
   session["cliente_id"].

A empresa da sessão vem do cliente que logou (cliente.empresa_id), não
da configuração: se um dia a configuração mudar, uma sessão viva não
passa a enxergar dado de outra empresa.
"""
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv, set_key
from flask import (
    Flask, Response, flash, jsonify, redirect, render_template, request, send_file, session, url_for,
)

from core import motor_checklist, motor_documentos
from core.conexao import conectar
from core.configuracoes import obter_configuracoes
from core.limitador_tentativas import excedeu_limite
from core.motor_casos import criar_caso
from core.motor_clientes import ClienteInvalido, ClienteJaExiste, criar_cliente
from core.motor_marketplace import (
    AnuncioInvalido,
    STATUS_APROVADO,
    STATUS_VENDIDO,
    criar_anuncio,
    listar_anuncios,
    marcar_vendido,
    obter_anuncio,
    remover as remover_anuncio,
)
from core.motor_portal_auth import (
    TOKEN_VALIDADE_MINUTOS,
    criar_acesso,
    localizar_cliente_por_cpf_ou_email,
    validar_e_consumir_codigo,
    validar_e_consumir_token,
)
from domain.clube_tiro.categorias_marketplace import CATEGORIA_ARMA, CATEGORIAS
from domain.clube_tiro.motor_campeonatos import listar_campeonatos, obter_campeonato
from domain.clube_tiro.motor_filiados import (
    PERIODOS_MESES,
    contar_participacoes,
    contar_treinos_e_provas,
    limite_janela,
    localizar_ativo_por_cpf_ou_email,
    obter_por_cpf as obter_filiado_por_cpf,
    periodo_valido,
)
from domain.clube_tiro.motor_resultados import listar_resultados
from integracoes.gmail import enviar_email, gmail_configurado
from integracoes.shooting_house import (
    ShootingHouseIndisponivel,
    completar_arma_via_habitualidade,
    consultar_armas,
    consultar_cr,
    consultar_ficha_completa,
    consultar_habitualidade,
)

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

# Limite de pedidos de link mágico por IP -- sem isso, alguém poderia
# martelar o formulário pra spammar a caixa de entrada de terceiro com
# e-mail de acesso, ou tentar enumerar CPF/e-mail cadastrado mais rápido
# (core/limitador_tentativas.py).
LOGIN_MAX_TENTATIVAS = 5
LOGIN_JANELA_SEGUNDOS = 300
# Código de 6 dígitos: a trava que importa é a do próprio código (5
# chutes, contados no banco -- core/motor_portal_auth.py). Esta, por IP,
# só segura quem tenta varrer vários pedidos de uma vez.
CODIGO_MAX_TENTATIVAS_IP = 10

# Quanto tempo o Portal fica logado (2026-10-14). Antes a sessão morria
# ao fechar o navegador -- num app instalado isso é pedir código toda vez
# que o celular tira o app da memória. 30 dias, e "Sair" continua
# encerrando na hora.
SESSAO_VALIDADE_DIAS = 30

load_dotenv(ENV_PATH)
if not os.getenv("PORTAL_SECRET_KEY"):
    _chave = secrets.token_hex(32)
    set_key(str(ENV_PATH), "PORTAL_SECRET_KEY", _chave)
    os.environ["PORTAL_SECRET_KEY"] = _chave

# static_url_path com o prefixo /portal (2026-10-14): em produção o
# despachante de webapp/servir.py manda pro Portal só o que começa com
# /portal -- um /static/... caía no PAINEL, e o logo só aparecia porque o
# painel tem uma cópia do mesmo arquivo. Os ícones do app não têm.
app = Flask(__name__, static_url_path="/portal/static")
app.secret_key = os.environ["PORTAL_SECRET_KEY"]
app.config["TEMPLATES_AUTO_RELOAD"] = True
# Cookie de sessão só trafega em HTTPS quando COOKIE_HTTPS=Sim no .env --
# mesma lógica de webapp/app.py, desligado por padrão porque o Portal
# ainda roda em HTTP puro (127.0.0.1).
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_HTTPS", "").strip().lower() == "sim"
# Nome de cookie próprio -- por padrão o Flask usa "session" pros dois
# apps, e como painel admin (porta 5000) e Portal (porta 5002) podem
# rodar no mesmo navegador ao mesmo tempo em localhost, cookies com o
# mesmo nome se sobrescreveriam entre si.
app.config["SESSION_COOKIE_NAME"] = "portal_session"
# SameSite=Lax -- mesmo motivo de webapp/app.py: sem a marcação, Safari
# e Firefox mandam o cookie em POST vindo de outro site, e uma página
# maliciosa poderia remover anúncio ou enviar arquivo em nome do cliente
# logado. Lax deixa o link mágico do e-mail funcionando (é navegação
# normal); Strict não deixaria.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=SESSAO_VALIDADE_DIAS)

URL_BASE = os.environ.get("PORTAL_URL_BASE", "http://127.0.0.1:5002")

# De qual empresa é este Portal (ver a nota de multi-tenant no topo do
# arquivo). Usado só na tela de login, antes de existir sessão; depois
# de logado, a empresa vem sempre de session["empresa_id"].
PORTAL_EMPRESA_ID = os.environ.get("PORTAL_EMPRESA_ID", "EMP-000001")


def _data_br(data_iso: Optional[str]) -> Optional[str]:
    """Converte um datetime ISO (ex.: '2026-08-09T00:00:00Z') pro formato
    dd/mm/aaaa usado no resto do Portal (Campeonatos, Habitualidade) --
    sem isso, prazo_estimado aparecia cru só nesta tela, único lugar do
    Portal com data no formato errado."""
    if not data_iso:
        return None
    return datetime.strptime(data_iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def _valor_br(valor: Optional[float]) -> Optional[str]:
    """Formata número puro (3500.0) como moeda brasileira (R$ 3.500,00)
    -- em Python, não no template: aritmética/formatação de número nunca
    é responsabilidade de template (mesmo princípio de datas)."""
    if valor is None:
        return None
    inteiro, decimal = f"{valor:,.2f}".split(".")
    inteiro_br = inteiro.replace(",", ".")
    return f"R$ {inteiro_br},{decimal}"


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
        # Exige os dois: sessão antiga (de antes do multi-tenant) não tem
        # empresa_id e precisa refazer o login em vez de cair num
        # KeyError dentro da rota.
        if not (session.get("cliente_id") and session.get("empresa_id")):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def filiado_ativo_required(f):
    """Marketplace e Habitualidade são só pra quem é filiado ATIVO do
    clube -- sempre depois de @cliente_login_required (mesma ordem de
    login_required/gestor_required no painel). Cliente que não é filiado
    (ex.: só fez transferência de arma) recebe 403, não 404 -- é acesso
    negado, não "não existe"."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("e_filiado_ativo"):
            return jsonify(erro="Este recurso é exclusivo de filiados ativos do clube."), 403
        return f(*args, **kwargs)
    return wrapper


def empresa_atual() -> str:
    """Empresa do cliente logado. Só dentro de rota com
    @cliente_login_required, que é quem garante que a chave existe."""
    return session["empresa_id"]


@app.route("/")
def raiz():
    # Conveniência só pra quem digita a raiz -- em produção o Portal vive
    # inteiro sob /portal/... (ver webapp/servir.py, o despachante de WSGI
    # que decide entre painel e Portal pelo prefixo do caminho; um app
    # respondendo em "/" quebraria essa decisão quando os dois dividem o
    # mesmo domínio).
    return redirect(url_for("login"))


@app.route("/portal/login", methods=["GET", "POST"])
def login():
    mensagem = None
    if request.method == "POST":
        if excedeu_limite(f"login_portal:{request.remote_addr}", LOGIN_MAX_TENTATIVAS, LOGIN_JANELA_SEGUNDOS):
            return render_template(
                "portal_login.html",
                mensagem="Muitas tentativas. Aguarde alguns minutos e tente novamente.",
            )
        identificador = (request.form.get("identificador") or "").strip()
        # Busca dentro da empresa deste Portal. Sem o filtro, um CPF que
        # existe nas duas empresas mandaria link de acesso ao cadastro
        # errado -- e o link dá acesso a documento de arma de fogo.
        cliente = (
            localizar_cliente_por_cpf_ou_email(PORTAL_EMPRESA_ID, identificador)
            if identificador else None
        )
        # Quem ainda não é cliente do despachante mas já é filiado ATIVO
        # do clube ganha cadastro na hora (2026-09-02) -- só quando a
        # PRÓPRIA pessoa pede o link, nunca em lote/importação. É o que
        # abre a porta do Marketplace pros ~1450 filiados que nunca
        # usaram nenhum serviço do despachante, sem misturar as duas
        # populações fora desse gatilho.
        if not cliente and identificador:
            filiado = localizar_ativo_por_cpf_ou_email(PORTAL_EMPRESA_ID, identificador)
            if filiado:
                try:
                    cliente = criar_cliente(
                        PORTAL_EMPRESA_ID, nome=filiado["nome"], cpf=filiado["cpf"],
                        email=filiado.get("email"),
                        observacoes="Cadastro criado automaticamente no primeiro acesso ao Portal (filiado do clube).",
                    )
                except ClienteJaExiste as e:
                    # Já existe cliente com este CPF, só sem e-mail
                    # cadastrado (por isso a busca de cima não achou) --
                    # usa o cadastro que já existe em vez de duplicar.
                    con = conectar(PORTAL_EMPRESA_ID)
                    linha = con.execute(
                        "SELECT * FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
                        (e.cliente_id, PORTAL_EMPRESA_ID),
                    ).fetchone()
                    con.close()
                    cliente = dict(linha) if linha else None
                except ClienteInvalido:
                    cliente = None
            # Mesma exigência de sempre (decisão 3 do Portal): sem
            # e-mail não tem como mandar o link, então conta como "não
            # achou" -- nunca um 500 por tentar mandar e-mail vazio.
            if cliente and not cliente.get("email"):
                cliente = None
        # O desafio vai pra sessão SEMPRE, ache ou não o cliente: é o que
        # prende o código a este aparelho, e um cookie que só mudasse
        # quando o CPF está cadastrado contaria o que a mensagem única
        # abaixo esconde.
        desafio = secrets.token_urlsafe(16)
        session["desafio_login"] = desafio
        session["desafio_em"] = int(time.time())
        session.permanent = True
        if cliente:
            token, codigo = criar_acesso(PORTAL_EMPRESA_ID, cliente["cliente_id"], desafio)
            link = f"{URL_BASE}/portal/entrar/{token}"
            if gmail_configurado():
                config = obter_configuracoes(PORTAL_EMPRESA_ID)
                nome_empresa = config.get("nome_empresa", "nosso escritório")
                try:
                    enviar_email(
                        destinatario=cliente["email"],
                        # Assunto curto e sem pontuação de enfeite: o nome da
                        # empresa já aparece no remetente, logo ao lado (sem o
                        # "nosso escritório" de reserva: remetente com esse nome
                        # é pior que remetente sem nome).
                        assunto="Seu link de acesso ao Portal do Cliente",
                        nome_remetente=config.get("nome_empresa"),
                        corpo=(
                            f"Olá {cliente['nome']},\n\n"
                            "Use o link abaixo para acessar o Portal (válido por 15 minutos, "
                            "uso único):\n\n"
                            f"{link}\n\n"
                            "Está usando o app do Portal no celular? Digite este código lá:\n\n"
                            f"    {codigo}\n\n"
                            "Se você não solicitou esse acesso, é só ignorar este e-mail.\n\n"
                            f"{config.get('assinatura_email', f'Equipe {nome_empresa}')}"
                        ),
                    )
                except Exception:
                    # gmail_configurado() só confere que token.json existe,
                    # não que ele ainda é válido -- um token expirado ou
                    # revogado do lado do Google (RefreshError) só aparece
                    # aqui, na hora de enviar. Sem este try/except, essa
                    # falha derrubava a rota inteira com 500 ANTES de
                    # chegar na mensagem única de baixo -- e um 500 só
                    # quando o CPF/e-mail existe seria um jeito novo de
                    # descobrir se alguém está cadastrado, furando o mesmo
                    # cuidado contra enumeração que essa mensagem protege.
                    # O token já foi criado e ninguém vai usá-lo -- expira
                    # sozinho em 15 minutos, sem risco. Fica só registrado
                    # no console pra alguém notar que o Gmail parou.
                    import traceback
                    traceback.print_exc()
                    print(f"[PORTAL] Falha ao enviar e-mail de acesso -- link (não entregue): {link}")
            else:
                # Gmail ainda não autorizado nesta máquina (uso local/dev)
                # -- imprime o link no console pra dar pra testar sem
                # depender de e-mail real chegando.
                print(f"[PORTAL] Gmail não configurado -- link de acesso: {link}")
                print(f"[PORTAL] Gmail não configurado -- código de acesso: {codigo}")
        # Mensagem sempre igual, ache ou não o cliente -- não dá pista se
        # um CPF/e-mail está cadastrado (evita enumeração de clientes).
        mensagem = (
            "Se encontrarmos esse CPF ou e-mail no nosso cadastro, enviamos "
            "um e-mail com um link e um código de acesso."
        )
        return render_template("portal_login.html", mensagem=mensagem, etapa_codigo=True)
    # O iPhone pode tirar o app da memória enquanto a pessoa vai ao e-mail
    # buscar o código, e aí ele reabre do zero, nesta tela. Se o pedido é
    # recente, ela volta direto ao campo do código em vez de ao do CPF.
    # (O desafio existe para todo pedido, cadastrado ou não, então isto
    # não revela nada.)
    pedido_em = session.get("desafio_em") or 0
    pedido_recente = time.time() - pedido_em < TOKEN_VALIDADE_MINUTOS * 60
    return render_template(
        "portal_login.html",
        etapa_codigo=pedido_recente and session.get("desafio_login") and not request.args.get("novo"),
    )


@app.route("/portal/login/codigo", methods=["POST"])
def entrar_com_codigo():
    """A segunda porta do mesmo acesso (ver core/motor_portal_auth.py):
    o código do e-mail, digitado no aparelho que pediu."""
    if excedeu_limite(f"codigo_portal:{request.remote_addr}", CODIGO_MAX_TENTATIVAS_IP, LOGIN_JANELA_SEGUNDOS):
        return render_template(
            "portal_login.html", etapa_codigo=True,
            erro="Muitas tentativas. Aguarde alguns minutos e tente novamente.",
        )
    cliente_id = validar_e_consumir_codigo(
        PORTAL_EMPRESA_ID, session.get("desafio_login"), request.form.get("codigo"),
    )
    if not cliente_id or not _abrir_sessao(cliente_id):
        # Um texto só para todos os motivos (errado, expirado, esgotado,
        # pedido em outro aparelho) -- mesma regra do link.
        return render_template(
            "portal_login.html", etapa_codigo=True,
            erro="Código incorreto ou expirado. Confira o último e-mail ou peça um novo.",
        )
    return redirect(url_for("dashboard"))


@app.route("/portal/entrar/<token>")
def entrar(token):
    cliente_id = validar_e_consumir_token(PORTAL_EMPRESA_ID, token)
    if not cliente_id or not _abrir_sessao(cliente_id):
        return render_template("portal_expirado.html")
    return redirect(url_for("dashboard"))


def _abrir_sessao(cliente_id: str) -> bool:
    """O que vem depois de link OU código aceito -- num lugar só, para as
    duas portas abrirem exatamente a mesma sessão."""
    # A empresa da sessão sai da linha do cliente, não da configuração:
    # é o cliente que define de quem é o dado que ele vai enxergar pelo
    # resto da sessão.
    con = conectar(PORTAL_EMPRESA_ID)
    cliente = con.execute(
        "SELECT nome, empresa_id FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, PORTAL_EMPRESA_ID),
    ).fetchone()
    con.close()
    if not cliente:
        return False
    # clear() também apaga o desafio_login: o pedido de acesso acabou.
    session.clear()
    session.permanent = True
    session["cliente_id"] = cliente_id
    session["cliente_nome"] = cliente["nome"]
    session["empresa_id"] = cliente["empresa_id"]
    # Filiação é cruzada por CPF (mesmo cruzamento que o painel já faz na
    # ficha do Cliente, bloco "NO CLUBE") -- decide o que aparece no menu
    # (Habitualidade, Marketplace), NÃO decide login: um cliente que
    # nunca foi filiado (ex.: só usou transferência de arma) continua
    # entrando normal, só não vê essas duas abas.
    con2 = conectar(cliente["empresa_id"])
    cpf_cliente = con2.execute(
        "SELECT cpf FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, cliente["empresa_id"]),
    ).fetchone()
    con2.close()
    filiado = obter_filiado_por_cpf(cliente["empresa_id"], cpf_cliente["cpf"] if cpf_cliente else None)
    session["e_filiado_ativo"] = bool(filiado and filiado.get("status_filiacao") == "Ativo")
    return True


@app.route("/portal/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/portal/privacidade")
def privacidade():
    # Pública, sem login, de propósito (2026-10-07): o Google exige o
    # endereço de uma Política de Privacidade acessível para tirar a
    # autorização do Gmail do modo "Testando" -- e nesse modo o token
    # vence a cada 7 dias, que foi o que derrubou o e-mail em julho.
    # Também é o que a LGPD espera de quem guarda CPF e documento de arma.
    return render_template("portal_privacidade.html")


@app.route("/portal/termos")
def termos():
    # Pública, pelo mesmo motivo da política acima: o Google pede o link
    # dos Termos de Serviço na mesma tela de Branding.
    return render_template("portal_termos.html")


# --------------------------------------------------------------------
# App instalável (PWA, 2026-10-14)
# --------------------------------------------------------------------
# O Portal instalado na tela do celular continua sendo este mesmo site:
# o manifesto diz ao celular nome, ícone e cor; o service worker só
# guarda o visual (logo, ícones e a tela "sem internet").
#
# Escopo "/portal" SEM barra no fim: o Início do Portal é "/portal", e um
# escopo "/portal/" deixaria justamente ele fora do app.

PWA_ESCOPO = "/portal"
PWA_VERSAO = "portal-v1"  # trocar quando mudar ARQUIVOS do service worker


@app.route("/portal/manifest.webmanifest")
def pwa_manifesto():
    icones = [
        {"src": url_for("static", filename="app/icone-192.png"), "sizes": "192x192", "type": "image/png"},
        {"src": url_for("static", filename="app/icone-512.png"), "sizes": "512x512", "type": "image/png"},
        {"src": url_for("static", filename="app/icone-maskable-512.png"), "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ]
    resposta = jsonify(
        id=PWA_ESCOPO,
        name="Smith Clube de Tiro",
        short_name="Smith App",
        description="Portal do Cliente: processos, documentos e habitualidade.",
        lang="pt-BR",
        start_url=url_for("dashboard"),
        scope=PWA_ESCOPO,
        display="standalone",
        background_color="#131417",
        theme_color="#131417",
        icons=icones,
    )
    resposta.mimetype = "application/manifest+json"
    return resposta


@app.route("/portal/sw.js")
def pwa_service_worker():
    """Nunca guarda página, dado nem documento -- só o que é igual para
    todo mundo. O Portal mostra CPF, arma e documento de pessoa; um
    celular perdido não pode levar nada disso numa cópia offline. Sem
    internet, a navegação cai na tela "sem conexão" em vez do erro do
    navegador."""
    arquivos = [
        url_for("pwa_offline"),
        url_for("static", filename="img/logo_smith_white.png"),
        url_for("static", filename="app/icone-192.png"),
    ]
    codigo = render_template("portal_sw.js", versao=PWA_VERSAO, arquivos=arquivos,
                             offline=url_for("pwa_offline"),
                             estaticos=url_for("static", filename=""))
    resposta = Response(codigo, mimetype="application/javascript")
    # Sem isto o navegador limita o escopo à pasta do arquivo
    # ("/portal/"), que não inclui o Início ("/portal").
    resposta.headers["Service-Worker-Allowed"] = PWA_ESCOPO
    # O navegador precisa ver versão nova do service worker quando ela
    # sair; cache aqui atrasaria isso.
    resposta.headers["Cache-Control"] = "no-cache"
    return resposta


@app.route("/portal/offline")
def pwa_offline():
    return render_template("portal_offline.html")


def _processos_com_checklist(con, empresa_id: str, caso_id: str) -> list:
    """Processos de um caso, cada um já com o checklist de documentos e
    as contagens pra o alvo de progresso -- usado tanto no resumo do
    dashboard (agregado por caso) quanto na tela de detalhe (completo)."""
    processos = con.execute(
        "SELECT p.processo_id, p.protocolo, p.status, p.prazo_estimado, "
        "p.proxima_acao, s.nome_servico "
        "FROM processo p JOIN servico s ON s.service_id = p.servico_id "
        "WHERE p.caso_id = ? AND p.empresa_id = ? ORDER BY p.data_abertura",
        (caso_id, empresa_id),
    ).fetchall()
    resultado = []
    for linha_processo in processos:
        processo = dict(linha_processo)
        processo["status_classe"] = _classe_selo(processo["status"])
        processo["prazo_estimado_fmt"] = _data_br(processo["prazo_estimado"])
        checklist = motor_checklist.status_checklist(con, empresa_id, processo["processo_id"])
        processo["checklist"] = checklist
        processo["checklist_total"] = len(checklist)
        processo["checklist_recebidos"] = sum(1 for item in checklist if item["recebido"])
        processo["checklist_pct"] = (
            round(100 * processo["checklist_recebidos"] / processo["checklist_total"])
            if checklist else 0
        )
        resultado.append(processo)
    return resultado


def _casos_com_resumo(con, empresa_id: str, cliente_id: str) -> list:
    casos = con.execute(
        "SELECT caso_id, titulo, status, categoria "
        "FROM caso WHERE cliente_id = ? AND empresa_id = ? ORDER BY atualizado_em DESC",
        (cliente_id, empresa_id),
    ).fetchall()

    casos_resumo = []
    for linha_caso in casos:
        caso = dict(linha_caso)
        caso["status_classe"] = _classe_selo(caso["status"])
        processos = _processos_com_checklist(con, empresa_id, caso["caso_id"])
        # A tela "Despachante" mostra o processo dentro do caso dele --
        # guardar a lista aqui evita uma segunda consulta que repetiria
        # exatamente este checklist já calculado acima.
        caso["processos"] = processos
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
    implica atirador ativo.

    `indisponivel=True` é um terceiro estado, diferente de
    tem_registro=False, e a diferença é o ponto todo: "você não tem
    registro no clube" é uma afirmação; "não consegui consultar agora"
    é a ausência dela. Confundir os dois faria a tela dizer a um
    atirador em dia que ele não tem CR nem treino nenhum, sempre que a
    API estivesse fora do ar (ver ShootingHouseIndisponivel em
    integracoes/shooting_house.py)."""
    try:
        cr = consultar_cr(cpf)
    except ShootingHouseIndisponivel:
        cr = None
        cr_indisponivel = True
    else:
        cr_indisponivel = False

    try:
        hab = consultar_habitualidade(cpf)
    except ShootingHouseIndisponivel:
        return {
            "cr": cr, "total_participacoes": 0, "tem_registro": False,
            "indisponivel": True,
        }

    eventos = []
    for dados in (hab.get("habitualidades") or {}).values():
        eventos.extend(dados.get("eventos", []))
    return {
        "cr": cr,
        "total_participacoes": len(eventos),
        "tem_registro": bool(cr) or bool(eventos),
        "indisponivel": cr_indisponivel,
    }


def _resumo_filiacao(cpf: str) -> dict:
    """Situação de anuidade (o que o usuário chama de "validade da
    filiação") pra tela Início -- mesmo padrão de _resumo_habitualidade:
    consulta AO VIVO (`consultar_ficha_completa`), nunca o retrato
    guardado em `dominio.filiado` (aquele existe pro panorama do clube
    inteiro no painel, não pra afirmação a um cliente -- ver CLAUDE.md,
    "Panorama de habitualidade").

    tem_registro=False é "não é filiado" (cliente que só fez
    transferência de arma, por exemplo); indisponivel=True é "não
    consegui perguntar agora" -- os dois nunca podem virar a mesma
    mensagem na tela, senão uma falha de rede vira "você não é filiado"
    pra um sócio de verdade."""
    try:
        ficha = consultar_ficha_completa(cpf)
    except ShootingHouseIndisponivel:
        return {"tem_registro": False, "indisponivel": True}
    if not ficha:
        return {"tem_registro": False, "indisponivel": False}
    return {
        "tem_registro": True,
        "indisponivel": False,
        "anuidade_em_dia": ficha.get("anuidade_em_dia"),
        "anuidade_validade": _data_br(ficha.get("anuidade_validade")),
        # 'Ativo' / 'Inativo' / None -- decide a cor do cartão. None
        # (o campo não veio) fica na cor neutra: pintar de verde
        # afirmaria o que ninguém conferiu, e de vermelho acusaria.
        "status_filiacao": ficha.get("status_filiacao"),
    }


@app.route("/portal")
@cliente_login_required
def dashboard():
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    con = conectar(empresa_id)

    cliente = con.execute(
        "SELECT cpf FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()

    casos_resumo = _casos_com_resumo(con, empresa_id, cliente_id)
    casos_abertos = [c for c in casos_resumo if c["status"] not in ("Encerrado", "Cancelado")]

    processos_rows = con.execute(
        "SELECT p.processo_id, p.status, p.proxima_acao, p.prazo_estimado, "
        "s.nome_servico, ca.caso_id, ca.titulo AS caso_titulo "
        "FROM processo p "
        "JOIN servico s ON s.service_id = p.servico_id "
        "JOIN caso ca ON ca.caso_id = p.caso_id "
        "WHERE p.cliente_id = ? AND p.empresa_id = ? ORDER BY p.ultima_atualizacao DESC",
        (cliente_id, empresa_id),
    ).fetchall()

    processos_em_andamento = []
    documentos_pendentes = 0
    for linha in processos_rows:
        proc = dict(linha)
        checklist = motor_checklist.status_checklist(con, empresa_id, proc["processo_id"])
        documentos_pendentes += sum(1 for item in checklist if not item["recebido"])
        if proc["status"] not in ("Concluído", "Cancelado"):
            proc["status_classe"] = _classe_selo(proc["status"])
            processos_em_andamento.append(proc)
    con.close()

    proximos_campeonatos = _proximos_campeonatos(empresa_id)

    habitualidade_resumo = None
    filiacao_resumo = None
    if cliente and cliente["cpf"]:
        habitualidade_resumo = _resumo_habitualidade(cliente["cpf"])
        filiacao_resumo = _resumo_filiacao(cliente["cpf"])

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
        filiacao_resumo=filiacao_resumo,
    )


@app.route("/portal/casos")
@cliente_login_required
def despachante():
    # Antes eram duas telas -- "Meus casos" e "Processos" -- mostrando o
    # mesmo dado em dois recortes (um caso pode ter vários processos, e
    # as duas listas linkavam pro mesmo caso_detalhe). Fundidas numa só,
    # "Despachante", com o agrupamento Caso -> Processo que o resto do
    # sistema já usa (ver core/motor_casos.py). A URL continua
    # "/portal/casos" -- não é o que o cliente vê, e mudar quebraria
    # qualquer link ou favorito antigo à toa.
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    casos_resumo = _casos_com_resumo(con, empresa_id, cliente_id)
    con.close()

    return render_template(
        "portal_despachante.html",
        ativo="despachante",
        cliente_nome=session.get("cliente_nome"),
        casos=casos_resumo,
    )


@app.route("/portal/processos")
@cliente_login_required
def processos():
    # Tela antiga, fundida em despachante() acima (2026-08-31). Mantida
    # só como redirecionamento -- caso alguém tenha essa URL salva nos
    # favoritos, ela continua levando a algum lugar em vez de dar 404.
    return redirect(url_for("despachante"))


@app.route("/portal/habitualidade")
@cliente_login_required
@filiado_ativo_required
def habitualidade():
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    cliente = con.execute(
        "SELECT cpf FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()
    con.close()

    cpf = cliente["cpf"] if cliente else None
    # Período escolhido pelo atirador (6/12/24/36 meses). Só recorta o que
    # a consulta ao vivo já trouxe -- a chamada ao Shooting House é a mesma
    # para qualquer período, então trocar o filtro não muda o que é lido.
    meses = periodo_valido(request.args.get("periodo"))
    cr = None
    eventos = []
    total_eventos = 0
    participacoes_periodo = None
    ultima_participacao = None
    # Tela vazia por "não consegui consultar" tem que ser visivelmente
    # diferente de tela vazia por "você não tem registro nenhum" -- ver
    # _resumo_habitualidade. Sem este aviso, uma queda da API do Shooting
    # House apareceria pro atirador como um histórico de treinos zerado.
    indisponivel = False
    if cpf:
        try:
            cr = consultar_cr(cpf)
        except ShootingHouseIndisponivel:
            indisponivel = True
        try:
            hab = consultar_habitualidade(cpf)
        except ShootingHouseIndisponivel:
            indisponivel = True
            hab = {}
        # Mesmo formato de /api/filiados/<cpf>/ficha (webapp/app.py) --
        # `grupo` é a chave de fora de habitualidades[grupo][id_arma], e
        # cada evento já vem com `arma` (a arma_formatada mapeada por
        # integracoes/shooting_house.py, série incluída no texto).
        # Legítimo mostrar aqui: é o próprio dono vendo o próprio
        # histórico, atrás de login, e isto nunca passa perto de prompt
        # de IA -- mesma ressalva de motor_documentos.py::salvar_no_dossie
        # sobre número de série.
        for grupo, dados in (hab.get("habitualidades") or {}).items():
            for ev in dados.get("eventos", []):
                eventos.append({**ev, "grupo": grupo})
        eventos.sort(key=lambda e: datetime.strptime(e["data_participacao"], "%d/%m/%Y"), reverse=True)
        total_eventos = len(eventos)
        # O histórico mostra só o período escolhido, com o mesmo corte de
        # data das contagens -- senão o cartão diria "5 em 6 meses" em
        # cima de uma lista de 30 linhas.
        limite = limite_janela(meses)
        eventos = [
            e for e in eventos
            if datetime.strptime(e["data_participacao"], "%d/%m/%Y").date() >= limite
        ]
        # Mesmo número que aparece na ficha de Filiado do painel (bloco
        # "NO CLUBE") quando o período é 12 meses -- mesma função,
        # `contar_participacoes`, pra não existirem duas contas que podem
        # divergir. A diferença é que ali é um retrato sincronizado (pode
        # estar desatualizado) e aqui sai da consulta AO VIVO que acabou
        # de rodar acima -- por isso o número aqui pode não bater com o do
        # painel num dado momento, e é o daqui que vale (CLAUDE.md:
        # pergunta de cliente é sempre consulta ao vivo).
        participacoes_periodo, ultima_participacao = contar_participacoes(hab, meses=meses)
        treinos_provas_periodo = contar_treinos_e_provas(hab, meses=meses)
    else:
        treinos_provas_periodo = {"treinos": 0, "provas": 0, "total": 0}

    return render_template(
        "portal_habitualidade.html",
        ativo="habitualidade",
        cliente_nome=session.get("cliente_nome"),
        cr=cr,
        eventos=eventos,
        total_eventos=total_eventos,
        meses=meses,
        periodos=PERIODOS_MESES,
        participacoes_periodo=participacoes_periodo,
        treinos_provas_periodo=treinos_provas_periodo,
        ultima_participacao=_data_br(ultima_participacao),
        tem_cpf=bool(cpf),
        indisponivel=indisponivel,
    )


@app.route("/portal/acervo")
@cliente_login_required
def acervo():
    """Armas do atirador -- consulta AO VIVO o Shooting House, mesmo
    princípio de habitualidade()/dashboard() acima: nunca guarda cópia
    própria (CLAUDE.md, "consultar, não copiar"). Número de série e
    grupo são legítimos aqui -- é o dono da arma vendo o próprio acervo,
    protegido por login, e esta tela não passa perto de prompt de IA
    nenhum (mesma ressalva de core/motor_documentos.py::salvar_no_dossie
    sobre o dossiê)."""
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    cliente = con.execute(
        "SELECT cpf FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()
    con.close()

    cpf = cliente["cpf"] if cliente else None
    armas = []
    # Mesma distinção de sempre: "não consegui consultar" (indisponivel)
    # nunca pode aparecer como "você não tem arma nenhuma" (lista vazia
    # depois de consulta bem-sucedida) -- ver consultar_armas() e
    # _resumo_habitualidade() acima.
    indisponivel = False
    if cpf:
        try:
            armas = consultar_armas(cpf)
        except ShootingHouseIndisponivel:
            indisponivel = True

        # O endpoint de armas nem sempre traz série/sigma/grupo (visto
        # em 2026-09-02) -- completa com o que a habitualidade já tem
        # confirmado pra mesma arma. Falha na habitualidade aqui não
        # derruba a tela: as armas continuam aparecendo com o que
        # consultar_armas() já trouxe, só sem o complemento.
        if armas:
            try:
                habitualidade = consultar_habitualidade(cpf)
            except ShootingHouseIndisponivel:
                habitualidade = {}
            armas = [completar_arma_via_habitualidade(a, habitualidade) for a in armas]

    return render_template(
        "portal_acervo.html",
        ativo="acervo",
        cliente_nome=session.get("cliente_nome"),
        armas=armas,
        tem_cpf=bool(cpf),
        indisponivel=indisponivel,
    )


def _proximos_campeonatos(empresa_id: str, hoje=None) -> list:
    """Campeonatos de hoje em diante, já formatados pra exibição (dia,
    mês abreviado, intervalo por extenso, rótulo de contagem regressiva)
    -- datas e contas nunca são feitas no template/IA, sempre aqui em
    Python, o texto final só fraseia o número pronto (mesmo princípio de
    integracoes/shooting_house.py). Compartilhado entre a Home (só o
    próximo) e a tela de Campeonatos (a lista inteira)."""
    hoje = hoje or datetime.now().date()
    eventos = []
    for c in listar_campeonatos(empresa_id):
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


def _campeonatos_com_resultado(empresa_id: str, hoje=None) -> list:
    """Campeonatos já ocorridos que têm classificação cadastrada -- lista
    enxuta (nome/data/local), sem a classificação em si: cada um vira só
    um link pra tela própria de resultado (/portal/resultados/<id>),
    não um bloco inteiro dentro da tela de Campeonatos."""
    hoje = hoje or datetime.now().date()
    resultado = []
    for c in listar_campeonatos(empresa_id):
        data_fim = datetime.strptime(c["data_fim"], "%Y-%m-%d").date()
        if data_fim >= hoje:
            continue
        if not listar_resultados(empresa_id, c["campeonato_id"]):
            continue
        resultado.append({**c, "intervalo": _intervalo_campeonato(c, hoje)})

    resultado.sort(key=lambda c: c["data_inicio"], reverse=True)
    return resultado


@app.route("/portal/campeonatos")
@cliente_login_required
def campeonatos():
    hoje = datetime.now().date()
    eventos = _proximos_campeonatos(empresa_atual(), hoje)
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
        campeonatos_com_resultado=_campeonatos_com_resultado(empresa_atual()),
    )


@app.route("/portal/resultados/<campeonato_id>")
@cliente_login_required
def resultado_detalhe(campeonato_id):
    empresa_id = empresa_atual()
    campeonato = obter_campeonato(empresa_id, campeonato_id)
    resultados_lista = listar_resultados(empresa_id, campeonato_id) if campeonato else []
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
    empresa_id = empresa_atual()
    con = conectar(empresa_id)

    # Mesmo princípio de isolamento do resto do Portal: o caso só é
    # encontrado se pertencer a este cliente -- nunca confia no caso_id
    # da URL sozinho. Com multi-tenant a checagem ganha uma segunda
    # camada (empresa), mas a de cliente continua sendo a que importa:
    # dois clientes da MESMA empresa também não podem se enxergar.
    linha_caso = con.execute(
        "SELECT caso_id, titulo, descricao, status, categoria "
        "FROM caso WHERE caso_id = ? AND cliente_id = ? AND empresa_id = ?",
        (caso_id, cliente_id, empresa_id),
    ).fetchone()
    if not linha_caso:
        con.close()
        flash("Caso não encontrado.", "erro")
        return redirect(url_for("despachante"))

    caso = dict(linha_caso)
    caso["status_classe"] = _classe_selo(caso["status"])
    caso["processos"] = _processos_com_checklist(con, empresa_id, caso_id)

    # Documentos que ainda faltam, agrupados por processo -- alimenta o
    # <select> do formulário de envio (o cliente escolhe da lista em vez
    # de escrever de cabeça o nome do documento exigido).
    #
    # Cada opção carrega processo + item, não só o texto: é isso que
    # permite o envio virar uma pendência de aprovação naquele item
    # específico do checklist, em vez de um arquivo solto que alguém
    # teria que ligar à mão depois. Item que já está aguardando
    # conferência sai da lista -- reenviar não adianta nada enquanto
    # ninguém olhou o primeiro.
    itens_faltando = []
    for processo in caso["processos"]:
        faltando = [
            {
                "valor": f"{processo['processo_id']}|{item['documento_exigido_id']}",
                "texto": item["item"],
            }
            for item in processo["checklist"]
            if item["estado"] == "faltando"
        ]
        if faltando:
            itens_faltando.append({"processo_label": processo["nome_servico"], "itens": faltando})

    documentos = con.execute(
        "SELECT documento_id, tipo_documento, nome_arquivo, status, data_envio "
        "FROM documento WHERE cliente_id = ? AND empresa_id = ? AND ("
        "  caso_id = ? OR processo_id IN (SELECT processo_id FROM processo WHERE caso_id = ?)"
        ") ORDER BY data_envio DESC",
        (cliente_id, empresa_id, caso_id, caso_id),
    ).fetchall()
    con.close()

    return render_template(
        "portal_caso.html",
        ativo="casos",
        cliente_nome=session.get("cliente_nome"),
        caso=caso,
        itens_faltando=itens_faltando,
        # data_envio formatada aqui pelo mesmo motivo do prazo_estimado
        # (ver _data_br): a tabela mostrava "2026-07-29" cru enquanto o
        # resto do Portal usa dd/mm/aaaa. É a segunda vez que uma coluna
        # de data escapa nesta tela -- toda data nova que entrar aqui
        # passa por _data_br antes de ir pro template.
        documentos=[
            dict(d, data_envio_fmt=_data_br(d["data_envio"])) for d in documentos
        ],
    )


@app.route("/portal/documentos", methods=["POST"])
@cliente_login_required
def upload_documento():
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    caso_id = (request.form.get("caso_id") or "").strip() or None

    def _voltar():
        if caso_id:
            return redirect(url_for("caso_detalhe", caso_id=caso_id))
        return redirect(url_for("despachante"))

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
        return redirect(url_for("despachante"))

    # Nunca confiar no caso_id vindo do formulário sem checar que
    # pertence a este cliente -- ponto central de isolamento de dado do
    # Portal (docs/portal_cliente_arquitetura.md, seção 3). Sem essa
    # checagem, um cliente poderia anexar (ou pior, associar) um
    # documento ao caso de outra pessoa só trocando o ID na requisição.
    # Redirecionar de volta pro caso_id "cru" é seguro mesmo assim:
    # caso_detalhe() faz essa mesma checagem de novo antes de mostrar
    # qualquer coisa.
    con = conectar(empresa_id)
    dono = con.execute(
        "SELECT cliente_id FROM caso WHERE caso_id = ? AND empresa_id = ?",
        (caso_id, empresa_id),
    ).fetchone()
    con.close()
    if not dono or dono["cliente_id"] != cliente_id:
        flash("Caso não encontrado.", "erro")
        return redirect(url_for("despachante"))

    # "__outro__" é o valor do <select> quando o documento não está na
    # lista de faltantes (portal_caso.html) -- nesse caso o texto de
    # verdade vem do campo livre que aparece ao lado. Qualquer outro
    # valor é "PRO-xxxxxx|DEX-xxxxxx": o item exato do checklist que o
    # cliente diz estar respondendo.
    escolha = (request.form.get("tipo_documento") or "").strip()
    processo_id = documento_exigido_id = None
    tipo_documento = escolha

    if escolha == "__outro__":
        tipo_documento = (request.form.get("tipo_documento_outro") or "").strip()
    elif "|" in escolha:
        processo_id, documento_exigido_id = escolha.split("|", 1)
        # O par vem do formulário, então nada nele é confiável. Duas
        # coisas precisam ser provadas antes de qualquer gravação: que o
        # processo pertence ao caso que já sabemos ser deste cliente (sem
        # isso, trocar o ID no formulário anexaria documento no processo
        # de outra pessoa) e que o item é mesmo do serviço desse
        # processo. A segunda é conferida de novo dentro de
        # marcar_documento -- redundância proposital, é a única escrita
        # do Portal que o cliente direciona.
        con = conectar(empresa_id)
        item = con.execute(
            "SELECT dex.item FROM processo p "
            "JOIN documento_exigido dex ON dex.servico_id = p.servico_id "
            "     AND dex.empresa_id = p.empresa_id "
            "WHERE p.processo_id = ? AND p.caso_id = ? AND p.empresa_id = ? "
            "  AND dex.documento_exigido_id = ? "
            # Item extra só vale no processo a que pertence -- sem isto, o
            # cliente poderia mandar arquivo para o item extra de outro.
            "  AND (dex.processo_id IS NULL OR dex.processo_id = p.processo_id)",
            (processo_id, caso_id, empresa_id, documento_exigido_id),
        ).fetchone()
        con.close()
        if not item:
            flash("Documento não encontrado na sua lista.", "erro")
            return _voltar()
        tipo_documento = item["item"]

    tipo_documento = tipo_documento or "Anexo enviado pelo cliente (Portal)"

    documento_id = motor_documentos.salvar_documento(
        empresa_id, cliente_id, conteudo, arquivo.filename,
        caso_id=caso_id,
        tipo_documento=tipo_documento,
    )

    if not processo_id:
        # Documento sem item ("outro"): continua como antes, um anexo
        # que a equipe liga ao checklist manualmente se for o caso.
        flash("Documento enviado.", "sucesso")
        return redirect(url_for("caso_detalhe", caso_id=caso_id))

    try:
        motor_checklist.marcar_documento(
            empresa_id, processo_id, documento_exigido_id, documento_id,
            marcado_por=motor_checklist.MARCADO_POR_CLIENTE,
            status=motor_checklist.STATUS_AGUARDANDO,
        )
    except ValueError as e:
        # O arquivo já está salvo e visível pra equipe; o que falhou foi
        # só o vínculo com o item. Dizer "enviado" e sumir com o aviso
        # esconderia do cliente que aquele item continua em aberto.
        flash(f"Documento enviado, mas não foi vinculado ao item: {e}", "erro")
        return redirect(url_for("caso_detalhe", caso_id=caso_id))

    flash("Documento enviado. Ele vai aparecer como aguardando aprovação.", "sucesso")
    return redirect(url_for("caso_detalhe", caso_id=caso_id))


@app.route("/portal/minha-conta")
@cliente_login_required
def minha_conta():
    """Os documentos permanentes da pessoa, vistos por ela mesma.

    Só a categoria 'Dossiê': documento de caso continua aparecendo dentro
    do caso, que é onde ele faz sentido. Aqui é o arquivo pessoal -- CR,
    CRAF, laudos --, o que a pessoa quer achar sem lembrar em qual
    atendimento ele entrou.

    O cliente NÃO envia documento por esta tela, de propósito: o dossiê é
    o que o despachante conferiu e guardou. Envio de cliente continua
    entrando pelo checklist do caso, que nasce 'Aguardando aprovação' e
    passa por conferência humana (CLAUDE.md). Deixar o cliente escrever
    direto no dossiê apagaria essa distinção.
    """
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    documentos = motor_documentos.listar_dossie(empresa_id, cliente_id)

    for documento in documentos:
        documento["data_envio_fmt"] = _data_br(documento.get("data_envio"))
        documento["data_validade_fmt"] = _data_br(documento.get("data_validade"))
        # A extensão decide como o navegador mostra: imagem vai em <img>,
        # o resto (PDF) em <iframe> com o leitor do próprio navegador.
        nome = (documento.get("nome_arquivo") or "").lower()
        documento["e_imagem"] = nome.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif")
        )

    return render_template(
        "portal_minha_conta.html",
        ativo="minha_conta",
        cliente_nome=session.get("cliente_nome"),
        documentos=documentos,
        vencidos=sum(1 for d in documentos if d["situacao_validade"] == "vencido"),
        vencendo=sum(1 for d in documentos if d["situacao_validade"] == "vencendo"),
    )


@app.route("/portal/documentos/<documento_id>/arquivo")
@cliente_login_required
def download_documento(documento_id):
    cliente_id = session["cliente_id"]
    empresa_id = empresa_atual()
    con = conectar(empresa_id)
    doc = con.execute(
        "SELECT cliente_id, nome_arquivo, link_arquivo FROM documento "
        "WHERE documento_id = ? AND empresa_id = ?",
        (documento_id, empresa_id),
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
    # ?inline=1 mostra dentro da plataforma; sem ele, baixa. É o MESMO
    # arquivo e a MESMA checagem de posse -- só muda o cabeçalho de
    # disposição. O painel administrativo usa o mesmo parâmetro.
    inline = request.args.get("inline") == "1"
    return send_file(caminho, as_attachment=not inline, download_name=nome_sugerido)


# ---------------------------------------------------------------------
# MARKETPLACE (2026-09-02) -- mural de classificados entre os filiados
# ATIVOS do clube (ver core/motor_marketplace.py e
# domain/clube_tiro/categorias_marketplace.py). Sem pagamento: contato
# (telefone/e-mail) vai direto no anúncio, decisão do usuário.
# ---------------------------------------------------------------------

def _servico_transferencia_arma(empresa_id: str) -> Optional[str]:
    """O nome EXATO do serviço de Transferência de Arma no catálogo desta
    empresa, ou None se não existir -- usado pra decidir se mostra o
    botão "Preciso de ajuda com a documentação". Comparação em Python
    (não SQL) porque o `lower()` do SQLite não trata acento
    corretamente, e "Transferência" tem um.

    Só "transferência" no filtro, sem "de arma" -- conferido contra o
    banco real (2026-09-02): o serviço se chama literalmente
    "Transferência" no catálogo migrado da planilha, não "Transferência
    de Arma". O nome mais descritivo só existe no fixture de teste
    (tests/conftest.py), que é escrito à mão e não reflete o dado real."""
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT nome_servico FROM servico WHERE empresa_id = ? AND ativo = 'Sim'",
            (empresa_id,),
        ).fetchall()
    finally:
        con.close()
    for linha in linhas:
        if "transferência" in (linha["nome_servico"] or "").strip().lower():
            return linha["nome_servico"]
    return None


@app.route("/portal/marketplace")
@cliente_login_required
@filiado_ativo_required
def marketplace():
    empresa_id = empresa_atual()
    categoria_filtro = (request.args.get("categoria") or "").strip()
    anuncios = listar_anuncios(empresa_id, status=STATUS_APROVADO)
    if categoria_filtro:
        anuncios = [a for a in anuncios if a["categoria"] == categoria_filtro]
    for a in anuncios:
        a["criado_em_fmt"] = _data_br(a["criado_em"])
        a["valor_fmt"] = _valor_br(a["valor"])
        a["e_meu"] = a["cliente_id"] == session["cliente_id"]

    return render_template(
        "portal_marketplace.html",
        ativo="marketplace",
        cliente_nome=session.get("cliente_nome"),
        anuncios=anuncios,
        categorias=CATEGORIAS,
        categoria_filtro=categoria_filtro,
        categoria_arma=CATEGORIA_ARMA,
        mostra_cta_documentacao=bool(_servico_transferencia_arma(empresa_id)),
    )


@app.route("/portal/marketplace/meus-anuncios")
@cliente_login_required
@filiado_ativo_required
def meus_anuncios():
    empresa_id = empresa_atual()
    cliente_id = session["cliente_id"]
    anuncios = listar_anuncios(empresa_id, cliente_id=cliente_id)
    for a in anuncios:
        a["criado_em_fmt"] = _data_br(a["criado_em"])
        a["valor_fmt"] = _valor_br(a["valor"])

    con = conectar(empresa_id)
    cliente = con.execute(
        "SELECT telefone, email FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone()
    con.close()

    return render_template(
        "portal_marketplace_meus_anuncios.html",
        ativo="marketplace",
        cliente_nome=session.get("cliente_nome"),
        anuncios=anuncios,
        categorias=CATEGORIAS,
        telefone_padrao=cliente["telefone"] if cliente else None,
        email_padrao=cliente["email"] if cliente else None,
    )


@app.route("/portal/marketplace/publicar", methods=["POST"])
@cliente_login_required
@filiado_ativo_required
def marketplace_publicar():
    empresa_id = empresa_atual()
    cliente_id = session["cliente_id"]

    fotos = []
    for arquivo in request.files.getlist("fotos"):
        if not arquivo or not arquivo.filename:
            continue
        extensao = Path(arquivo.filename).suffix.lower()
        if extensao not in DOCUMENTO_EXTENSOES_ACEITAS:
            flash(f"Arquivo ignorado (formato não aceito): {arquivo.filename}", "erro")
            continue
        conteudo = arquivo.read()
        if len(conteudo) > DOCUMENTO_TAMANHO_MAXIMO:
            flash(f"Arquivo ignorado (maior que 15MB): {arquivo.filename}", "erro")
            continue
        fotos.append((conteudo, arquivo.filename))

    # Aceita formato brasileiro (ponto de milhar, vírgula decimal) --
    # é como o placeholder do campo instrui a pessoa a digitar.
    valor_bruto = (request.form.get("valor") or "").strip()
    valor = None
    if valor_bruto:
        try:
            valor = float(valor_bruto.replace(".", "").replace(",", "."))
        except ValueError:
            flash("Valor inválido -- use só números (ex.: 3500,00).", "erro")
            return redirect(url_for("meus_anuncios"))

    try:
        criar_anuncio(
            empresa_id, cliente_id,
            categoria=request.form.get("categoria", ""),
            titulo=request.form.get("titulo", ""),
            descricao=request.form.get("descricao"),
            valor=valor,
            contato_telefone=request.form.get("contato_telefone"),
            contato_email=request.form.get("contato_email"),
            fotos=fotos or None,
        )
    except AnuncioInvalido as e:
        flash(str(e), "erro")
        return redirect(url_for("meus_anuncios"))

    flash("Anúncio enviado. Ele aparece na vitrine assim que o despachante aprovar.", "sucesso")
    return redirect(url_for("meus_anuncios"))


def _meu_anuncio_ou_404(empresa_id: str, anuncio_id: str) -> dict:
    """Confere posse antes de qualquer ação de dono (marcar vendido,
    remover) -- mesmo cuidado de sempre no Portal: ID sequencial e fácil
    de adivinhar, quem segura é a checagem de dono, não o acaso."""
    anuncio = obter_anuncio(empresa_id, anuncio_id)
    if not anuncio or anuncio["cliente_id"] != session["cliente_id"]:
        return None
    return anuncio


@app.route("/portal/marketplace/<anuncio_id>/vendido", methods=["POST"])
@cliente_login_required
@filiado_ativo_required
def marketplace_marcar_vendido(anuncio_id):
    empresa_id = empresa_atual()
    if not _meu_anuncio_ou_404(empresa_id, anuncio_id):
        return jsonify(erro="Anúncio não encontrado."), 404
    marcar_vendido(empresa_id, anuncio_id)
    flash("Anúncio marcado como vendido.", "sucesso")
    return redirect(url_for("meus_anuncios"))


@app.route("/portal/marketplace/<anuncio_id>/remover", methods=["POST"])
@cliente_login_required
@filiado_ativo_required
def marketplace_remover(anuncio_id):
    empresa_id = empresa_atual()
    if not _meu_anuncio_ou_404(empresa_id, anuncio_id):
        return jsonify(erro="Anúncio não encontrado."), 404
    remover_anuncio(empresa_id, anuncio_id)
    flash("Anúncio removido.", "sucesso")
    return redirect(url_for("meus_anuncios"))


@app.route("/portal/marketplace/<anuncio_id>/foto/<int:indice>")
@cliente_login_required
@filiado_ativo_required
def marketplace_foto(anuncio_id, indice):
    empresa_id = empresa_atual()
    anuncio = obter_anuncio(empresa_id, anuncio_id)
    # Foto de anúncio Aprovado é visível pra qualquer filiado (é vitrine
    # pública, não documento pessoal); anúncio ainda Pendente/Recusado só
    # o próprio dono pode pré-visualizar.
    if not anuncio:
        return jsonify(erro="Anúncio não encontrado."), 404
    dono = anuncio["cliente_id"] == session["cliente_id"]
    if anuncio["status"] != STATUS_APROVADO and not dono:
        return jsonify(erro="Anúncio não encontrado."), 404
    if indice < 0 or indice >= len(anuncio["fotos"]):
        return jsonify(erro="Foto não encontrada."), 404
    caminho = Path(anuncio["fotos"][indice])
    if not caminho.is_file():
        return jsonify(erro="Arquivo não encontrado no disco."), 404
    return send_file(caminho)


@app.route("/portal/marketplace/<anuncio_id>/documentacao", methods=["POST"])
@cliente_login_required
@filiado_ativo_required
def marketplace_documentacao(anuncio_id):
    """Botão "Preciso de ajuda com a documentação" -- abre um Caso de
    verdade pro despachante, pelo mesmo caminho que "abrir caso à mão"
    usa no painel (core/motor_casos.criar_caso). Pedido do usuário
    (2026-09-02): o marketplace precisa puxar quem anuncia/compra arma
    pra tratar da Transferência com o despachante, não só conectar
    vendedor e comprador."""
    empresa_id = empresa_atual()
    anuncio = obter_anuncio(empresa_id, anuncio_id)
    if not anuncio:
        flash("Anúncio não encontrado.", "erro")
        return redirect(url_for("marketplace"))

    nome_servico = _servico_transferencia_arma(empresa_id)
    if not nome_servico:
        flash("Este serviço não está disponível nesta empresa.", "erro")
        return redirect(url_for("marketplace"))

    criar_caso(
        empresa_id, session["cliente_id"],
        titulo=f"Transferência de arma -- via Marketplace ({anuncio['titulo']})",
        categoria=nome_servico,
        origem="Portal", canal_origem="Portal",
        criado_por=session.get("cliente_nome") or "Portal",
        descricao=f"Aberto a partir do Marketplace, anúncio {anuncio_id}: \"{anuncio['titulo']}\".",
    )
    flash("Prontinho -- o despachante vai entrar em contato pra tratar a documentação.", "sucesso")
    return redirect(url_for("marketplace"))


if __name__ == "__main__":
    # use_reloader=False de proposito (2026-07-30): nesta maquina, com
    # dois Pythons instalados (.venv e a instalacao global), o reloader
    # do Werkzeug entrava num loop -- cada reinicio alternava entre os
    # dois interpretadores e gerava mais um processo filho, sem nunca
    # convergir (mesmo achado em atendimento/webhook.py). Custo de
    # deixar desligado: editar o arquivo exige reiniciar o processo na
    # mao pra valer.
    app.run(host="127.0.0.1", port=5002, debug=False, use_reloader=False)
