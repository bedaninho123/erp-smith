"""Preenche em `configuracoes` os fatos institucionais que faltavam para
o Consultor responder pergunta de cliente sobre horário, endereço,
filiação e afins (ver core/configuracoes.py::CHAVES_INSTITUCIONAIS e
motor_ia/consultor.py, fonte "informacoes_empresa").

Achado em 2026-09-23: um cliente perguntou "que horas o clube abre
hoje?" e caiu num rascunho genérico -- não porque a IA errou, mas
porque nada buscava esse fato. `horario_semana`/`horario_sabado`/
`horario_domingo` já existiam desde a migração inicial da planilha,
mas nada os lia fora da tela de Configurações. Este script acrescenta o
que ainda faltava (endereço, redes sociais, primeira visita, filiação,
anuidade, forma de pagamento, estrutura, estacionamento) e corrige
`horario_domingo`, que estava "Fechado" -- o clube abre aos domingos em
dia de prova, segundo o dono.

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
]

# Valor antigo (migrado da planilha, nunca confirmado com o dono) e o
# valor real -- o clube abre em dia de prova, não fecha todo domingo.
HORARIO_DOMINGO_ANTIGO = "Fechado"
HORARIO_DOMINGO_NOVO = "Aberto apenas em dia de prova"


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
