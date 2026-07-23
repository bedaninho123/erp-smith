"""Rode este script UMA VEZ (`python -m integracoes.gmail_autorizar`)
para autorizar o ERP Smith a enviar e-mails pela sua conta do Gmail.

Pré-requisito: o arquivo credentials.json precisa estar na raiz do
projeto (baixado do Google Cloud Console -- veja o passo a passo que o
Claude te explicou no chat).

O que acontece ao rodar:
  1. O terminal mostra um link. Copie e cole esse link no seu navegador
     (não depende de abrir sozinho -- mais confiável em qualquer
     máquina). Faça login no Google e autorize o acesso (só permissão
     de ENVIAR e-mail, nada de ler).
  2. Depois de clicar em "Permitir", salva um arquivo token.json na
     raiz do projeto -- é esse arquivo que os outros módulos usam
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
    # open_browser=False força a biblioteca a sempre IMPRIMIR o link em
    # vez de só tentar abrir sozinha -- evita ficar travado em silêncio
    # quando o navegador padrão não abre automaticamente.
    print("Copie o link abaixo e cole no seu navegador para autorizar:\n")
    creds = flow.run_local_server(port=0, open_browser=False)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nAutorização concluída. Token salvo em {TOKEN_PATH}.")
    print("Agora os outros módulos já podem enviar e-mail pela sua conta.")


if __name__ == "__main__":
    main()
