"""Nome do remetente no e-mail (2026-10-15): o link de acesso do Portal
caía no spam, e um endereço solto sem nome pedindo para clicar num link
é um dos sinais que os filtros pesam. Nada aqui fala com o Gmail de
verdade."""
from email import message_from_bytes
from email.header import decode_header, make_header

from integracoes import gmail


def _from_legivel(mensagem) -> str:
    return str(make_header(decode_header(mensagem["from"])))


def test_nome_com_acento_chega_inteiro_no_remetente():
    msg = gmail.montar_mensagem(
        "cliente@exemplo.com", "Assunto", "Corpo",
        remetente="atendimento@exemplo.com", nome_remetente="Clube São João",
    )
    relido = message_from_bytes(msg.as_bytes())
    assert _from_legivel(relido) == "Clube São João <atendimento@exemplo.com>"


def test_sem_nome_nao_inventa_cabecalho():
    # Quem não passa nome continua como sempre foi: o Gmail preenche.
    msg = gmail.montar_mensagem("cliente@exemplo.com", "Assunto", "Corpo")
    assert msg["from"] is None


class _Resposta:
    def __init__(self, dado):
        self._dado = dado

    def execute(self):
        return self._dado


class _ServicoFalso:
    """Imita só o pedaço da API do Gmail que enviar_email usa."""

    def __init__(self):
        self.enviados = []
        self.perfis_pedidos = 0

    def users(self):
        return self

    def messages(self):
        return self

    def getProfile(self, userId):
        self.perfis_pedidos += 1
        return _Resposta({"emailAddress": "atendimento@exemplo.com"})

    def send(self, userId, body):
        self.enviados.append(body["raw"])
        return _Resposta({"id": "MSG-FALSA"})


def test_enviar_email_usa_o_endereco_da_propria_conta(monkeypatch):
    import base64

    servico = _ServicoFalso()
    monkeypatch.setattr(gmail, "_obter_credenciais", lambda: None)
    monkeypatch.setattr(gmail, "build", lambda *a, **k: servico)
    monkeypatch.setattr(gmail, "_endereco_da_conta", None)

    gmail.enviar_email("cliente@exemplo.com", "Oi", "Corpo", nome_remetente="Smith Clube de Tiro")
    gmail.enviar_email("outro@exemplo.com", "Oi", "Corpo", nome_remetente="Smith Clube de Tiro")

    relido = message_from_bytes(base64.urlsafe_b64decode(servico.enviados[0]))
    assert _from_legivel(relido) == "Smith Clube de Tiro <atendimento@exemplo.com>"
    # O endereço é perguntado uma vez só, não a cada e-mail.
    assert servico.perfis_pedidos == 1
