"""Motor de Clientes: cria o cliente do despachante. Estado do Core, com
a validação junto -- mesmo padrão de motor_casos.py (status contra lista
controlada) e motor_usuarios.py (papéis).

Por que só agora: até 2026-08-25 o painel não criava cliente nenhum, a
tela de Clientes só listava. Quem cadastrava era script de migração. Isso
deixou de servir quando ficou claro que **não existe base para migrar** --
o despachante atende hoje por pasta de papel e WhatsApp, sem cadastro
nenhum. Então o cliente nasce um a um, no momento em que o primeiro caso
dele é aberto.

`cliente.cpf` é a chave de tudo que vem depois: é por ele que se consulta
habitualidade, CR e arma no Shooting House, e é contra ele que o portão
de identidade confere quem está pedindo dado sensível
(core/motor_identidade.py). CPF errado aqui não é erro de digitação, é
uma consulta que vai buscar a pessoa errada -- daí a validação de dígito
verificador acontecer no cadastro, que é o único lugar do sistema onde
ela faz sentido.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

# Texto livre no schema (sem CHECK), lista controlada aqui -- mesmo
# padrão do resto do Core.
STATUS_VALIDOS = {"Ativo", "Inativo"}


class ClienteInvalido(ValueError):
    """Dado que a pessoa digitou não serve. Mensagem é pra tela."""


class ClienteJaExiste(ValueError):
    """Já existe cliente com este CPF NESTA empresa. Não é erro técnico:
    a UNIQUE é (empresa_id, cpf) justamente porque a mesma pessoa pode
    ser cliente de dois despachantes."""

    def __init__(self, mensagem: str, cliente_id: str):
        super().__init__(mensagem)
        self.cliente_id = cliente_id


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def limpar_cpf(cpf: Optional[str]) -> str:
    return re.sub(r"\D", "", cpf or "")


def cpf_valido(cpf: Optional[str]) -> bool:
    """Confere os dois dígitos verificadores.

    Aqui a validação vale a pena, ao contrário de
    core/motor_identidade.py::extrair_cpfs -- lá o objetivo é achar
    candidatos num texto e a conferência real é contra o cadastro; aqui
    o cadastro É o que está sendo criado, e não há contra o que conferir
    depois. Um dígito trocado passaria a valer como verdade para todas
    as consultas ao Shooting House daquele cliente."""
    digitos = limpar_cpf(cpf)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(
            int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho)
        )
        verificador = (soma * 10) % 11
        if verificador == 10:
            verificador = 0
        if verificador != int(digitos[tamanho]):
            return False
    return True


def criar_cliente(
    empresa_id: str,
    nome: str,
    cpf: str,
    email: Optional[str] = None,
    telefone: Optional[str] = None,
    cidade: Optional[str] = None,
    observacoes: Optional[str] = None,
    status: str = "Ativo",
    atendimento_ia: str = "Sim",
) -> dict:
    """Cria e devolve o cliente. `empresa_id` vem sempre da sessão de
    quem está logado, nunca do formulário."""
    nome = (nome or "").strip()
    if not nome:
        raise ClienteInvalido("Nome é obrigatório.")

    cpf_limpo = limpar_cpf(cpf)
    if not cpf_valido(cpf_limpo):
        raise ClienteInvalido("CPF inválido -- confira os números digitados.")

    if status not in STATUS_VALIDOS:
        raise ClienteInvalido(
            f"Status inválido: {status}. Use um de: {', '.join(sorted(STATUS_VALIDOS))}."
        )

    con = conectar(empresa_id)
    try:
        ja_existe = con.execute(
            "SELECT cliente_id, nome FROM cliente WHERE empresa_id = ? AND cpf = ?",
            (empresa_id, cpf_limpo),
        ).fetchone()
        if ja_existe:
            raise ClienteJaExiste(
                f"Já existe um cliente com este CPF: {ja_existe['nome']}.",
                ja_existe["cliente_id"],
            )

        cliente_id = _proximo_id(con, "cliente", "cliente_id", "CLI")
        agora = _agora_iso()
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, telefone, "
            "cidade, status, atendimento_ia, data_cadastro, observacoes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cliente_id, empresa_id, nome, cpf_limpo, (email or "").strip() or None,
             (telefone or "").strip() or None, (cidade or "").strip() or None,
             status, atendimento_ia, agora, (observacoes or "").strip() or None),
        )
        con.commit()
        return {
            "cliente_id": cliente_id, "empresa_id": empresa_id, "nome": nome,
            "cpf": cpf_limpo, "email": email, "telefone": telefone,
            "cidade": cidade, "status": status, "data_cadastro": agora,
        }
    finally:
        con.close()


# ----------------------------------------------------------------------
# Contato que chegou por e-mail e ainda não informou CPF (2026-10-07).
#
# Até aqui só existia cliente criado à mão, sempre com CPF. Quando a caixa
# do atendimento começou do zero, ficou claro o buraco: e-mail de quem
# ainda não era cliente era lido e descartado em silêncio -- `mensagem` e
# `conversa` exigem um cliente_id, e não havia cliente para apontar.
# Agora o remetente desconhecido vira um cadastro com e-mail e nome, CPF
# vazio, e a mensagem segue o caminho de todo mundo (Aprovações,
# Atendimentos). Quem completa o CPF é uma pessoa da equipe, pela ficha.
#
# CPF vazio não abre nada: o portão de identidade recusa quem não tem CPF
# no cadastro, e o Consultor não consulta o Shooting House sem CPF.
# ----------------------------------------------------------------------

OBSERVACAO_CONTATO_AUTOMATICO = (
    "Cadastro criado automaticamente pelo primeiro e-mail recebido. "
    "Falta informar o CPF."
)

# Parte antes do @ de quem nunca lê resposta: avisos de sistema, alertas
# de segurança do Google, devolução de e-mail. Responder a eles é gastar
# IA à toa, e cadastrá-los encheria a lista de clientes de robô.
_REMETENTE_AUTOMATICO = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|bounces?)([-_.+].*)?$",
    re.IGNORECASE,
)


def remetente_automatico(email: Optional[str]) -> bool:
    local = (email or "").strip().split("@")[0]
    return bool(_REMETENTE_AUTOMATICO.match(local))


def obter_ou_criar_contato_por_email(
    empresa_id: str, email: Optional[str], nome: Optional[str] = None,
) -> Optional[dict]:
    """Cadastro do remetente de e-mail que a identificação não achou.

    Chamado só DEPOIS de `identificar_cliente` não achar ninguém -- nunca
    no lugar dela, senão um cliente antigo escrevendo de outro endereço
    ganharia um cadastro novo em vez de ser reconhecido pelo CPF.

    Devolve None (e não cria nada) quando:
      - não há e-mail, ou o remetente é automático (no-reply e afins);
      - o e-mail já está em DOIS ou mais cadastros. É a identificação
        ambígua (casal que divide o endereço): criar um terceiro só
        aumentaria a confusão, e quem decide de quem é a mensagem é uma
        pessoa.
    Se o e-mail está em exatamente um cadastro, devolve esse -- não
    duplica."""
    email = (email or "").strip()
    if not email or "@" not in email or remetente_automatico(email):
        return None

    con = conectar(empresa_id)
    try:
        existentes = con.execute(
            "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(email) = LOWER(?) LIMIT 2",
            (empresa_id, email),
        ).fetchall()
        if len(existentes) > 1:
            return None
        if existentes:
            return dict(existentes[0])

        nome = (nome or "").strip() or email.split("@")[0]
        cliente_id = _proximo_id(con, "cliente", "cliente_id", "CLI")
        agora = _agora_iso()
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, telefone, "
            "cidade, status, atendimento_ia, data_cadastro, observacoes) "
            "VALUES (?,?,?,NULL,?,NULL,NULL,'Ativo','Sim',?,?)",
            (cliente_id, empresa_id, nome, email, agora, OBSERVACAO_CONTATO_AUTOMATICO),
        )
        con.commit()
        return {
            "cliente_id": cliente_id, "empresa_id": empresa_id, "nome": nome,
            "cpf": None, "email": email, "telefone": None, "cidade": None,
            "status": "Ativo", "data_cadastro": agora,
        }
    finally:
        con.close()


def informar_cpf(empresa_id: str, cliente_id: str, cpf: str) -> dict:
    """Completa o CPF de um cadastro que ainda não tem.

    Só preenche vazio, nunca troca um CPF que já existe: corrigir CPF é
    outra operação, mais perigosa (muda de quem é a habitualidade e o CR
    consultados), e não deve acontecer de carona neste botão.

    CPF que já é de outro cliente levanta `ClienteJaExiste` com o id dele
    -- é o cliente antigo que escreveu de um e-mail novo. Juntar os dois
    é decisão de gente, não deste motor."""
    cpf_limpo = limpar_cpf(cpf)
    if not cpf_valido(cpf_limpo):
        raise ClienteInvalido("CPF inválido -- confira os números digitados.")

    con = conectar(empresa_id)
    try:
        cliente = con.execute(
            "SELECT cliente_id, cpf FROM cliente WHERE empresa_id = ? AND cliente_id = ?",
            (empresa_id, cliente_id),
        ).fetchone()
        if not cliente:
            raise ClienteInvalido("Cliente não encontrado.")
        if cliente["cpf"]:
            raise ClienteInvalido("Este cadastro já tem CPF.")

        outro = con.execute(
            "SELECT cliente_id, nome FROM cliente WHERE empresa_id = ? AND cpf = ?",
            (empresa_id, cpf_limpo),
        ).fetchone()
        if outro:
            raise ClienteJaExiste(
                f"Este CPF já é de outro cliente: {outro['nome']} ({outro['cliente_id']}).",
                outro["cliente_id"],
            )

        con.execute(
            "UPDATE cliente SET cpf = ? WHERE empresa_id = ? AND cliente_id = ?",
            (cpf_limpo, empresa_id, cliente_id),
        )
        con.commit()
        return {"cliente_id": cliente_id, "cpf": cpf_limpo}
    finally:
        con.close()


if __name__ == "__main__":
    # Só lógica, sem tocar no banco -- ver "Quem roda o quê" no CLAUDE.md.
    for cpf in ("529.982.247-25", "111.111.111-11", "123.456.789-00", "5299822472"):
        print(f"{cpf:20} -> válido={cpf_valido(cpf)}")
