"""Convite por e-mail: a própria pessoa cria a senha do painel (2026-10-20).

Até aqui a senha só nascia por `webapp/definir_senha.py`, rodado no
terminal -- o que, com o painel no Railway, significava ninguém novo
conseguir entrar sem alguém abrir um terminal no servidor. Pedido do
usuário: criar um Gestor e ele entrar sem depender disso.

A regra que vinha de antes CONTINUA valendo, só ganhou uma segunda porta:
**a senha é sempre definida pela própria pessoa, nunca por quem a
cadastrou.** O Gestor manda o link; quem escolhe a senha é o dono do
e-mail. O mesmo link serve de "Esqueci minha senha" na tela de login.

Travas, todas aqui e não na rota:

- **Uso único**, e pedir um link novo mata os anteriores ainda não usados
  -- um convite esquecido numa caixa de e-mail antiga não fica valendo.
- **Prazo**: o que o Gestor manda vale `VALIDADE_CONVITE_HORAS` (a pessoa
  pode demorar a abrir o e-mail); o "Esqueci minha senha" vale
  `VALIDADE_REDEFINICAO_MINUTOS` (quem pediu está com a tela aberta agora).
- **Só o hash do link vai para o banco.** Quem ler o banco (ou um backup
  dele no Drive) não consegue usar link nenhum.
- **Usuário desativado ou empresa desativada** não usa link, mesmo
  dentro do prazo: desativar tem que fechar todas as portas.
- Criar e usar ficam no `log_administrativo`, na mesma transação.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from werkzeug.security import generate_password_hash

from core.conexao import conectar, conectar_admin
from core.motor_log_administrativo import registrar as registrar_log

MOTIVO_CONVITE = "convite"
MOTIVO_REDEFINICAO = "redefinicao"

VALIDADE_CONVITE_HORAS = 48
VALIDADE_REDEFINICAO_MINUTOS = 60

SENHA_TAMANHO_MINIMO = 8


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _proximo_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(usuario_convite_id, 5) AS INTEGER)) FROM usuario_convite"
    ).fetchone()[0] or 0
    return f"UCV-{maior + 1:06d}"


def criar_link(
    empresa_id: str, usuario_id: str, motivo: str, pedido_por: str,
    pela_tela_de_login: bool = False,
) -> dict:
    """Gera o link de uso único. Devolve o token em claro UMA vez, para ir
    no e-mail -- o banco só fica com o hash. Mata os links anteriores
    desta pessoa que ainda não foram usados.

    O prazo depende de QUEM pediu, não do motivo: o "Esqueci minha senha"
    da tela de login é pedido por quem está com a tela aberta (prazo
    curto); o que o Gestor manda pode ficar horas na caixa de entrada."""
    if motivo not in (MOTIVO_CONVITE, MOTIVO_REDEFINICAO):
        raise ValueError(f"Motivo inválido: {motivo}")

    con = conectar(empresa_id)
    try:
        usuario = con.execute(
            "SELECT usuario_id, nome, email, ativo FROM usuario "
            "WHERE usuario_id = ? AND empresa_id = ?",
            (usuario_id, empresa_id),
        ).fetchone()
        if not usuario:
            raise ValueError(f"Usuário não encontrado: {usuario_id}")
        if usuario["ativo"] != "Sim":
            raise ValueError("Usuário desativado. Reative antes de enviar o convite.")

        agora = _agora()
        validade = (
            timedelta(minutes=VALIDADE_REDEFINICAO_MINUTOS) if pela_tela_de_login
            else timedelta(hours=VALIDADE_CONVITE_HORAS)
        )
        expira = agora + validade
        token = secrets.token_urlsafe(32)

        con.execute(
            "UPDATE usuario_convite SET invalidado_em = ? "
            "WHERE usuario_id = ? AND empresa_id = ? AND usado_em IS NULL AND invalidado_em IS NULL",
            (_iso(agora), usuario_id, empresa_id),
        )
        con.execute(
            "INSERT INTO usuario_convite (usuario_convite_id, empresa_id, usuario_id, "
            "token_hash, motivo, criado_em, expira_em) VALUES (?,?,?,?,?,?,?)",
            (_proximo_id(con), empresa_id, usuario_id, _hash_token(token), motivo,
             _iso(agora), _iso(expira)),
        )
        registrar_log(
            con, empresa_id,
            "CONVITE_SENHA_ENVIADO" if motivo == MOTIVO_CONVITE else "REDEFINICAO_SENHA_PEDIDA",
            usuario_id,
            f"Link para criar senha enviado para {usuario['email']}",
            None, _iso(expira), pedido_por,
        )
        con.commit()
        return {
            "token": token, "expira_em": _iso(expira), "motivo": motivo,
            "nome": usuario["nome"], "email": usuario["email"],
        }
    finally:
        con.close()


def _link_valido(con, token: str) -> Optional[dict]:
    """A linha do link, se ele ainda serve. Procura pelo hash no banco
    inteiro: como no login, é o próprio link que diz de que empresa a
    pessoa é -- nada digitado na tela escolhe a empresa."""
    linha = con.execute(
        "SELECT c.usuario_convite_id, c.empresa_id, c.usuario_id, c.motivo, c.expira_em, "
        "u.nome, u.email FROM usuario_convite c "
        "JOIN usuario u ON u.usuario_id = c.usuario_id AND u.empresa_id = c.empresa_id "
        "JOIN empresa e ON e.empresa_id = c.empresa_id "
        "WHERE c.token_hash = ? AND c.usado_em IS NULL AND c.invalidado_em IS NULL "
        "AND u.ativo = 'Sim' AND e.ativo = 'Sim'",
        (_hash_token(token or ""),),
    ).fetchone()
    if not linha or linha["expira_em"] <= _iso(_agora()):
        return None
    return dict(linha)


def conferir_link(token: str) -> Optional[dict]:
    """Nome e e-mail de quem vai criar a senha, ou None se o link não
    serve mais (usado, vencido, substituído, pessoa desativada)."""
    con = conectar_admin()
    try:
        linha = _link_valido(con, token)
        return {"nome": linha["nome"], "email": linha["email"], "motivo": linha["motivo"]} if linha else None
    finally:
        con.close()


def validar_senha(senha: str, email: str) -> Optional[str]:
    """Mensagem de erro, ou None se a senha serve."""
    if len(senha or "") < SENHA_TAMANHO_MINIMO:
        return f"A senha precisa ter pelo menos {SENHA_TAMANHO_MINIMO} caracteres."
    if senha.strip().lower() == (email or "").strip().lower():
        return "A senha não pode ser o seu e-mail."
    return None


def definir_senha(token: str, senha: str) -> dict:
    """Grava a senha e consome o link, na mesma transação. Levanta
    ValueError com mensagem para a tela quando algo não serve."""
    con = conectar_admin()
    try:
        linha = _link_valido(con, token)
        if not linha:
            raise ValueError("Este link não vale mais. Peça um novo.")
        erro = validar_senha(senha, linha["email"])
        if erro:
            raise ValueError(erro)

        agora = _iso(_agora())
        # O WHERE repete "não usado": dois cliques no mesmo link ao mesmo
        # tempo não podem os dois gravar senha.
        consumido = con.execute(
            "UPDATE usuario_convite SET usado_em = ? "
            "WHERE usuario_convite_id = ? AND usado_em IS NULL AND invalidado_em IS NULL",
            (agora, linha["usuario_convite_id"]),
        ).rowcount
        if not consumido:
            raise ValueError("Este link não vale mais. Peça um novo.")
        con.execute(
            "UPDATE usuario SET senha_hash = ? WHERE usuario_id = ? AND empresa_id = ?",
            (generate_password_hash(senha), linha["usuario_id"], linha["empresa_id"]),
        )
        registrar_log(
            con, linha["empresa_id"], "SENHA_DEFINIDA_POR_LINK", linha["usuario_id"],
            "Senha do painel criada pela própria pessoa, pelo link do e-mail",
            None, linha["motivo"], linha["nome"],
        )
        con.commit()
        return {"email": linha["email"], "nome": linha["nome"]}
    finally:
        con.close()


def usuario_para_redefinir(email: str) -> Optional[dict]:
    """Quem pede "Esqueci minha senha": mesma busca do login (e-mail,
    usuário ativo, empresa ativa). None não é dito na tela -- a resposta é
    a mesma com ou sem cadastro, senão a tela viraria um verificador de
    e-mail."""
    con = conectar_admin()
    try:
        linha = con.execute(
            "SELECT u.usuario_id, u.empresa_id FROM usuario u "
            "JOIN empresa e ON e.empresa_id = u.empresa_id "
            "WHERE lower(u.email) = ? AND u.ativo = 'Sim' AND e.ativo = 'Sim'",
            ((email or "").strip().lower(),),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def convites_pendentes(empresa_id: str) -> dict:
    """{usuario_id: expira_em} do link ainda válido de cada pessoa, para a
    tela de Usuários dizer "convite enviado, vale até...". """
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT usuario_id, MAX(expira_em) AS expira_em FROM usuario_convite "
            "WHERE empresa_id = ? AND usado_em IS NULL AND invalidado_em IS NULL "
            "AND expira_em > ? GROUP BY usuario_id",
            (empresa_id, _iso(_agora())),
        ).fetchall()
        return {l["usuario_id"]: l["expira_em"] for l in linhas}
    finally:
        con.close()
