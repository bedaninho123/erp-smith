"""Envio do backup de produção para o Google Drive (2026-10-14).

Por que existe: o backup diário do Railway (webapp/servir.py) gravava no
MESMO volume onde o banco mora, e sem os documentos dos clientes. Se o
volume se perdesse, ia junto o banco, os documentos e o backup. Este
módulo leva uma cópia completa, todo dia, para fora do Railway.

Conta: a pessoal do dono (decisão do usuário em 2026-10-14), autorizada
uma vez por `python -m integracoes.drive_autorizar`. Escopo `drive.file`,
o mais restrito que o Google tem: o sistema só enxerga o que ele mesmo
criou (a pasta de backup e os arquivos dela), nunca o resto do Drive.

Token separado do Gmail (ERP_DRIVE_TOKEN_PATH, padrão drive_token.json
na raiz, fora do git): são contas diferentes, e uma autorização vencida
não pode derrubar a outra. Na hospedagem o caminho aponta para o volume
(/data), porque o token é reescrito ao renovar.

Se o arquivo ainda não existe no volume e a variável ERP_DRIVE_TOKEN_JSON
estiver definida, ele nasce dela -- é como o token chega ao Railway sem
precisar copiar arquivo por SSH. Autorização nova na variável (outro
`refresh_token`) substitui o arquivo; ver `_semear_token_do_ambiente`.
"""
import json
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_PATH = Path(
    os.environ.get("ERP_DRIVE_TOKEN_PATH")
    or (Path(__file__).resolve().parent.parent / "drive_token.json")
)
PASTA_BACKUP = "ERP Smith - Backups Produção"
MIME_PASTA = "application/vnd.google-apps.folder"


def _refresh_token(conteudo: str) -> Optional[str]:
    try:
        return json.loads(conteudo).get("refresh_token")
    except (ValueError, AttributeError):
        return None


def _semear_token_do_ambiente() -> None:
    """O arquivo nasce da variável e, dali em diante, só é trocado por ela
    quando a AUTORIZAÇÃO mudou -- outro `refresh_token`. Renovar mexe só
    no `token` de acesso, então o arquivo renovado continua valendo mais
    que o da variável. Sem a troca, revogar o acesso e autorizar de novo
    (incidente do Railway, 2026-10-22) não tinha efeito: o volume seguia
    lendo o token revogado e a variável nova era ignorada."""
    conteudo = os.environ.get("ERP_DRIVE_TOKEN_JSON", "").strip()
    if not conteudo:
        return
    if TOKEN_PATH.exists():
        do_arquivo = _refresh_token(TOKEN_PATH.read_text(encoding="utf-8"))
        do_ambiente = _refresh_token(conteudo)
        if do_ambiente is None or do_ambiente == do_arquivo:
            return
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(conteudo, encoding="utf-8")


def drive_configurado() -> bool:
    _semear_token_do_ambiente()
    return TOKEN_PATH.exists()


def _servico():
    _semear_token_do_ambiente()
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _id_da_pasta(servico) -> str:
    # Com drive.file a busca só enxerga o que este app criou: uma pasta
    # de mesmo nome feita à mão pela pessoa não é confundida com esta.
    nome = PASTA_BACKUP.replace("'", "\\'")
    achadas = servico.files().list(
        q=f"name = '{nome}' and mimeType = '{MIME_PASTA}' and trashed = false",
        fields="files(id)", spaces="drive",
    ).execute().get("files", [])
    if achadas:
        return achadas[0]["id"]
    return servico.files().create(
        body={"name": PASTA_BACKUP, "mimeType": MIME_PASTA}, fields="id",
    ).execute()["id"]


def enviar_backup(arquivo: Path, manter_ultimos: int) -> dict:
    """Sobe `arquivo` para a pasta de backup e apaga os mais antigos além
    de `manter_ultimos`. Apagar só DEPOIS de o novo ter subido inteiro:
    se o envio cai no meio, os 14 anteriores continuam lá."""
    servico = _servico()
    pasta = _id_da_pasta(servico)
    midia = MediaFileUpload(str(arquivo), mimetype="application/zip", resumable=True)
    enviado = servico.files().create(
        body={"name": arquivo.name, "parents": [pasta]}, media_body=midia, fields="id, size",
    ).execute()

    arquivos = servico.files().list(
        q=f"'{pasta}' in parents and trashed = false",
        orderBy="createdTime desc", fields="files(id, name)", pageSize=1000,
    ).execute().get("files", [])
    apagados: list[str] = []
    for antigo in arquivos[manter_ultimos:]:
        # delete (não lixeira): na lixeira o arquivo continua ocupando
        # espaço da conta por 30 dias, e o motivo da rotação é espaço.
        servico.files().delete(fileId=antigo["id"]).execute()
        apagados.append(antigo["name"])
    return {"id": enviado["id"], "tamanho": int(enviado.get("size") or 0), "apagados": apagados}


def servico():
    """O cliente da API, para quem faz várias operações seguidas (o
    espelho de documentos) sem renovar o token a cada uma."""
    return _servico()


def pasta_utilizavel(servico, pasta_id: str) -> bool:
    """A pasta ainda existe e não está na lixeira? A pessoa pode apagar
    pelo Drive uma pasta que o sistema criou; aí ela é criada de novo, em
    vez de os arquivos irem para dentro de algo que ninguém vê."""
    from googleapiclient.errors import HttpError

    try:
        dados = servico.files().get(fileId=pasta_id, fields="trashed").execute()
    except HttpError as e:
        if getattr(e, "status_code", None) == 404 or getattr(getattr(e, "resp", None), "status", None) == 404:
            return False
        raise
    return not dados.get("trashed")


def criar_pasta(servico, nome: str, pai_id: Optional[str] = None) -> str:
    corpo = {"name": nome, "mimeType": MIME_PASTA}
    if pai_id:
        corpo["parents"] = [pai_id]
    return servico.files().create(body=corpo, fields="id").execute()["id"]


def renomear(servico, arquivo_id: str, nome: str) -> None:
    servico.files().update(fileId=arquivo_id, body={"name": nome}, fields="id").execute()


def enviar_arquivo(servico, caminho: Path, nome: str, pasta_id: str, mimetype: str) -> str:
    midia = MediaFileUpload(str(caminho), mimetype=mimetype, resumable=True)
    return servico.files().create(
        body={"name": nome, "parents": [pasta_id]}, media_body=midia, fields="id",
    ).execute()["id"]


def listar_backups() -> Optional[list[dict]]:
    """Para conferir de fora (diagnóstico): nome, data e tamanho, sem
    baixar nada. None quando o Drive não está autorizado."""
    if not drive_configurado():
        return None
    servico = _servico()
    pasta = _id_da_pasta(servico)
    return servico.files().list(
        q=f"'{pasta}' in parents and trashed = false",
        orderBy="createdTime desc", fields="files(name, createdTime, size)", pageSize=1000,
    ).execute().get("files", [])
