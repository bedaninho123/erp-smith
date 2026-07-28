"""Autenticação sem senha do Portal do Cliente -- token de uso único
(link mágico), ver docs/portal_cliente_arquitetura.md (decisão 2).
Estado do Core: gera/valida/consome token e localiza cliente por CPF ou
e-mail exato. Não manda e-mail nenhum -- isso é responsabilidade de
quem chama este módulo (ver integracoes/gmail.py), porque o Core não
depende de Integrações (mesma regra já documentada em core/conexao.py).
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.conexao import conectar

TOKEN_VALIDADE_MINUTOS = 15


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(portal_token_id, 5) AS INTEGER)) FROM portal_token"
    ).fetchone()[0] or 0
    return f"PTK-{maior + 1:06d}"


def localizar_cliente_por_cpf_ou_email(empresa_id: str, identificador: str) -> Optional[dict]:
    """Busca exata (nunca aproximada -- diferente de
    motor_ia/identificador_cliente.py, que é do Motor IA e faz busca
    fuzzy por nome pra classificar mensagem de atendimento). Só retorna
    cliente com e-mail cadastrado -- sem e-mail não tem como mandar o
    link (docs/portal_cliente_arquitetura.md, decisão 3).

    Multi-tenant: a busca é dentro de UMA empresa. O mesmo CPF pode
    existir em duas empresas (são cadastros independentes), então sem o
    filtro o Portal de uma mandaria link de acesso para o cliente da
    outra."""
    identificador = (identificador or "").strip()
    if not identificador:
        return None

    con = conectar(empresa_id)
    try:
        linha = None
        cpf_normalizado = re.sub(r"\D", "", identificador)
        if cpf_normalizado:
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND cpf = ? "
                "AND email IS NOT NULL AND email != ''",
                (empresa_id, cpf_normalizado),
            ).fetchone()
        if not linha and "@" in identificador:
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND lower(email) = lower(?) "
                "AND email IS NOT NULL AND email != ''",
                (empresa_id, identificador),
            ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def criar_token(empresa_id: str, cliente_id: str) -> str:
    con = conectar(empresa_id)
    try:
        dono = con.execute(
            "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
            (cliente_id, empresa_id),
        ).fetchone()
        if not dono:
            raise ValueError(f"Cliente não encontrado nesta empresa: {cliente_id}")

        token = secrets.token_urlsafe(32)
        novo_id = _proximo_id(con)
        agora = _agora()
        expira = agora + timedelta(minutes=TOKEN_VALIDADE_MINUTOS)
        con.execute(
            "INSERT INTO portal_token (portal_token_id, empresa_id, token, cliente_id, "
            "criado_em, expira_em, usado_em) VALUES (?,?,?,?,?,?,?)",
            (novo_id, empresa_id, token, cliente_id, _iso(agora), _iso(expira), None),
        )
        con.commit()
        return token
    finally:
        con.close()


def validar_e_consumir_token(empresa_id: str, token: str) -> Optional[str]:
    """Retorna cliente_id se o token existir, ainda não tiver sido usado
    e não estiver expirado -- e já marca como usado (uso único de
    verdade: mesmo token não abre uma segunda sessão). Retorna None pra
    qualquer caso inválido, sem distinguir o motivo pra fora (evita dar
    pista pra quem estiver tentando adivinhar token de outro cliente).

    O token é único globalmente (é segredo de autenticação), mas a
    validação exige a empresa mesmo assim: um token válido apresentado no
    Portal da empresa errada não abre sessão nenhuma."""
    if not token:
        return None
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT * FROM portal_token WHERE token = ? AND empresa_id = ?",
            (token, empresa_id),
        ).fetchone()
        if not linha or linha["usado_em"]:
            return None
        if linha["expira_em"] < _iso(_agora()):
            return None
        con.execute(
            "UPDATE portal_token SET usado_em = ? WHERE portal_token_id = ? AND empresa_id = ?",
            (_iso(_agora()), linha["portal_token_id"], empresa_id),
        )
        con.commit()
        return linha["cliente_id"]
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    cliente = localizar_cliente_por_cpf_ou_email(EMPRESA, "12345678900")
    if not cliente:
        print("Nenhum cliente de teste com esse CPF/e-mail encontrado.")
    else:
        print(f"Cliente encontrado: {cliente['nome']} ({cliente['cliente_id']})")
        token = criar_token(EMPRESA, cliente["cliente_id"])
        print(f"Token gerado: {token[:12]}...")

        cliente_id = validar_e_consumir_token(EMPRESA, token)
        print(f"Primeira validação (deve funcionar): {cliente_id}")

        cliente_id_repetido = validar_e_consumir_token(EMPRESA, token)
        print(f"Segunda validação do mesmo token (deve ser None): {cliente_id_repetido}")

        print(f"Token inválido/inexistente: {validar_e_consumir_token(EMPRESA, 'lixo-nao-existe')}")
