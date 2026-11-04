"""Grava o vídeo explicativo do Portal do Cliente, em formato de celular.

    .venv\\Scripts\\python.exe -m docs.video_portal.gravar_video

Para que serve: o vídeo mostra as telas DE VERDADE do Portal, renderizadas
pelos mesmos templates de produção, mas com gente inventada. Quando uma tela
mudar, roda de novo e o vídeo sai atualizado, sem regravar nada à mão.

Nada aqui toca em dado real. O import de `portal.rodar_demo` aponta o sistema
para um banco temporário (apagado no fim), desliga o Gmail e o Shooting House.
As consultas ao Shooting House são trocadas por dado fictício só dentro deste
processo, e com o mesmo comportamento de produção: `consultar_cr` levanta
indisponível, porque lá ainda não tem implementação real, então o cartão de CR
não aparece no vídeo (mostrar um cartão que o atirador nunca vê só confundiria).

O quadro é montado um a um (captura da tela + faixa de legenda), e não filmado:
é isso que dá texto nítido e rolagem lisa, sem depender da velocidade da máquina.

Saída nesta mesma pasta:
    portal_do_cliente_tutorial.mp4   1080x1920, H.264, pronto para o WhatsApp
    roteiro_narracao.md              o texto de cada trecho, com o tempo
"""
# O import PRECISA vir antes de qualquer coisa do projeto (ver portal/rodar_demo.py).
from portal import rodar_demo as demo  # noqa: E402

import io  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

base = demo.base
PASTA_SAIDA = Path(__file__).resolve().parent
SAIDA_MP4 = PASTA_SAIDA / "portal_do_cliente_tutorial.mp4"
SAIDA_ROTEIRO = PASTA_SAIDA / "roteiro_narracao.md"
# Fotos de conferência de cada trecho. Fora do repositório, de propósito.
PASTA_FOTOS = Path(os.environ.get("VIDEO_FOTOS") or tempfile.mkdtemp(prefix="video_portal_fotos_"))
FFMPEG = os.environ.get("FFMPEG_EXE") or r"C:\Program Files\ShareX\ffmpeg.exe"

PORTA = 5013
URL = f"http://127.0.0.1:{PORTA}"
ENDERECO_PUBLICO = "portal.smithclubedetiro.com.br"

LARGURA, ALTURA = 1080, 1920
VIEW_L, VIEW_A = 390, 570  # a tela do celular, em pixels de CSS
ESCALA = LARGURA / VIEW_L
TELA_A = round(VIEW_A * ESCALA)
FAIXA_A = ALTURA - TELA_A
FPS = 30

# CPF de exemplo clássico, para aparecer digitado e na folha impressa.
CPF_FICTICIO = "12345678909"
CPF_FICTICIO_TELA = "123.456.789-09"

FONTES = (
    '<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders:wght@600;700'
    '&family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
)


# ---------------------------------------------------------------- dado fictício
def _eventos_ficticios() -> dict:
    hoje = date.today()
    arma_1 = "(XX000001) Pistola - Modelo Exemplo - 9mm"
    arma_2 = "(XX000002) Carabina - Modelo Exemplo - .22 LR"
    # (dias atrás, hora, modalidade, arma, prova ou None para treino)
    linhas = [
        (6, "16:30", "Treino", arma_1, None),
        (20, "10:15", "Precisão", arma_1, "Prova de Precisão Smith Clube"),
        (41, "15:00", "Treino", arma_2, None),
        (63, "09:45", "Treino", arma_1, None),
        (88, "14:20", "4 Armas", arma_1, "Prova 4 Armas Smith Clube"),
        (112, "16:00", "Treino", arma_2, None),
        (150, "11:10", "Treino", arma_1, None),
        (190, "10:30", "Treino", arma_1, None),
        (240, "15:40", "Precisão", arma_2, "Prova de Precisão Smith Clube"),
        (300, "09:20", "Treino", arma_1, None),
        (420, "16:10", "Treino", arma_2, None),
        (560, "10:05", "Treino", arma_1, None),
    ]
    eventos = [
        {
            "data_participacao": (hoje - timedelta(days=dias)).strftime("%d/%m/%Y"),
            "hora_participacao": hora,
            "modalidade": modalidade,
            "local": "Smith Clube de Tiro",
            "arma": arma,
            "competicao": prova or "TREINO",
        }
        for dias, hora, modalidade, arma, prova in linhas
    ]
    return {"habitualidades": {"ACRP": {"count": len(eventos), "eventos": eventos}}}


ARMAS_FICTICIAS = [
    {"id": 1, "type": "Pistola", "brand": "Exemplo", "model": "Modelo A", "caliber": "9mm",
     "serie": "XX000001", "sigma": "000001", "grupo": "ACRP"},
    {"id": 2, "type": "Carabina", "brand": "Exemplo", "model": "Modelo B", "caliber": ".22 LR",
     "serie": "XX000002", "sigma": "000002", "grupo": "ACRP"},
]


def preparar_banco() -> None:
    base._criar_banco_core()
    base._criar_banco_dominio()
    base._popular_habitualidade()

    # O calendário é o público do clube. Um campeonato inventado num vídeo
    # enviado ao grupo seria lido como prova de verdade.
    from domain.clube_tiro.db.popular_campeonatos_2026 import main as popular_campeonatos
    popular_campeonatos(base.EMPRESA)

    con = sqlite3.connect(os.environ["ERP_CORE_DB"])
    con.execute("UPDATE empresa SET nome = 'Smith Clube de Tiro'")
    con.execute("UPDATE cliente SET cpf = ? WHERE cliente_id = ?", (CPF_FICTICIO, demo.CLIENTE_DEMO))
    con.execute("UPDATE caso SET descricao = NULL, titulo = 'Transferência de arma' WHERE caso_id = 'CAS-000001'")
    processo = con.execute(
        "SELECT processo_id FROM processo WHERE caso_id = 'CAS-000001' AND servico_id = 'SER-000004'"
    ).fetchone()[0]
    con.commit()
    con.close()
    con = sqlite3.connect(os.environ["ERP_DOMAIN_DB"])
    con.execute("UPDATE filiado SET cpf = ? WHERE cpf = '10000000006'", (CPF_FICTICIO,))
    con.commit()
    con.close()

    base._marcar_checklist_demo(processo, "CAS-000001", demo.CLIENTE_DEMO)

    from core.motor_marketplace import aprovar, criar_anuncio
    for categoria, titulo, descricao, valor in [
        ("Acessório", "Coldre de cintura", "Pouco uso, para pistola. Anúncio de exemplo.", 180.0),
        ("Luneta/Mira", "Red dot compacto", "Com caixa e manual. Anúncio de exemplo.", 950.0),
        ("Equipamento", "Abafador eletrônico", "Funcionando perfeitamente. Anúncio de exemplo.", 420.0),
    ]:
        anuncio = criar_anuncio(
            base.EMPRESA, "CLI-000002", categoria, titulo, descricao=descricao, valor=valor,
            contato_email="anunciante@exemplo.local",
        )
        aprovar(base.EMPRESA, anuncio, "demonstração")


def trocar_consultas(portal_app) -> dict:
    """Só dentro deste processo. Devolve onde o código de acesso aparece."""
    from integracoes.shooting_house import ShootingHouseIndisponivel

    def cr_como_em_producao(_cpf):
        raise ShootingHouseIndisponivel("Sem implementação real.")

    portal_app.consultar_cr = cr_como_em_producao
    portal_app.consultar_habitualidade = lambda _cpf, **_k: _eventos_ficticios()
    portal_app.consultar_armas = lambda _cpf: [dict(a) for a in ARMAS_FICTICIAS]
    portal_app.consultar_ficha_completa = lambda _cpf: {
        "status_filiacao": "Ativo", "anuidade_em_dia": "Sim",
        "anuidade_validade": (date.today() + timedelta(days=210)).isoformat(),
    }

    capturado = {}
    criar_acesso_original = portal_app.criar_acesso

    def criar_acesso_guardando(*args, **kwargs):
        token, codigo = criar_acesso_original(*args, **kwargs)
        capturado["codigo"] = codigo
        return token, codigo

    portal_app.criar_acesso = criar_acesso_guardando
    return capturado


# ------------------------------------------------------------------- os cartões
def _pagina_cartao(corpo: str, css: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTES}<style>
      * {{ box-sizing: border-box; margin: 0; }}
      html, body {{ width: {LARGURA}px; height: {ALTURA}px; background: #16181D; color: #fff;
        font-family: 'IBM Plex Sans', sans-serif; }}
      body {{ padding: 90px 72px; display: flex; flex-direction: column; }}
      h1 {{ font-family: 'Big Shoulders', sans-serif; font-weight: 700; font-size: 104px; line-height: 1.02; }}
      h2 {{ font-family: 'Big Shoulders', sans-serif; font-weight: 700; font-size: 58px; line-height: 1.1; }}
      .logo {{ width: 340px; display: block; }}
      .sub {{ color: #C9CDD4; font-size: 44px; line-height: 1.32; }}
      .mono {{ font-family: 'IBM Plex Mono', monospace; font-weight: 500; }}
      .bloco {{ background: #fff; color: #16181D; border-radius: 28px; padding: 40px 44px; }}
      {css}
    </style></head><body>{corpo}</body></html>"""


def cartao_abertura() -> str:
    return _pagina_cartao(f"""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:44px;">
        <img class="logo" src="{URL}/portal/static/img/logo_smith_white.png">
        <h1>Portal do Cliente</h1>
        <p class="sub">Como usar pelo celular: habitualidade, acervo, documentos e processos em um só lugar.</p>
      </div>""")


def cartao_endereco() -> str:
    return _pagina_cartao(f"""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:48px;">
        <p class="sub" style="color:#6FA0DC; font-weight:600;">Passo 1</p>
        <h1 style="font-size:88px;">Abra o navegador do celular e digite o endereço</h1>
        <div class="bloco mono" style="font-size:43px; text-align:center; padding:48px 16px;">{ENDERECO_PUBLICO}</div>
        <p class="sub">Safari no iPhone. Chrome no Android.</p>
      </div>""")


def cartao_email(codigo: str) -> str:
    return _pagina_cartao(f"""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:40px;">
        <p class="sub" style="color:#6FA0DC; font-weight:600;">O e-mail que você recebe</p>
        <div class="bloco" style="font-size:36px; line-height:1.42;">
          <p style="font-weight:600;">Smith Clube de Tiro</p>
          <p style="color:#5B6470; font-size:31px;">atendimentosmithclube@gmail.com</p>
          <p style="color:#5B6470; margin-bottom:28px;">Seu link de acesso ao Portal do Cliente</p>
          <p>Olá Helena Costa,</p>
          <p style="margin:22px 0 8px;">Use o link abaixo para acessar o Portal (válido por 15 minutos, uso único):</p>
          <p style="color:#2F5FA7; text-decoration:underline; margin-bottom:22px; overflow-wrap:anywhere;">https://{ENDERECO_PUBLICO}/portal/entrar/...</p>
          <p>Está usando o app do Portal no celular? Digite este código lá:</p>
          <p class="mono" style="font-size:78px; letter-spacing:.08em; text-align:center; margin-top:24px;">{codigo}</p>
        </div>
        <p class="sub"><b style="color:#fff;">Não chegou?</b> Olhe o Spam ou o Lixo eletrônico. Ele vai para o e-mail cadastrado no clube.</p>
      </div>""")


def cartao_instalar() -> str:
    compartilhar = ('<svg width="44" height="44" viewBox="0 0 20 20" fill="none" stroke="#2F5FA7" stroke-width="1.6" '
                    'stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-9px"><path d="M10 2.5v10"/>'
                    '<path d="M6.5 6 10 2.5 13.5 6"/><path d="M6 9H4.5v8.5h11V9H14"/></svg>')
    return _pagina_cartao(f"""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:38px;">
        <h1 style="font-size:84px;">Deixe o Portal na tela do celular</h1>
        <div class="bloco">
          <h2>iPhone, no Safari</h2>
          <ol><li>Toque em Compartilhar {compartilhar}</li>
          <li>Escolha <b>Adicionar à Tela de Início</b></li>
          <li>Toque em <b>Adicionar</b></li></ol>
        </div>
        <div class="bloco">
          <h2>Android, no Chrome</h2>
          <ol><li>Toque em <b>Instalar</b> no aviso do Portal</li>
          <li>Sem aviso? Abra o menu <b>⋮</b> e toque em <b>Instalar app</b> ou <b>Adicionar à tela inicial</b></li></ol>
        </div>
        <p class="sub"><b style="color:#fff;">No app, entre sempre pelo código</b> de 6 dígitos do e-mail.</p>
      </div>""", "ol { margin-top: 20px; padding-left: 50px; font-size: 38px; line-height: 1.34; } li { margin-top: 12px; }")


def cartao_atualizacao() -> str:
    return _pagina_cartao("""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:30px;">
        <h1 style="font-size:82px;">Quanto tempo leva para atualizar?</h1>
        <div class="bloco faixa" style="--cor:#2E7D4F;">
          <h2 style="color:#2E7D4F;">Na hora</h2>
          <p>Habitualidade, acervo e filiação: o Portal pergunta ao sistema do clube cada vez que você abre a tela.</p>
          <p>Processos, documentos e campeonatos: assim que o clube ou o despachante lança.</p>
        </div>
        <div class="bloco faixa" style="--cor:#A8750B;">
          <h2 style="color:#7A5709;">Até 3 horas</h2>
          <p>Filiado novo ou filiação regularizada: é o tempo para liberar o acesso. Se o menu não mudar, toque em Sair e entre de novo.</p>
        </div>
        <div class="bloco faixa" style="--cor:#2F5FA7;">
          <h2 style="color:#2F5FA7;">Depois da conferência</h2>
          <p>Documento enviado e anúncio do Marketplace dependem da aprovação do despachante.</p>
        </div>
      </div>""", """.faixa { border-left: 16px solid var(--cor); padding: 30px 36px; }
                    .faixa p { font-size: 35px; line-height: 1.32; margin-top: 12px; }""")


def cartao_treino() -> str:
    return _pagina_cartao("""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:44px;">
        <h1 style="font-size:88px;">Treinou e não apareceu?</h1>
        <div class="bloco" style="font-size:42px; line-height:1.36;">
          <p><b>1.</b> Abra a tela de Habitualidade de novo pelo menu.</p>
          <p style="margin-top:26px;"><b>2.</b> Confira se a participação foi lançada no tablet do clube. O que não foi lançado lá não aparece aqui.</p>
          <p style="margin-top:26px;"><b>3.</b> Ainda faltando? Fale com a secretaria.</p>
        </div>
      </div>""")


def cartao_final() -> str:
    return _pagina_cartao(f"""
      <div style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:48px;">
        <img class="logo" src="{URL}/portal/static/img/logo_smith_white.png">
        <h1 style="font-size:92px;">Agora é só entrar</h1>
        <div class="bloco mono" style="font-size:43px; text-align:center; padding:48px 16px;">{ENDERECO_PUBLICO}</div>
        <p class="sub">Dúvidas ou e-mail desatualizado? Fale com a secretaria do clube.</p>
      </div>""")


def faixa_legenda(rotulo: str, texto: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTES}<style>
      * {{ box-sizing: border-box; margin: 0; }}
      body {{ width: {LARGURA}px; height: {FAIXA_A}px; background: #16181D; color: #fff; overflow: hidden;
        border-top: 6px solid #2F5FA7; padding: 22px 44px 0; font-family: 'IBM Plex Sans', sans-serif; }}
      .topo {{ display: flex; justify-content: space-between; align-items: baseline; }}
      .rotulo {{ font-family: 'Big Shoulders', sans-serif; font-weight: 700; font-size: 46px; color: #6FA0DC; }}
      .demo {{ font-size: 25px; color: #98A0AC; }}
      .texto {{ font-size: 45px; line-height: 1.22; font-weight: 500; margin-top: 10px; }}
    </style></head><body>
      <div class="topo"><span class="rotulo">{rotulo}</span><span class="demo">Dados fictícios de demonstração</span></div>
      <p class="texto">{texto}</p>
    </body></html>"""


# ------------------------------------------------------------------ o gravador
class Gravador:
    def __init__(self, navegador):
        contexto = navegador.new_context(
            viewport={"width": VIEW_L, "height": VIEW_A}, device_scale_factor=ESCALA,
            is_mobile=True, has_touch=True, locale="pt-BR",
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
        )
        self.page = contexto.new_page()
        self.pintor = navegador.new_context(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1,
        ).new_page()
        self.ffmpeg = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{LARGURA}x{ALTURA}", "-r", str(FPS), "-i", "-",
             "-vf", "scale=out_color_matrix=bt709,format=yuv420p",
             "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-profile:v", "high", "-level", "4.1",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             str(SAIDA_MP4.with_suffix(".sem_audio.mp4"))],
            stdin=subprocess.PIPE,
        )
        self.quadros = 0
        self.atual = Image.new("RGB", (LARGURA, ALTURA), (22, 24, 29))
        self.tela = None
        self.faixa = None
        self.roteiro = []
        self.ultimo_texto_em = 0.0
        self.ultimo_texto_palavras = 0
        self.fotos = 0

    # --- quadros
    @property
    def tempo(self) -> float:
        return self.quadros / FPS

    def _escrever(self, imagem: Image.Image, repeticoes: int = 1) -> None:
        dados = imagem.tobytes()
        for _ in range(repeticoes):
            self.ffmpeg.stdin.write(dados)
        self.quadros += repeticoes
        self.atual = imagem

    def segurar(self, segundos: float) -> None:
        self._escrever(self.atual, max(1, round(segundos * FPS)))

    def _misturar_para(self, alvo: Image.Image, quadros: int = 9) -> None:
        origem = self.atual
        for i in range(1, quadros + 1):
            self._escrever(Image.blend(origem, alvo, i / quadros))
        self.atual = alvo

    def foto(self, nome: str) -> None:
        self.fotos += 1
        self.atual.convert("RGB").resize((360, 640)).save(PASTA_FOTOS / f"{self.fotos:02d}_{nome}.jpg", quality=85)

    def _montar(self, tela: Image.Image, faixa: Image.Image) -> Image.Image:
        quadro = Image.new("RGB", (LARGURA, ALTURA))
        quadro.paste(tela, (0, 0))
        quadro.paste(faixa, (0, TELA_A))
        return quadro

    # --- captura
    def capturar(self) -> Image.Image:
        cru = self.page.screenshot(type="png", clip={"x": 0, "y": 0, "width": VIEW_L, "height": VIEW_A})
        imagem = Image.open(io.BytesIO(cru)).convert("RGB")
        if imagem.size != (LARGURA, TELA_A):
            imagem = imagem.resize((LARGURA, TELA_A), Image.LANCZOS)
        return imagem

    def _pintar(self, html: str, altura: int) -> Image.Image:
        self.pintor.set_content(html, wait_until="networkidle")
        self.pintor.evaluate("document.fonts.ready")
        cru = self.pintor.screenshot(type="png", clip={"x": 0, "y": 0, "width": LARGURA, "height": altura})
        return Image.open(io.BytesIO(cru)).convert("RGB")

    def carregar(self) -> None:
        self.page.wait_for_load_state("networkidle")
        self.page.evaluate("document.fonts.ready")

    def atualizar_tela(self, quadros: int = 9) -> None:
        """A página mudou: mostra a tela nova com a faixa atual."""
        self.carregar()
        self.tela = self.capturar()
        self._misturar_para(self._montar(self.tela, self.faixa), quadros)

    # --- legenda e narração
    def legenda(self, rotulo: str, texto: str) -> None:
        self.ler()
        self.faixa = self._pintar(faixa_legenda(rotulo, texto), FAIXA_A)
        if self.tela is None:
            self.tela = self.capturar()
        self.roteiro.append((self.tempo, rotulo, texto))
        self._misturar_para(self._montar(self.tela, self.faixa), 7)
        self.ultimo_texto_em = self.tempo
        self.ultimo_texto_palavras = len(texto.split())

    def ler(self) -> None:
        """Segura o tempo que falta para a legenda atual ser lida com calma."""
        if not self.ultimo_texto_palavras:
            return
        necessario = 0.7 + self.ultimo_texto_palavras / 2.6
        falta = necessario - (self.tempo - self.ultimo_texto_em)
        if falta > 0:
            self.segurar(falta)
        self.ultimo_texto_palavras = 0

    def cartao(self, html: str, segundos: float, rotulo: str, narracao: str, nome: str) -> None:
        self.ler()
        imagem = self._pintar(html, ALTURA)
        self.roteiro.append((self.tempo, rotulo, narracao))
        self._misturar_para(imagem, 12)
        self.segurar(max(segundos, len(narracao.split()) / 2.8))
        self.foto(nome)
        self.tela = None

    def voltar_da_cartao(self) -> None:
        self.tela = self.capturar()

    # --- gestos
    def rolar(self, destino_y: float, segundos: float = 1.1) -> None:
        inicio = self.page.evaluate("window.scrollY")
        maximo = self.page.evaluate("document.documentElement.scrollHeight - innerHeight")
        destino_y = max(0, min(destino_y, maximo))
        passos = max(2, round(segundos * FPS))
        for i in range(1, passos + 1):
            t = i / passos
            suave = t * t * (3 - 2 * t)
            self.page.evaluate("y => window.scrollTo({top: y, behavior: 'instant'})", inicio + (destino_y - inicio) * suave)
            self.tela = self.capturar()
            self._escrever(self._montar(self.tela, self.faixa))

    def rolar_ate(self, localizador, margem: int = 70, segundos: float = 1.1) -> None:
        topo = localizador.first.evaluate("e => e.getBoundingClientRect().top + window.scrollY")
        self.rolar(topo - margem, segundos)

    def tocar(self, localizador, depois_navega: bool = True) -> None:
        alvo = localizador.first
        caixa = alvo.bounding_box()
        if not caixa or caixa["y"] < 0 or caixa["y"] + caixa["height"] > VIEW_A:
            self.rolar_ate(alvo, margem=int(VIEW_A / 2 - 30))
            caixa = alvo.bounding_box()
        cx = (caixa["x"] + caixa["width"] / 2) * ESCALA
        cy = (caixa["y"] + caixa["height"] / 2) * ESCALA
        self.tela = self.capturar()
        base_quadro = self._montar(self.tela, self.faixa)
        for i in range(13):
            self._escrever(_com_toque(base_quadro, cx, cy, i / 12))
        self.atual = base_quadro
        alvo.click()
        if depois_navega:
            self.atualizar_tela()

    def digitar(self, localizador, texto: str) -> None:
        campo = localizador.first
        campo.click()
        for letra in texto:
            campo.press_sequentially(letra)
            self.tela = self.capturar()
            self._escrever(self._montar(self.tela, self.faixa), 4)

    def abrir_pelo_menu(self, nome: str) -> None:
        self.rolar(0, 0.5)
        self.tocar(self.page.locator(".portal-topo-mobile"), depois_navega=False)
        self.page.wait_for_timeout(450)
        self.atualizar_tela(6)
        self.segurar(0.2)
        self.tocar(self.page.locator(f".portal-nav a:has-text('{nome}')"))

    def fechar(self) -> None:
        self.ffmpeg.stdin.close()
        self.ffmpeg.wait()


def _com_toque(quadro: Image.Image, cx: float, cy: float, t: float) -> Image.Image:
    """Um dedo: círculo que aparece, aperta e solta um anel."""
    resultado = quadro.copy()
    lado = 360
    camada = Image.new("RGBA", (lado * 2, lado * 2), (0, 0, 0, 0))
    pincel = ImageDraw.Draw(camada)
    centro = lado
    entrada = min(1.0, t / 0.35)
    raio = (70 - 14 * math.sin(min(1.0, t / 0.6) * math.pi)) * entrada * 2
    pincel.ellipse([centro - raio, centro - raio, centro + raio, centro + raio],
                   fill=(47, 95, 167, int(120 * entrada)), outline=(255, 255, 255, int(235 * entrada)), width=8)
    if t > 0.45:
        anel = (t - 0.45) / 0.55
        raio_anel = (80 + 150 * anel) * 2
        pincel.ellipse([centro - raio_anel, centro - raio_anel, centro + raio_anel, centro + raio_anel],
                       outline=(47, 95, 167, int(200 * (1 - anel))), width=10)
    camada = camada.resize((lado, lado), Image.LANCZOS)
    resultado.paste(camada, (int(cx - lado / 2), int(cy - lado / 2)), camada)
    return resultado


# -------------------------------------------------------------------- o roteiro
def filmar(g: Gravador, capturado: dict) -> None:
    pagina = g.page

    g.cartao(cartao_abertura(), 3.0, "Abertura",
             "Este é o Portal do Cliente do Smith. Veja como usar tudo pelo celular.", "abertura")
    g.cartao(cartao_endereco(), 4.0, "Passo 1",
             f"Abra o navegador do celular e digite o endereço: {ENDERECO_PUBLICO}.", "endereco")

    # Entrar. O convite do app fica para depois: ele cobriria o formulário.
    pagina.goto(f"{URL}/portal/login")
    pagina.evaluate("localStorage.setItem('portal_convite_app_fechado', '1')")
    pagina.reload()
    g.carregar()
    g.voltar_da_cartao()
    g.legenda("Entrar", "Digite seu CPF ou o e-mail cadastrado no clube e toque em Receber acesso. Não tem senha para decorar.")
    g.foto("login")
    g.digitar(pagina.locator("#identificador"), CPF_FICTICIO_TELA)
    g.ler()
    g.tocar(pagina.locator("button[type=submit]"))
    g.legenda("Entrar", "Agora vá ao seu e-mail. Chega um link e um código de 6 dígitos.")
    g.foto("pede_codigo")
    g.ler()

    g.cartao(cartao_email(capturado["codigo"]), 6.5, "Entrar",
             "O e-mail traz o link e o código. Se não chegar, olhe o Spam.", "email")
    g.voltar_da_cartao()
    g.legenda("Entrar", "Digite o código, ou toque no link do e-mail. Vale por 15 minutos. Se pedir outro, só o último funciona.")
    g.ler()
    g.digitar(pagina.locator("#codigo"), capturado["codigo"])
    g.tocar(pagina.locator("button[type=submit]"))

    # Início, com o convite do app de verdade.
    g.legenda("Início", "Pronto, você entrou! O Portal mantém você conectado por 30 dias.")
    g.foto("inicio")
    g.ler()
    pagina.evaluate("localStorage.removeItem('portal_convite_app_fechado')")
    pagina.reload()
    g.atualizar_tela()
    g.legenda("Instalar o app", "O Portal também vira um app na tela do celular. É o mesmo Portal, sem loja e sem download.")
    g.foto("convite_app")
    g.ler()
    g.cartao(cartao_instalar(), 8.5, "Instalar o app",
             "No iPhone, toque em Compartilhar e escolha Adicionar à Tela de Início. "
             "No Android, toque em Instalar. No app, entre sempre pelo código.", "instalar")
    g.voltar_da_cartao()
    g.legenda("Início", "No Início você vê o próximo campeonato, a habitualidade, a filiação e seus processos.")
    g.tocar(pagina.locator("#convite-app-fechar"), depois_navega=False)
    g.atualizar_tela(6)
    g.foto("inicio_sem_convite")
    g.segurar(0.6)
    g.rolar_ate(pagina.locator(".destaque-mini").nth(1), margem=64, segundos=1.1)
    g.segurar(0.7)
    g.rolar_ate(pagina.locator(".stats-grid"), margem=64, segundos=1.1)
    g.foto("inicio_processos")
    g.ler()

    # Habitualidade
    g.legenda("Menu", "Toque nas três listras para abrir o menu. Habitualidade e Marketplace são para filiados ativos.")
    g.rolar(0, 0.6)
    g.ler()
    g.abrir_pelo_menu("Habitualidade")
    g.legenda("Habitualidade", "Aqui estão suas participações, treinos, provas e a data da última.")
    g.foto("habitualidade")
    g.ler()
    g.legenda("Habitualidade", "Escolha o período: 6, 12, 24 ou 36 meses. Os números acompanham a escolha.")
    g.ler()
    g.tocar(pagina.locator(".filtro-periodo a:has-text('24')"))
    g.segurar(0.6)
    g.legenda("Habitualidade", "No histórico está cada participação, com data, modalidade e arma.")
    g.rolar_ate(pagina.locator(".secao-titulo").first, margem=64, segundos=1.2)
    g.foto("habitualidade_historico")
    g.ler()
    g.legenda("Habitualidade", "E este botão prepara a relação em folha timbrada, para imprimir ou salvar em PDF.")
    g.rolar_ate(pagina.locator("#botao-folha"), margem=150, segundos=0.8)
    g.ler()
    g.tocar(pagina.locator("#botao-folha"))
    g.foto("folha")
    g.segurar(2.5)
    pagina.go_back()
    g.atualizar_tela()

    # Acervo
    g.abrir_pelo_menu("Acervo")
    g.legenda("Acervo", "No Acervo ficam as armas registradas em seu nome: calibre, série, Sigma e grupo.")
    g.foto("acervo")
    g.ler()

    # Despachante
    g.abrir_pelo_menu("Despachante")
    g.legenda("Despachante", "Em Despachante você acompanha cada caso. Toque em um deles para ver os detalhes.")
    g.foto("despachante")
    g.ler()
    g.tocar(pagina.locator(".grupo-caso-cabecalho"))
    g.legenda("Despachante", "Quando o serviço termina, o documento pronto fica aqui para visualizar, imprimir ou salvar.")
    entrega = pagina.locator(".entrega")
    g.rolar_ate(entrega, margem=170, segundos=1.2)
    g.foto("documento_pronto")
    g.ler()
    g.legenda("Despachante", "O checklist mostra o que foi recebido, o que aguarda aprovação e o que ainda falta.")
    g.rolar_ate(pagina.locator(".checklist"), margem=70, segundos=1.2)
    g.foto("checklist")
    g.ler()
    g.rolar_ate(pagina.locator(".ficha-form"), margem=110, segundos=1.4)
    g.legenda("Despachante", "Para enviar: escolha o documento, anexe um PDF ou foto de até 15 MB e toque em Enviar.")
    g.ler()
    pagina.locator("#tipo_documento").select_option(index=1)
    g.atualizar_tela(6)
    g.segurar(0.5)
    with tempfile.NamedTemporaryFile(prefix="documento_exemplo_", suffix=".pdf", delete=False) as arquivo:
        arquivo.write(base._pdf_exemplo())
    pagina.locator("#arquivo").set_input_files(arquivo.name)
    g.atualizar_tela(6)
    g.segurar(0.8)
    g.tocar(pagina.locator(".ficha-form button[type=submit]"))
    os.unlink(arquivo.name)
    g.legenda("Despachante", "Enviado! O documento fica aguardando aprovação até o despachante conferir.")
    g.foto("enviado")
    g.ler()

    # Minha conta
    g.abrir_pelo_menu("Minha conta")
    g.legenda("Minha conta", "Em Minha conta ficam os documentos guardados pelo despachante, com a validade de cada um.")
    g.foto("minha_conta")
    g.ler()

    # Campeonatos
    g.abrir_pelo_menu("Campeonatos")
    g.legenda("Campeonatos", "Em Campeonatos está o calendário de provas do clube.")
    g.foto("campeonatos")
    g.ler()
    g.rolar(420, 1.2)
    g.segurar(0.2)

    # Marketplace
    g.abrir_pelo_menu("Marketplace")
    g.legenda("Marketplace", "No Marketplace, os filiados anunciam entre si. Seu anúncio entra depois da aprovação do despachante.")
    g.foto("marketplace")
    g.ler()

    g.cartao(cartao_atualizacao(), 16.0, "Atualização",
             "Habitualidade, acervo e filiação atualizam na hora, sempre que você abre a tela. "
             "Processos, documentos e campeonatos, assim que o clube ou o despachante lança. "
             "Filiado novo ou filiação regularizada leva até 3 horas para liberar. "
             "Documento enviado e anúncio dependem da conferência do despachante.", "atualizacao")
    g.cartao(cartao_treino(), 8.0, "Atualização",
             "Treinou e não apareceu? Abra a tela de novo e confira se foi lançado no tablet do clube. "
             "Se ainda faltar, fale com a secretaria.", "treino")
    g.cartao(cartao_final(), 4.0, "Encerramento",
             "Agora é só entrar. Dúvidas ou e-mail desatualizado? Fale com a secretaria do clube.", "final")


def _tempo(segundos: float) -> str:
    return f"{int(segundos // 60)}:{int(segundos % 60):02d}"


def escrever_roteiro(roteiro: list, duracao: float) -> None:
    linhas = [
        "# Roteiro de narração: Portal do Cliente\n",
        f"Duração do vídeo: {_tempo(duracao)}. Para gravar sua voz em cima, leia cada trecho no tempo indicado.\n",
        "| Tempo | Tela | O que falar |",
        "|---|---|---|",
    ]
    for inicio, rotulo, texto in roteiro:
        linhas.append(f"| {_tempo(inicio)} | {rotulo} | {texto} |")
    SAIDA_ROTEIRO.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main() -> int:
    if not Path(FFMPEG).exists():
        print(f"ffmpeg não encontrado em {FFMPEG}. Aponte FFMPEG_EXE para ele.")
        return 1
    PASTA_FOTOS.mkdir(parents=True, exist_ok=True)
    preparar_banco()
    from portal import app as modulo_portal
    capturado = trocar_consultas(modulo_portal)
    servidor = make_server("127.0.0.1", PORTA, modulo_portal.app, threaded=True)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    temporario = SAIDA_MP4.with_suffix(".sem_audio.mp4")
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--lang=pt-BR"])
            gravador = Gravador(navegador)
            try:
                filmar(gravador, capturado)
            finally:
                gravador.fechar()
                navegador.close()
        # Faixa de som muda: alguns aparelhos tratam vídeo sem áudio como GIF.
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-i", str(temporario),
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "32k", "-shortest",
             "-movflags", "+faststart", str(SAIDA_MP4)],
            check=True,
        )
        escrever_roteiro(gravador.roteiro, gravador.tempo)
        print(f"Vídeo: {SAIDA_MP4} ({SAIDA_MP4.stat().st_size / 1_000_000:.1f} MB, {_tempo(gravador.tempo)})")
        print(f"Roteiro: {SAIDA_ROTEIRO}")
        print(f"Fotos de conferência: {PASTA_FOTOS}")
    finally:
        temporario.unlink(missing_ok=True)
        servidor.shutdown()
        shutil.rmtree(base.PASTA, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
