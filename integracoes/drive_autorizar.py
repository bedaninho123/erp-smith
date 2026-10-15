"""Rode este script UMA VEZ (`python -m integracoes.drive_autorizar`)
para autorizar o ERP Smith a guardar o backup de produção no SEU Google
Drive (ver integracoes/google_drive.py).

O que acontece ao rodar:
  1. O terminal mostra um link. Copie e cole no navegador e entre com a
     conta do Google onde os backups devem ficar.
  2. A permissão pedida é a mais restrita do Google Drive: o sistema só
     enxerga a pasta de backup que ele mesmo criar. O resto do seu Drive
     continua invisível pra ele.
  3. Depois de "Permitir", salva drive_token.json na raiz do projeto
     (fora do git). É esse arquivo que vai para o Railway.

Usa o mesmo credentials.json do Gmail (é o "aplicativo" ERP Smith no
Google Cloud); a conta autorizada pode ser outra, e é.
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from integracoes.google_drive import SCOPES, TOKEN_PATH

CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "credentials.json"


def main():
    if not CREDENTIALS_PATH.exists():
        print(f"Não encontrei {CREDENTIALS_PATH} -- é o mesmo arquivo usado pelo Gmail.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    print("Copie o link abaixo e cole no seu navegador para autorizar:\n")
    creds = flow.run_local_server(port=0, open_browser=False)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nAutorização concluída. Token salvo em {TOKEN_PATH}.")


if __name__ == "__main__":
    main()
