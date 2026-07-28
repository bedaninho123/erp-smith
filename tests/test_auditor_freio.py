"""O freio determinístico do Auditor (motor_ia/auditor.py).

Quando o Planejador sinaliza que o atendimento precisa de humano, o
Auditor tem que barrar a resposta **sem consultar a OpenAI** -- é a
única camada do Motor IA que não depende de a IA cooperar. É também o
que sustenta a blindagem contra prompt injection: uma mensagem
maliciosa pode tentar convencer o modelo de qualquer coisa, mas não
consegue negociar com um `if` em Python.

Nenhum teste aqui chama a OpenAI de verdade -- inclusive porque provar
que a chamada NÃO acontece é metade do objetivo.
"""
import pytest

from motor_ia.auditor import auditar
from motor_ia.planejador import Plano, planejar
from motor_ia.classificador import ResultadoClassificacao


def _plano_humano(motivo="Cliente irritado pediu atendente."):
    return Plano(rota="consulta_processo", fontes=[], encaminhar_humano=True, motivo_humano=motivo)


def test_encaminha_humano_sem_chamar_a_openai(monkeypatch):
    """Se este teste algum dia falhar com 'OpenAI foi chamada', alguém
    moveu a checagem determinística pra depois da chamada de IA."""
    def _explode(*args, **kwargs):
        raise AssertionError("OpenAI foi chamada -- o freio determinístico deixou de ser o primeiro passo.")

    monkeypatch.setattr("motor_ia.auditor.OpenAI", _explode)

    resultado = auditar(
        resposta="Seu processo está aprovado!",
        dados={},
        cliente_nome="Ana",
        plano=_plano_humano(),
    )

    assert resultado.acao == "encaminhar_humano"
    assert resultado.aprovado is False


def test_motivo_do_planejador_chega_no_resultado(monkeypatch):
    monkeypatch.setattr("motor_ia.auditor.OpenAI", lambda *a, **k: pytest.fail("não deveria chamar IA"))

    resultado = auditar(
        resposta="qualquer coisa",
        dados={},
        cliente_nome="Ana",
        plano=_plano_humano("Reclamação formal registrada."),
    )

    assert resultado.motivo == "Reclamação formal registrada."


def test_resposta_bonita_nao_burla_o_freio(monkeypatch):
    """A resposta do Redator não tem voto nenhum aqui: por mais correta
    que pareça, se o Planejador pediu humano, ela não sai."""
    monkeypatch.setattr("motor_ia.auditor.OpenAI", lambda *a, **k: pytest.fail("não deveria chamar IA"))

    resultado = auditar(
        resposta=(
            "Olá Ana, tudo certo com seu processo, nenhuma pendência! "
            "Te ajudo em algo mais?"
        ),
        dados={"processos": []},
        cliente_nome="Ana",
        plano=_plano_humano(),
    )

    assert resultado.acao == "encaminhar_humano"


# --------------------------------------------------------------------
# O caminho que leva até o freio: Classificador -> Planejador
# --------------------------------------------------------------------

def _classificacao(intencao, precisa_humano):
    return ResultadoClassificacao(
        intencao=intencao,
        resumo="resumo de teste",
        precisa_humano=precisa_humano,
    )


def test_precisa_humano_do_classificador_vira_encaminhamento():
    """É este o elo que a blindagem de prompt injection protege: uma
    tentativa de manipulação sai do Classificador com precisa_humano, e
    o Planejador transforma isso em encaminhar_humano."""
    plano = planejar(_classificacao("CONSULTA_PROCESSO", precisa_humano=True))

    assert plano.encaminhar_humano is True


def test_intencao_atendimento_humano_encaminha_mesmo_sem_a_flag():
    plano = planejar(_classificacao("ATENDIMENTO_HUMANO", precisa_humano=False))

    assert plano.encaminhar_humano is True


def test_consulta_normal_nao_encaminha():
    """Controle positivo -- sem isso, um Planejador que encaminhasse
    tudo passaria nos dois testes acima."""
    plano = planejar(_classificacao("CONSULTA_DOCUMENTOS", precisa_humano=False))

    assert plano.encaminhar_humano is False
