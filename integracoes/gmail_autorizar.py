"""Rode este script UMA VEZ (`python -m integracoes.gmail_autorizar`)
para autorizar o ERP Smith a enviar e-mails pela sua conta do Gmail.

Pré-requisito: o arquivo credentials.json precisa estar na raiz do
projeto (baixado do Google Cloud Console -- veja o passo a passo que o
Claude te explicou no chat).

O que acontece ao rodar:
  1. Abre uma aba no seu navegador pedindo para você logar no Google e
     autorizar o acesso (só permissão de ENVIAR e-mail, nada de ler).
  2. Depois de você clicar em "Permitir", salva um arquivo token.json
     na raiz do projeto -- é esse arquivo que os outros módulos usam
     depois, sem precisar repetir esse processo.

token.json nunca é commitado (está no .gitignore).
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from integracoes.gmail import SCOPES, TOKEN_PATH

CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "credentials.json"


def main():
    if not CREDENTIALS_PATH.exists():
        print(
            f"Não encontrei {CREDENTIALS_PATH}.\n"
            "Baixe o arquivo de credenciais OAuth do Google Cloud Console "
            "e salve com esse nome exato na raiz do projeto antes de rodar "
            "este script de novo."
        )
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Autorização concluída. Token salvo em {TOKEN_PATH}.")
    print("Agora os outros módulos já podem enviar e-mail pela sua conta.")


if __name__ == "__main__":
    main()
