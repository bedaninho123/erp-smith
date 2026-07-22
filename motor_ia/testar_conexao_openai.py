"""Confere se a chave da OpenAI está configurada e válida -- sem nunca
imprimir o valor dela. Usa client.models.list(), que não consome tokens
de geração (só lista os modelos disponíveis para a chave)."""
from openai import AuthenticationError, OpenAI

from motor_ia.config import chave_configurada


def main():
    if not chave_configurada():
        print("OPENAI_API_KEY não encontrada. Verifique se o arquivo .env "
              "existe na raiz do projeto e tem a linha OPENAI_API_KEY=...")
        return

    print("Chave encontrada no .env. Testando conexão com a OpenAI...")
    client = OpenAI()
    try:
        modelos = client.models.list()
        total = len(modelos.data)
        print(f"Conexão OK -- a chave é válida. {total} modelos disponíveis "
              f"para esta conta.")
    except AuthenticationError:
        print("A chave foi encontrada, mas a OpenAI recusou -- ela está "
              "incorreta ou expirada. Confira o valor no .env.")
    except Exception as e:
        print(f"Não deu para conectar: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
