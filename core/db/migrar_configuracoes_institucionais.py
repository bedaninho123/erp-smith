"""Preenche em `configuracoes` os fatos institucionais que faltavam para
o Consultor responder pergunta de cliente sobre horário, endereço,
filiação e afins (ver core/configuracoes.py::CHAVES_INSTITUCIONAIS e
motor_ia/consultor.py, fonte "informacoes_empresa").

Achado em 2026-09-23: um cliente perguntou "que horas o clube abre
hoje?" e caiu num rascunho genérico -- não porque a IA errou, mas
porque nada buscava esse fato. Rodando esta migração contra o banco de
PRODUÇÃO (Railway), apareceu um problema maior: o banco de lá nunca
recebeu a leva original de configuração que `core.db.migrate_dados_teste`
semeia no banco local (nome da empresa, telefone, e-mail, horário,
saudação, assinatura, ajuste de IA) -- produção foi criada por outro
caminho, que pulou essa parte. Então este script acumulou duas coisas:
os fatos NOVOS que o dono respondeu agora (endereço, redes sociais,
primeira visita, filiação, anuidade, forma de pagamento, estrutura,
estacionamento) e os fatos BÁSICOS que já existiam localmente mas nunca
chegaram em produção -- confirmados com o dono em 2026-09-23 (telefone/
WhatsApp continuam os mesmos; e-mail institucional é smithclube@gmail.com,
o Gmail técnico ligado ao poller continua sendo outro, de teste, até a
migração completa). `horario_domingo` nasce direto com o valor real
("Aberto apenas em dia de prova") em vez de "Fechado" -- o valor antigo
nunca existiu em produção, só localmente, e o bloco no fim de `main()`
corrige o caso de outro ambiente que ainda tenha o valor errado (ex.:
local, antes desta migração já ter rodado lá uma vez).

Dado real de UMA empresa (o piloto), não um seed genérico -- por isso
recebe o empresa_id por linha de comando (padrão EMP-000001, mesmo
padrão de core.db.gerar_clientes_ficticios). Rodar para uma segunda
empresa exigiria os fatos reais DAQUELA empresa, não uma cópia destes.

Idempotente -- roda sobre banco em uso, não recria nada. Cada chave só
é inserida se ainda não existir para a empresa; horario_domingo é
corrigido só se ainda estiver no valor antigo.

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_configuracoes_institucionais [empresa_id]`
"""
import sys
from datetime import datetime, timezone

from core.conexao import conectar
from core.configuracoes import atualizar_configuracao
from core.motor_empresas import EMPRESA_PADRAO

# Valor antigo (migrado da planilha, nunca confirmado com o dono) e o
# valor real -- o clube abre em dia de prova, não fecha todo domingo.
HORARIO_DOMINGO_ANTIGO = "Fechado"
HORARIO_DOMINGO_NOVO = "Aberto apenas em dia de prova"

# (chave, valor, categoria, descrição) -- mesmo formato de
# core/db/migrate_dados_teste.py, só que como correção sobre banco já em
# uso em vez de seed inicial.
NOVAS_CHAVES = [
    ("endereco",
     "AV ETORE TIVERON, 200, PARQUE DOS SABIAS II (PADRE NOBREGA), "
     "CEP 17533-073 - MARÍLIA | SÃO PAULO",
     "empresa", "Endereço completo do clube"),
    ("site_clube", "https://www.smithclube.com.br/", "contato",
     "Site institucional do clube"),
    ("site_loja", "https://www.smithloja.com.br/", "contato",
     "Site da loja"),
    ("instagram", "https://www.instagram.com/smith.clube/", "contato",
     "Instagram do clube"),
    ("primeira_visita",
     "Pode chegar e treinar sem precisar agendar, mas é necessário "
     "estar com o CR, CRAF e guias de tráfego em dia.",
     "atendimento", "O que informar sobre a primeira visita"),
    ("processo_filiacao",
     "Para se filiar ao Smith Clube é necessário tirar o CR. Contamos "
     "com nossa equipe de despachante para emissão de todos os "
     "documentos e o acompanhamento necessário.",
     "atendimento", "Como funciona o processo de filiação"),
    ("valor_anuidade", "R$ 700,00, em até 6x sem juros", "empresa",
     "Valor da anuidade"),
    ("formas_pagamento", "Pix, cartão de crédito e cartão de débito",
     "empresa", "Formas de pagamento aceitas"),
    ("estrutura_clube",
     "8 pistas monitoradas, com alvos automáticos, em ambiente "
     "climatizado.",
     "empresa", "Estrutura do clube"),
    ("estacionamento", "Sim", "empresa", "Tem estacionamento"),

    # Básicos que já existiam no banco LOCAL (semeados por
    # core.db.migrate_dados_teste a partir da planilha original) mas
    # nunca chegaram em produção -- valores confirmados de novo com o
    # dono em 2026-09-23.
    ("nome_empresa", "Smith Clube de Tiro", "empresa",
     "Nome utilizado nas mensagens"),
    ("cidade", "Marília", "empresa", "Cidade da empresa"),
    ("estado", "SP", "empresa", "Estado da empresa"),
    ("telefone", "(14)99805-9500 / (14) 99815-7890", "contato",
     "Telefone principal"),
    ("whatsapp", "(14)99805-9500 / (14) 99815-7890", "contato",
     "WhatsApp de atendimento"),
    ("email_atendimento", "smithclube@gmail.com", "contato",
     "E-mail de atendimento"),
    ("horario_semana",
     "Terça e Sexta: 9h as 18h / Quarta 14h as 21h / Quinta 13h as 20h",
     "atendimento", "Horário de atendimento semanal"),
    ("horario_sabado", "Sábado, das 9h às 17h", "atendimento",
     "Horário de sábado"),
    ("horario_domingo", HORARIO_DOMINGO_NOVO, "atendimento",
     "Horário de domingo"),
    ("saudacao_padrao", "Olá! Como podemos ajudar?", "mensagens",
     "Saudação inicial"),
    ("mensagem_fora_horario",
     "Recebemos sua mensagem fora do nosso horário de atendimento. "
     "Retornaremos assim que possível.", "mensagens",
     "Resposta fora do expediente"),
    ("mensagem_encaminhamento_humano",
     "Sua solicitação será encaminhada para nossa equipe de atendimento.",
     "mensagens", "Aviso de transferência"),
    ("assinatura_email", "Equipe Smith Clube de Tiro", "mensagens",
     "Assinatura dos e-mails"),
    ("prazo_resposta_humano", "Em até 1 dia útil", "atendimento",
     "Prazo estimado para resposta humana"),
    ("mensagem_cliente_nao_encontrado",
     "Não localizamos um cadastro com esses dados em nosso sistema. Se "
     "você já é nosso cliente, poderia nos informar seu CPF para "
     "localizarmos seu cadastro? Caso ainda não seja cliente, ficaremos "
     "felizes em ajudar -- conte um pouco mais sobre o que você precisa.",
     "mensagens",
     "Resposta para remetente não identificado como cliente cadastrado"),
    ("notificar_cliente_mudanca_status", "Sim", "portal",
     "Enquanto 'Sim', o cliente recebe um e-mail genérico (sem detalhe "
     "do novo status no corpo, só um link pro Portal) sempre que o "
     "status de um caso ou processo dele muda pelo painel administrativo."),
    ("moeda", "BRL", "sistema", "Moeda utilizada nos valores"),
    ("idioma", "pt-BR", "sistema", "Idioma das respostas"),
    ("idioma_resposta", "pt-BR", "ia", "Idioma padrão das respostas"),
    ("nome_assistente", "Assistente Virtual Smith", "ia",
     "Nome do atendente virtual"),
    ("modelo_openai", "gpt-5-mini", "ia", "Modelo utilizado"),
    ("temperatura_ia", "0.2", "ia", "Criatividade das respostas"),
    ("max_tokens", "1200", "ia", "Máximo de tokens das respostas"),
    ("permitir_valores_referencia", "Sim", "ia",
     "Permite informar valores cadastrados"),
    ("permitir_prazos_referencia", "Sim", "ia",
     "Permite informar prazos cadastrados"),
    ("aviso_valor",
     "Os valores informados são referências e podem variar conforme o "
     "serviço e as particularidades do caso.", "mensagens",
     "Aviso utilizado junto aos valores"),
    ("aviso_prazo",
     "Os prazos informados são estimativas e podem variar conforme a "
     "análise do órgão competente.", "mensagens",
     "Aviso utilizado junto aos prazos"),
]


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def main(empresa_id: str = EMPRESA_PADRAO) -> None:
    con = conectar(empresa_id)
    try:
        chaves_existentes = {
            r[0] for r in con.execute(
                "SELECT chave FROM configuracoes WHERE empresa_id = ?", (empresa_id,)
            )
        }

        inseridas = []
        for chave, valor, categoria, descricao in NOVAS_CHAVES:
            if chave in chaves_existentes:
                continue
            config_id = _proximo_id(con, "configuracoes", "config_id", "CFG")
            con.execute(
                "INSERT INTO configuracoes (config_id, empresa_id, chave, valor, "
                "categoria, descricao, ativo) VALUES (?,?,?,?,?,?,?)",
                (config_id, empresa_id, chave, valor, categoria, descricao, "Sim"),
            )
            chaves_existentes.add(chave)
            inseridas.append(chave)
        con.commit()

        if inseridas:
            print(f"Inseridas {len(inseridas)} chave(s) nova(s): {', '.join(inseridas)}")
        else:
            print("Nenhuma chave nova a inserir (todas já existiam).")

        linha_domingo = con.execute(
            "SELECT config_id, valor FROM configuracoes "
            "WHERE empresa_id = ? AND chave = 'horario_domingo'",
            (empresa_id,),
        ).fetchone()
        if linha_domingo and linha_domingo["valor"] == HORARIO_DOMINGO_ANTIGO:
            atualizar_configuracao(
                empresa_id, linha_domingo["config_id"], HORARIO_DOMINGO_NOVO, "Sim",
                alterado_por="Migração (core.db.migrar_configuracoes_institucionais)",
            )
            print(f"horario_domingo corrigido: '{HORARIO_DOMINGO_ANTIGO}' -> '{HORARIO_DOMINGO_NOVO}'")
        else:
            print("horario_domingo: nada a corrigir (já não está no valor antigo).")
    finally:
        con.close()


if __name__ == "__main__":
    empresa = sys.argv[1] if len(sys.argv) > 1 else EMPRESA_PADRAO
    main(empresa)
