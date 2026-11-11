"""PDF da relação de habitualidade, para o botão "Salvar ou imprimir" do
Portal no iPhone.

Por que existe, se a folha HTML já imprime: no app instalado na tela de
início do iPhone, o `window.print()` é instável (2026-10-19: num dia
imprimiu, no outro o botão não fazia nada). O menu de compartilhar do
iPhone funciona ali, e ele oferece "Imprimir" e "Salvar em Arquivos" --
mas precisa de um ARQUIVO, não de uma página. Este módulo monta esse
arquivo a partir do MESMO dicionário que desenha a folha
(`habitualidade_imprimir` em portal/app.py), então o papel do PDF e o da
folha nunca dizem números diferentes.

Fonte Helvetica embutida no próprio PDF (sem arquivo de fonte no
servidor): cobre os acentos do português, e `_t()` troca o pouco que ela
não cobre (travessão, reticências) antes de escrever.
"""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from fpdf import FPDF, FontFace
from PIL import Image

LOGO = Path(__file__).parent / "static" / "img" / "logo_smith.png"

# Mesmas cores da folha HTML (portal_habitualidade_impressao.html).
TINTA = (35, 36, 40)
ACO = (98, 104, 115)
LINHA = (223, 227, 234)
AZUL = (57, 107, 179)
AZUL_FUNDO = (36, 72, 125)

_TROCAS = {"—": "-", "–": "-", "…": "...", "“": '"', "”": '"',
           "‘": "'", "’": "'", " ": " "}


def _t(texto) -> str:
    """Texto que a Helvetica do PDF consegue escrever (latin-1). O que
    sobrar fora disso vira "?" em vez de derrubar a geração inteira por
    causa de um caractere estranho vindo da API."""
    texto = "" if texto is None else str(texto)
    for de, para in _TROCAS.items():
        texto = texto.replace(de, para)
    return texto.encode("latin-1", "replace").decode("latin-1")


@lru_cache(maxsize=1)
def _logo_reduzida() -> Image.Image:
    """Logo em tamanho de papel: a original (900px) só pesaria no arquivo."""
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((450, 450))
    return logo


@lru_cache(maxsize=1)
def _marca_dagua() -> Image.Image:
    """Logo clarinha e girada, já misturada no branco. Pronta em vez de
    transparência do PDF: é o jeito que todo leitor de PDF e toda
    impressora mostram igual."""
    logo = _logo_reduzida()
    fundo = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    clara = logo.copy()
    clara.putalpha(clara.getchannel("A").point(lambda a: int(a * 0.06)))
    fundo.alpha_composite(clara)
    # Mesmo giro da folha HTML (rotate(-18deg) no CSS = anti-horário).
    return fundo.convert("RGB").rotate(18, expand=True, fillcolor=(255, 255, 255))


class _Folha(FPDF):
    def __init__(self, dados: dict):
        super().__init__(format="A4", unit="mm")
        self.dados = dados
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(True, margin=20)
        self.set_title(_t(f"Relação de habitualidade - {dados['atirador_nome']}"))
        self.set_author(_t(dados["nome_clube"]))
        self.alias_nb_pages()

    def header(self):
        # Timbrado de fundo em toda página, antes de qualquer texto.
        marca = _marca_dagua()
        largura = 160
        altura = largura * marca.height / marca.width
        self.image(marca, x=(self.w - largura) / 2, y=(self.h - altura) / 2, w=largura)

        self.image(_logo_reduzida(), x=12, y=10, h=16)
        self.set_xy(12, 11)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*TINTA)
        self.cell(0, 8, _t("Relação de habitualidade"), align="R")
        self.set_xy(12, 19)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*ACO)
        self.cell(0, 5, _t(f"Emitido em {self.dados['emitido_em']}"), align="R")
        self.set_draw_color(*AZUL)
        self.set_line_width(0.9)
        self.line(12, 29, self.w - 12, 29)
        self.set_y(34)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(*LINHA)
        self.set_line_width(0.2)
        self.line(12, self.get_y(), self.w - 12, self.get_y())
        self.set_y(-13)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*ACO)
        self.cell(
            150, 4,
            _t(f"{self.dados['nome_clube']} · Relação gerada pelo Portal do Cliente a partir "
               f"dos registros de habitualidade do clube em {self.dados['emitido_em']}."),
        )
        self.cell(0, 4, f"Página {self.page_no()} de {{nb}}", align="R")


def _rotulo_valor(pdf: FPDF, x: float, y: float, rotulo: str, valor: str):
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*ACO)
    pdf.cell(90, 4, _t(rotulo))
    pdf.set_xy(x, y + 4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*TINTA)
    pdf.cell(90, 6, _t(valor))


def _titulo_secao(pdf: FPDF, titulo: str, complemento: str = ""):
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*AZUL_FUNDO)
    pdf.cell(130, 6, _t(titulo))
    if complemento:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*ACO)
        pdf.cell(0, 6, _t(complemento), align="R")
    pdf.ln(7)


def _tabela_por_modalidade(pdf: FPDF, dados: dict):
    """Participações por modalidade nos quatro períodos, como na folha.
    A coluna do período desta folha vai em negrito."""
    linhas = dados.get("por_modalidade") or []
    if not linhas:
        return
    periodos = dados["periodos"]
    _titulo_secao(pdf, "Participações por modalidade")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*TINTA)
    pdf.set_draw_color(*LINHA)
    largura_num = 20
    with pdf.table(
        col_widths=(pdf.w - 24 - largura_num * len(periodos), *([largura_num] * len(periodos))),
        text_align=("LEFT", *(["RIGHT"] * len(periodos))),
        borders_layout="HORIZONTAL_LINES",
        line_height=4.6,
        padding=(1.4, 1.5),
        headings_style=FontFace(emphasis="BOLD", color=AZUL_FUNDO, size_pt=8.5),
    ) as tabela:
        cabecalho = tabela.row()
        cabecalho.cell("Modalidade")
        for p in periodos:
            cabecalho.cell(f"{p} meses")
        destaque = FontFace(emphasis="BOLD")
        for linha in linhas:
            fila = tabela.row()
            fila.cell(_t(linha["modalidade"]))
            for p in periodos:
                fila.cell(str(linha["contagens"][p]), style=destaque if p == dados["meses"] else None)
    pdf.ln(5)


def gerar_pdf(dados: dict) -> bytes:
    """`dados` é o mesmo contexto que desenha a folha HTML. Só chamar
    quando a folha tem o que emitir (CPF achado e consulta respondida):
    o PDF nunca sai dizendo "nenhuma participação" para quem só não
    conseguimos consultar."""
    pdf = _Folha(dados)
    pdf.add_page()

    y = pdf.get_y()
    _rotulo_valor(pdf, 12, y, "Atirador", dados["atirador_nome"])
    _rotulo_valor(pdf, 108, y, "CPF", dados["cpf_formatado"])
    _rotulo_valor(pdf, 12, y + 12, "Período", f"Últimos {dados['meses']} meses")
    _rotulo_valor(pdf, 108, y + 12, "De / até",
                  f"{dados['inicio_periodo']} a {dados['emitido_em'][:10]}")
    _rotulo_valor(pdf, 12, y + 24, "Relação", dados.get("recorte") or "Todas as participações")

    # Resumo: quatro quadros lado a lado, como na folha.
    y += 40
    participacoes = dados["participacoes_periodo"]
    quadros = [
        (str(participacoes if participacoes is not None else 0), "participações"),
        (str(dados["treinos_provas_periodo"]["treinos"]), "treinos"),
        (str(dados["treinos_provas_periodo"]["provas"]), "provas"),
        (dados["ultima_participacao"] or "-", "última participação"),
    ]
    largura = (pdf.w - 24) / 4
    pdf.set_draw_color(*LINHA)
    pdf.set_line_width(0.3)
    for i, (numero, rotulo) in enumerate(quadros):
        x = 12 + i * largura
        pdf.rect(x, y, largura, 17)
        pdf.set_xy(x + 3, y + 2.5)
        pdf.set_font("Helvetica", "B", 16 if i < 3 else 11)
        pdf.set_text_color(*TINTA)
        pdf.cell(largura - 6, 7, _t(numero))
        pdf.set_xy(x + 3, y + 10.5)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*ACO)
        pdf.cell(largura - 6, 4, _t(rotulo))
    pdf.set_y(y + 23)

    _tabela_por_modalidade(pdf, dados)

    eventos = dados["eventos"]
    recorte = dados.get("recorte")
    _titulo_secao(pdf, f"{recorte or 'Participações'} nos últimos {dados['meses']} meses",
                  f"{len(eventos)} registro{'' if len(eventos) == 1 else 's'}")
    if not eventos:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*TINTA)
        inicio = f"Nenhum registro de {recorte}" if recorte else "Nenhuma participação registrada"
        pdf.multi_cell(0, 6, _t(f"{inicio} nos últimos {dados['meses']} meses."))
        return bytes(pdf.output())

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*TINTA)
    pdf.set_draw_color(*LINHA)
    with pdf.table(
        col_widths=(22, 46, 16, 62, 40),
        text_align="LEFT",
        borders_layout="HORIZONTAL_LINES",
        line_height=4.6,
        padding=(1.6, 1.5),
        headings_style=FontFace(emphasis="BOLD", color=AZUL_FUNDO, size_pt=8.5),
    ) as tabela:
        cabecalho = tabela.row()
        for titulo in ("Data", "Modalidade", "Tipo", "Arma", "Local"):
            cabecalho.cell(titulo)
        for ev in eventos:
            linha = tabela.row()
            data = ev.get("data_participacao") or ""
            if ev.get("hora_participacao"):
                data += f"\n{ev['hora_participacao']}"
            modalidade = ev.get("modalidade") or ""
            if ev.get("grupo"):
                modalidade += f" · {ev['grupo']}"
            # Mesma regra da folha HTML e da tela, letra por letra.
            competicao = ev.get("competicao")
            prova = bool(competicao) and competicao.strip().upper() != "TREINO"
            linha.cell(_t(data))
            linha.cell(_t(modalidade))
            linha.cell("Prova" if prova else "Treino")
            linha.cell(_t(ev.get("arma") or ""))
            linha.cell(_t(ev.get("local") or ""))

    return bytes(pdf.output())
