"""Cópia de cada documento numa pasta com o nome do cliente, no Google
Drive (2026-10-20).

Pedido do usuário: achar os documentos de uma pessoa no Drive sem abrir
backup nenhum. O backup diário (.zip com tudo, 14 dias) continua
existindo e é outra coisa: aquele serve para restaurar o sistema inteiro;
este serve para uma pessoa abrir a pasta "Helena Costa" e ver os
arquivos dela.

    ERP Smith - Documentos dos Clientes/
        Helena Costa (CLI-000001)/
            2026-10-20 - CRAF — Certificado de Registro... (DOC-000123).pdf

Decisões:

- **Roda em segundo plano** (webapp/servir.py, a cada 10 min), nunca na
  hora do envio. Documento entra por quatro caminhos (painel, Portal,
  e-mail, dossiê); uma rotina só pega todos, e o Drive fora do ar nunca
  impede ninguém de subir um arquivo.
- **Nada sobe duas vezes** (`drive_documento`), e o que falhou sobe na
  rodada seguinte -- falha de um arquivo não para os outros.
- **Apagar no painel NÃO apaga no Drive.** A cópia é de segurança; um
  clique errado no painel não pode levar o arquivo junto.
- **O nome da pasta leva o código do cliente**: dois "João Silva" são
  comuns, e duas pastas com o mesmo nome no Drive seriam indistinguíveis.
  Se o nome do cliente mudar no cadastro, a pasta é renomeada.
- Mesma conta e mesma permissão do backup (`drive.file`): o sistema só
  enxerga as pastas que ele mesmo criou.

Só roda em produção (pela thread de webapp/servir.py). Não há comando de
terminal de propósito: rodado no PC, mandaria os documentos do banco
LOCAL para o mesmo Drive da produção, misturando os dois.
"""
import mimetypes
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.conexao import conectar
from integracoes import google_drive

PASTA_RAIZ = "ERP Smith - Documentos dos Clientes"
LIMITE_POR_RODADA = 50


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nome_pasta_cliente(nome: str, cliente_id: str) -> str:
    return f"{(nome or 'Sem nome').strip()} ({cliente_id})"


def nome_arquivo(documento: dict) -> str:
    """Data primeiro, para a pasta ficar em ordem cronológica; o código do
    documento no fim, para dois arquivos do mesmo tipo no mesmo dia não
    terem o mesmo nome."""
    data = (documento.get("data_envio") or "")[:10] or "sem data"
    tipo = (documento.get("tipo_documento") or "Documento").replace("/", "-").strip()
    extensao = Path(documento.get("nome_arquivo") or documento.get("link_arquivo") or "").suffix.lower()
    return f"{data} - {tipo} ({documento['documento_id']}){extensao}"


def _pasta(con, servico, empresa_id: str, chave: str, nome: str, pai_id, conferidas: set) -> str:
    """Id da pasta `chave` ('raiz' ou o cliente_id), criando ou renomeando
    se preciso. `conferidas` evita perguntar ao Drive mais de uma vez por
    rodada se a mesma pasta ainda existe."""
    linha = con.execute(
        "SELECT drive_pasta_id, nome FROM drive_pasta WHERE empresa_id = ? AND chave = ?",
        (empresa_id, chave),
    ).fetchone()
    if linha and (linha["drive_pasta_id"] in conferidas
                  or google_drive.pasta_utilizavel(servico, linha["drive_pasta_id"])):
        conferidas.add(linha["drive_pasta_id"])
        if linha["nome"] != nome:
            google_drive.renomear(servico, linha["drive_pasta_id"], nome)
            con.execute(
                "UPDATE drive_pasta SET nome = ? WHERE empresa_id = ? AND chave = ?",
                (nome, empresa_id, chave),
            )
            con.commit()
        return linha["drive_pasta_id"]

    pasta_id = google_drive.criar_pasta(servico, nome, pai_id)
    conferidas.add(pasta_id)
    con.execute(
        "INSERT OR REPLACE INTO drive_pasta (empresa_id, chave, drive_pasta_id, nome) VALUES (?,?,?,?)",
        (empresa_id, chave, pasta_id, nome),
    )
    con.commit()
    return pasta_id


def espelhar(empresa_id: str, limite: int = LIMITE_POR_RODADA) -> dict:
    """Uma rodada: sobe até `limite` documentos que ainda não estão no
    Drive. Devolve {enviados, falhas, sem_arquivo, faltando}: `falhas` é
    erro do Drive (vale alarme), `sem_arquivo` é linha do banco cujo
    arquivo sumiu do disco (não é culpa do Drive, e insistir não resolve).
    Sem Drive autorizado, levanta RuntimeError -- quem chama decide se
    isso é alarme."""
    if not google_drive.drive_configurado():
        raise RuntimeError("Google Drive não autorizado (ver integracoes/drive_autorizar.py).")

    con = conectar(empresa_id)
    try:
        pendentes = [dict(l) for l in con.execute(
            "SELECT d.documento_id, d.tipo_documento, d.nome_arquivo, d.link_arquivo, "
            "d.data_envio, d.cliente_id, c.nome AS cliente_nome "
            "FROM documento d JOIN cliente c ON c.cliente_id = d.cliente_id AND c.empresa_id = d.empresa_id "
            "WHERE d.empresa_id = ? AND d.link_arquivo IS NOT NULL "
            "AND d.documento_id NOT IN (SELECT documento_id FROM drive_documento WHERE empresa_id = ?) "
            "ORDER BY d.data_envio",
            (empresa_id, empresa_id),
        ).fetchall()]
        # Linha sem arquivo em disco sai da fila antes de contar o limite:
        # senão, cinquenta delas travariam a rodada para sempre.
        # core.db.auditar_documentos é quem denuncia essas linhas.
        sem_arquivo = [d for d in pendentes if not Path(d["link_arquivo"]).is_file()]
        pendentes = [d for d in pendentes if Path(d["link_arquivo"]).is_file()]
        if not pendentes:
            return {"enviados": 0, "falhas": 0, "sem_arquivo": len(sem_arquivo), "faltando": 0}

        servico = google_drive.servico()
        conferidas: set = set()
        raiz = _pasta(con, servico, empresa_id, "raiz", PASTA_RAIZ, None, conferidas)
        enviados = falhas = 0
        for documento in pendentes[:limite]:
            caminho = Path(documento["link_arquivo"])
            try:
                pasta = _pasta(
                    con, servico, empresa_id, documento["cliente_id"],
                    nome_pasta_cliente(documento["cliente_nome"], documento["cliente_id"]),
                    raiz, conferidas,
                )
                arquivo_id = google_drive.enviar_arquivo(
                    servico, caminho, nome_arquivo(documento), pasta,
                    mimetypes.guess_type(caminho.name)[0] or "application/octet-stream",
                )
                con.execute(
                    "INSERT INTO drive_documento (documento_id, empresa_id, drive_arquivo_id, enviado_em) "
                    "VALUES (?,?,?,?)",
                    (documento["documento_id"], empresa_id, arquivo_id, _agora_iso()),
                )
                con.commit()
                enviados += 1
            except Exception:
                # Um arquivo que falha não para os outros; ele tenta de
                # novo na próxima rodada, porque não entrou em drive_documento.
                traceback.print_exc()
                falhas += 1
        return {"enviados": enviados, "falhas": falhas, "sem_arquivo": len(sem_arquivo),
                "faltando": max(len(pendentes) - limite, 0) + falhas}
    finally:
        con.close()
