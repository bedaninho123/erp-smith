"""Categorias sugeridas para o Marketplace de classificados entre
atiradores, para o formulário de anúncio.

Vive no Domínio pelo mesmo motivo de documentos_cac.py: é vocabulário de
clube de tiro (um escritório de advocacia nunca vai anunciar uma
"Luneta/Mira"). `anuncio.categoria` (Core) continua sendo TEXTO livre --
esta lista é sugestão de tela, não validação.

Munição fica de fora de propósito (pedido do usuário, 2026-09-02): tem
controle de aquisição próprio (SIGMA), mais sensível que arma ou
acessório -- não oferecer como opção é a primeira barreira; a fila de
moderação (todo anúncio nasce Pendente, ver core/motor_marketplace.py)
é a segunda, contra quem tentar digitar fora da lista.
"""

CATEGORIAS = ("Arma", "Luneta/Mira", "Equipamento", "Acessório")

# Categoria que dispara o convite pra abrir a documentação de
# Transferência de Arma (ver portal/app.py) -- centralizado aqui porque
# é a mesma string usada nos dois lugares (sugestão de tela e regra de
# quando mostrar o botão).
CATEGORIA_ARMA = "Arma"
