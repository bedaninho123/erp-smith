"""O que o despachante sabe de um filiado e o Shooting House não diz.

(2026-09-24.) Pedido do usuário: data de expedição e de vencimento do
CR, e, para cada arma, o número SIGMA e o acervo (Tiro, Caça ou
Coleção). Conferido contra a especificação pública da API antes de
desenhar isto:

- `documents.cr` só tem `status`, `number` e `expirationDate`. **Não há
  data de expedição.** E a `expirationDate` não é confirmadamente o
  vencimento (ver `data_expiracao_bruta` em integracoes/shooting_house.py)
  -- então o vencimento digitado aqui é o que vale na tela, e a data da
  API aparece ao lado só como referência.
- A arma tem `sigma`, mas na resposta real ele veio `None` para a arma
  testada (e só se recupera pela habitualidade, quando a arma já foi
  usada num lançamento). **Acervo não existe em lugar nenhum da API.**

Por isso estas duas tabelas, e não colunas em `filiado`: `filiado` é
ESPELHO do Shooting House, reescrito a cada sincronização. Dado digitado
por gente não pode morar numa linha que uma máquina reescreve -- hoje o
UPDATE da sincronização lista as colunas uma a uma e não apagaria, mas
isso é detalhe de implementação, não garantia.

A ligação é pelo CPF (mesma ponte de `obter_por_cpf`), e a arma é
identificada pelo `id` que o Shooting House dá a ela -- nunca pela série,
que é dado sensível e não precisa ser chave de nada.

Nada daqui é escrito no Shooting House: a integração é somente leitura
(ver tests/test_shooting_house_somente_leitura.py). É anotação NOSSA.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from domain.clube_tiro.documentos_cac import FINALIDADES_ARMA
from domain.clube_tiro.motor_filiados import conectar

# Criadas sob demanda, além de estarem no schema.sql. Produção já
# recebeu duas tabelas atrasadas por migração que ninguém rodou
# (configuracoes, template) -- aqui o próprio motor garante que a tabela
# existe antes de usar, e o esquecimento não tem como acontecer.
_DDL = """
CREATE TABLE IF NOT EXISTS filiado_cr (
    empresa_id       TEXT NOT NULL,
    cpf              TEXT NOT NULL,
    data_expedicao   TEXT,
    data_vencimento  TEXT,
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT,
    PRIMARY KEY (empresa_id, cpf)
);
CREATE TABLE IF NOT EXISTS arma_anotacao (
    empresa_id       TEXT NOT NULL,
    cpf              TEXT NOT NULL,
    arma_id          TEXT NOT NULL,
    sigma            TEXT,
    acervo           TEXT,
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT,
    PRIMARY KEY (empresa_id, cpf, arma_id)
);
"""

_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _conectar():
    con = conectar()
    con.executescript(_DDL)
    return con


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cpf(cpf: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", cpf or "")
    if len(digitos) != 11:
        raise ValueError("CPF inválido.")
    return digitos


def _data(valor: Optional[str], rotulo: str) -> Optional[str]:
    valor = (valor or "").strip()[:10]
    if not valor:
        return None
    if not _RE_DATA.match(valor):
        raise ValueError(f"{rotulo}: use o formato AAAA-MM-DD.")
    return valor


# ---------------------------------------------------------------------
# CR
# ---------------------------------------------------------------------

def obter_cr(empresa_id: str, cpf: str) -> dict:
    """As datas do CR como o despachante cadastrou. Sempre devolve as
    duas chaves -- `None` é "ninguém cadastrou", nunca "não tem"."""
    con = _conectar()
    try:
        linha = con.execute(
            "SELECT data_expedicao, data_vencimento, atualizado_em, atualizado_por "
            "FROM filiado_cr WHERE empresa_id = ? AND cpf = ?",
            (empresa_id, _cpf(cpf)),
        ).fetchone()
    finally:
        con.close()
    if not linha:
        return {"data_expedicao": None, "data_vencimento": None,
                "atualizado_em": None, "atualizado_por": None}
    return dict(linha)


def salvar_cr(
    empresa_id: str, cpf: str, data_expedicao: Optional[str],
    data_vencimento: Optional[str], atualizado_por: Optional[str] = None,
) -> dict:
    expedicao = _data(data_expedicao, "Expedição do CR")
    vencimento = _data(data_vencimento, "Vencimento do CR")
    if expedicao and vencimento and vencimento < expedicao:
        raise ValueError("O vencimento do CR não pode ser antes da expedição.")

    con = _conectar()
    try:
        con.execute(
            "INSERT INTO filiado_cr (empresa_id, cpf, data_expedicao, data_vencimento, "
            "atualizado_em, atualizado_por) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (empresa_id, cpf) DO UPDATE SET "
            "data_expedicao = excluded.data_expedicao, "
            "data_vencimento = excluded.data_vencimento, "
            "atualizado_em = excluded.atualizado_em, "
            "atualizado_por = excluded.atualizado_por",
            (empresa_id, _cpf(cpf), expedicao, vencimento, _agora_iso(), atualizado_por),
        )
        con.commit()
    finally:
        con.close()
    return obter_cr(empresa_id, cpf)


def vencimentos_cr_por_cpf(empresa_id: str) -> dict:
    """{cpf: data_vencimento} de todo mundo que tem vencimento cadastrado
    -- para a lista de Filiados, numa consulta só (mesmo raciocínio de
    `_clientes_por_cpf` no painel: nunca uma consulta por linha)."""
    con = _conectar()
    try:
        return {
            l["cpf"]: l["data_vencimento"]
            for l in con.execute(
                "SELECT cpf, data_vencimento FROM filiado_cr "
                "WHERE empresa_id = ? AND data_vencimento IS NOT NULL",
                (empresa_id,),
            )
        }
    finally:
        con.close()


# ---------------------------------------------------------------------
# Armas
# ---------------------------------------------------------------------

def anotacoes_armas(empresa_id: str, cpf: str) -> dict:
    """{arma_id: {sigma, acervo}} das armas desta pessoa."""
    con = _conectar()
    try:
        return {
            l["arma_id"]: {"sigma": l["sigma"], "acervo": l["acervo"]}
            for l in con.execute(
                "SELECT arma_id, sigma, acervo FROM arma_anotacao "
                "WHERE empresa_id = ? AND cpf = ?",
                (empresa_id, _cpf(cpf)),
            )
        }
    finally:
        con.close()


def salvar_arma(
    empresa_id: str, cpf: str, arma_id, sigma: Optional[str],
    acervo: Optional[str], atualizado_por: Optional[str] = None,
) -> dict:
    arma_id = str(arma_id or "").strip()
    if not arma_id:
        raise ValueError("Arma não identificada.")
    acervo = (acervo or "").strip() or None
    # Aqui a lista É validada, ao contrário do dossiê: lá é rótulo de
    # arquivo e texto livre faz sentido; aqui é o campo que responde "a
    # que acervo esta arma pertence", e "tiro" / "Tiro esportivo" / "TIRO"
    # virariam três acervos diferentes em qualquer contagem.
    if acervo and acervo not in FINALIDADES_ARMA:
        raise ValueError(f"Acervo inválido. Use um de: {', '.join(FINALIDADES_ARMA)}.")
    sigma = (sigma or "").strip() or None

    con = _conectar()
    try:
        con.execute(
            "INSERT INTO arma_anotacao (empresa_id, cpf, arma_id, sigma, acervo, "
            "atualizado_em, atualizado_por) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (empresa_id, cpf, arma_id) DO UPDATE SET "
            "sigma = excluded.sigma, acervo = excluded.acervo, "
            "atualizado_em = excluded.atualizado_em, "
            "atualizado_por = excluded.atualizado_por",
            (empresa_id, _cpf(cpf), arma_id, sigma, acervo, _agora_iso(), atualizado_por),
        )
        con.commit()
    finally:
        con.close()
    return {"sigma": sigma, "acervo": acervo}


def mesclar_armas(armas: list, anotacoes: dict) -> list:
    """Junta o que veio do Shooting House com o que foi cadastrado aqui.

    O SIGMA da API, quando vem, ganha do digitado: é a fonte oficial, e
    uma digitação velha não pode esconder o número certo. O digitado só
    preenche o buraco -- e a tela sabe de onde veio cada um
    (`sigma_origem`), para não apresentar como oficial o que alguém
    digitou.
    """
    saida = []
    for arma in armas or []:
        nota = anotacoes.get(str(arma.get("id"))) or {}
        sigma_api = arma.get("sigma")
        saida.append({
            **arma,
            "sigma": sigma_api or nota.get("sigma"),
            "sigma_origem": "api" if sigma_api else ("manual" if nota.get("sigma") else None),
            "sigma_manual": nota.get("sigma"),
            "acervo": nota.get("acervo"),
        })
    return saida
