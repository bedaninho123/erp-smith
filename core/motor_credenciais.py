"""Senha do gov.br do cliente -- o dado mais perigoso que o sistema guarda.

(2026-09-24.) Pedido do usuário: o despachante faz pelo cliente os
pedidos que exigem entrar no gov.br (a revalidação do CR, por exemplo) e
precisa ter a senha à mão, "registrada junto dos dados dos clientes e
filiados". Antes disso ela era um item de checklist ("Senha gov.br") que
nunca poderia receber documento.

Por que este módulo é mais fechado que qualquer outro:

A senha do gov.br não é dado SOBRE a pessoa, é a CHAVE da vida digital
dela -- Receita, INSS, SINARM, assinatura digital. Vazar um CPF expõe;
vazar esta senha deixa alguém agir como ela. Daí quatro regras:

1. **Cifrada no banco** (Fernet, AES + HMAC). A chave vive em
   `ERP_CHAVE_SENHAS`, variável de ambiente, NUNCA no banco nem no
   código: quem levar o arquivo .db ou um backup leva texto ilegível.
   Sem a chave configurada, gravar e revelar RECUSAM (falha fechado) em
   vez de guardar em texto puro "por enquanto".
2. **Nunca sai em listagem.** `situacao()` diz só SE existe e quem
   cadastrou; o valor só sai por `revelar()`, uma pessoa, um pedido.
3. **Todo revelar deixa rastro** em `log_administrativo`
   (`SENHA_GOVBR_REVELADA`), na mesma transação -- a senha não sai sem o
   registro ter sido gravado. Cadastrar e trocar também registram. O
   valor em si nunca vai para o log.
4. **Fora do alcance da IA e do Portal.** Nenhuma view do Core lê esta
   tabela, e nenhum módulo de motor_ia/ ou portal/ importa este.

PERDER A CHAVE É PERDER TODAS AS SENHAS. Ela precisa estar guardada fora
do servidor também (é o único jeito de ler um backup restaurado).
"""
import os
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar
from core.motor_log_administrativo import registrar

VARIAVEL_CHAVE = "ERP_CHAVE_SENHAS"
TIPO_GOVBR = "gov.br"

_DDL = """
CREATE TABLE IF NOT EXISTS credencial_cliente (
    empresa_id       TEXT NOT NULL,
    cliente_id       TEXT NOT NULL,
    tipo             TEXT NOT NULL,          -- 'gov.br'
    segredo_cifrado  TEXT NOT NULL,          -- Fernet; nunca o valor puro
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT NOT NULL,
    PRIMARY KEY (empresa_id, cliente_id, tipo)
);
"""


class ChaveNaoConfigurada(RuntimeError):
    """`ERP_CHAVE_SENHAS` ausente ou inválida. Falha fechado."""


def _fernet():
    from cryptography.fernet import Fernet

    chave = (os.environ.get(VARIAVEL_CHAVE) or "").strip()
    if not chave:
        raise ChaveNaoConfigurada(
            "A chave de criptografia das senhas (ERP_CHAVE_SENHAS) não está "
            "configurada neste servidor. Nenhuma senha pode ser guardada nem lida."
        )
    try:
        return Fernet(chave.encode())
    except (ValueError, TypeError):
        raise ChaveNaoConfigurada("ERP_CHAVE_SENHAS está em formato inválido.") from None


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conectar(empresa_id: str):
    con = conectar(empresa_id)
    con.executescript(_DDL)
    return con


def _cliente_da_empresa(con, empresa_id: str, cliente_id: str) -> None:
    if not con.execute(
        "SELECT 1 FROM cliente WHERE cliente_id = ? AND empresa_id = ?",
        (cliente_id, empresa_id),
    ).fetchone():
        raise ValueError(f"Cliente não encontrado nesta empresa: {cliente_id}")


def situacao(empresa_id: str, cliente_id: Optional[str]) -> dict:
    """Se há senha cadastrada, e por quem -- NUNCA o valor."""
    vazio = {"cadastrada": False, "atualizado_em": None, "atualizado_por": None}
    if not cliente_id:
        return vazio
    con = _conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT atualizado_em, atualizado_por FROM credencial_cliente "
            "WHERE empresa_id = ? AND cliente_id = ? AND tipo = ?",
            (empresa_id, cliente_id, TIPO_GOVBR),
        ).fetchone()
    finally:
        con.close()
    if not linha:
        return vazio
    return {"cadastrada": True, "atualizado_em": linha["atualizado_em"],
            "atualizado_por": linha["atualizado_por"]}


def salvar(empresa_id: str, cliente_id: str, senha: str, por: str) -> None:
    """Cadastra ou troca. Senha vazia é recusada -- para apagar, `remover()`."""
    if not (senha or "").strip():
        raise ValueError("Digite a senha.")
    cifrada = _fernet().encrypt(senha.encode("utf-8")).decode("ascii")

    con = _conectar(empresa_id)
    try:
        _cliente_da_empresa(con, empresa_id, cliente_id)
        existia = con.execute(
            "SELECT 1 FROM credencial_cliente WHERE empresa_id = ? AND cliente_id = ? AND tipo = ?",
            (empresa_id, cliente_id, TIPO_GOVBR),
        ).fetchone()
        con.execute(
            "INSERT INTO credencial_cliente (empresa_id, cliente_id, tipo, segredo_cifrado, "
            "atualizado_em, atualizado_por) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (empresa_id, cliente_id, tipo) DO UPDATE SET "
            "segredo_cifrado = excluded.segredo_cifrado, "
            "atualizado_em = excluded.atualizado_em, atualizado_por = excluded.atualizado_por",
            (empresa_id, cliente_id, TIPO_GOVBR, cifrada, _agora_iso(), por),
        )
        registrar(
            con, empresa_id, "SENHA_GOVBR_ALTERADA" if existia else "SENHA_GOVBR_CADASTRADA",
            cliente_id, "Senha do gov.br " + ("trocada" if existia else "cadastrada"),
            None, None, por,
        )
        con.commit()
    finally:
        con.close()


def revelar(empresa_id: str, cliente_id: str, por: str) -> Optional[str]:
    """O valor da senha, ou None se não há. Registra ANTES de devolver:
    se o registro falhar, a senha não sai."""
    fernet = _fernet()
    con = _conectar(empresa_id)
    try:
        _cliente_da_empresa(con, empresa_id, cliente_id)
        linha = con.execute(
            "SELECT segredo_cifrado FROM credencial_cliente "
            "WHERE empresa_id = ? AND cliente_id = ? AND tipo = ?",
            (empresa_id, cliente_id, TIPO_GOVBR),
        ).fetchone()
        if not linha:
            return None
        registrar(con, empresa_id, "SENHA_GOVBR_REVELADA", cliente_id,
                  "Senha do gov.br exibida na tela", None, None, por)
        con.commit()
    finally:
        con.close()

    from cryptography.fernet import InvalidToken
    try:
        return fernet.decrypt(linha["segredo_cifrado"].encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Cifrada com outra chave (chave trocada ou banco de outro
        # servidor). Dizer isso é melhor que um 500 -- e nunca devolver
        # lixo como se fosse a senha.
        raise ChaveNaoConfigurada(
            "Esta senha foi guardada com outra chave de criptografia e não pode ser lida aqui."
        ) from None


def remover(empresa_id: str, cliente_id: str, por: str) -> bool:
    con = _conectar(empresa_id)
    try:
        _cliente_da_empresa(con, empresa_id, cliente_id)
        apagou = con.execute(
            "DELETE FROM credencial_cliente WHERE empresa_id = ? AND cliente_id = ? AND tipo = ?",
            (empresa_id, cliente_id, TIPO_GOVBR),
        ).rowcount
        if apagou:
            registrar(con, empresa_id, "SENHA_GOVBR_REMOVIDA", cliente_id,
                      "Senha do gov.br removida", None, None, por)
        con.commit()
        return bool(apagou)
    finally:
        con.close()
