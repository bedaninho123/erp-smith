"""Anuidade vencida: um mês de carência, depois o sócio perde o que é
benefício de sócio no app (decisão do usuário, 2026-11-10).

O que se perde: Habitualidade e Marketplace -- "o diferencial de ser sócio
do clube". Os anúncios dele saem da vitrine enquanto durar (nada é
apagado; renovou, voltam sozinhos). O que NÃO se perde: o despachante
(casos, documentos, documento pronto) é serviço à parte e não depende de
anuidade, e documento guardado nunca é apagado por isso.

Por que a regra mora aqui e não no Portal: é conhecimento do clube (um
escritório de advocacia não tem anuidade), e quem desenha a tela não pode
reimplementar a conta -- o cartão do Início, o menu, a trava das rotas e
a vitrine leem todos desta função.

NA DÚVIDA, NÃO CORTA. Os dois campos do Shooting House discordam para
parte dos filiados reais (em 2026-08-27: 179 marcados em atraso, 269 com a
validade vencida). Cortar só pela data tiraria o acesso de quem o próprio
fornecedor considera em dia. Por isso só bloqueia quando os DOIS
concordam: a data passou há mais de CARENCIA_DIAS **e** o status diz
'Não'. Sem data cadastrada, nunca bloqueia (é cadastro incompleto, não
dívida -- ver o comentário de `filiado` no schema do Domínio).

Datas: `hoje` vem sempre de quem chama, já no dia LOCAL (o servidor de
produção roda em UTC). Conta de data nunca vai para template nem para IA.
"""
from datetime import date, datetime, timedelta
from typing import Optional

# "Um mês" do pedido do usuário. Dias corridos e fixos, não "mesmo dia do
# mês seguinte": 31 de janeiro + 1 mês não existe, e uma regra que corta
# acesso não pode ter dia que não existe.
CARENCIA_DIAS = 30

EM_DIA = "em_dia"
# A data não veio. Cadastro incompleto, não dívida.
SEM_DATA = "sem_data"
# A data passou, mas o Shooting House não marca atraso (diz 'Sim' ou não
# diz nada). Os dois discordam: a tela conta que a data passou, e ninguém
# perde nada.
VENCIDA_SEM_CONFIRMACAO = "vencida_sem_confirmacao"
# Vencida e marcada em atraso, ainda dentro do mês: tudo continua
# funcionando, e o cartão avisa até quando.
CARENCIA = "carencia"
# Passou do mês: perde Habitualidade e Marketplace.
BLOQUEADA = "bloqueada"


def _como_data(valor) -> Optional[date]:
    """Aceita date, datetime ou texto ISO ('2026-03-10' ou
    '2026-03-10T00:00:00Z' -- o retrato guarda dos dois jeitos). Qualquer
    outra coisa vira None, e None nunca bloqueia."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def situacao_anuidade(anuidade_em_dia: Optional[str], anuidade_validade, hoje: date) -> dict:
    """Em que pé está a anuidade, e se ela tira os benefícios de sócio.

    Devolve:
        estado    -- uma das constantes acima
        validade  -- date ou None
        prazo     -- último dia da carência (date), só em CARENCIA/BLOQUEADA
        bloqueia  -- True só em BLOQUEADA

    `validade` é o último dia válido: no próprio dia ainda está em dia, e
    no último dia da carência ainda funciona. Perde-se no dia seguinte."""
    validade = _como_data(anuidade_validade)
    if validade is None:
        return {"estado": SEM_DATA, "validade": None, "prazo": None, "bloqueia": False}
    if validade >= hoje:
        return {"estado": EM_DIA, "validade": validade, "prazo": None, "bloqueia": False}
    if anuidade_em_dia != "Não":
        return {"estado": VENCIDA_SEM_CONFIRMACAO, "validade": validade, "prazo": None, "bloqueia": False}
    prazo = validade + timedelta(days=CARENCIA_DIAS)
    if hoje <= prazo:
        return {"estado": CARENCIA, "validade": validade, "prazo": prazo, "bloqueia": False}
    return {"estado": BLOQUEADA, "validade": validade, "prazo": prazo, "bloqueia": True}
