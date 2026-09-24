"""Listas de documento exigido por serviço -- as FICHAS DO CLUBE.

(2026-09-24.) Até aqui estas listas eram um rascunho montado por mim em
2026-08-27 a partir das listas de julho, com um grupo "Requisitos
(conferir, não coletar)" e redação de legislação. O usuário olhou o
checklist de um processo de CRAF e disse: "está errado muita coisa". E
mandou as fichas de papel que o despachante usa no balcão, uma por
serviço. **Esta versão é transcrição dessas fichas, e nada além delas.**
Nenhum item foi acrescentado por conta própria; os requisitos "a
conferir" do rascunho saíram, porque não estão em ficha nenhuma.

Decisões do usuário ao mandar as fichas (2026-09-24):

- Certidão com número entre parênteses -- "Cert. Federal (3)" -- quer
  dizer QUANTAS certidões. Vira um item por certidão ("1 de 3", "2 de 3",
  "3 de 3"), para o contador X/Y só fechar quando todas chegarem.
  Certidão sem número é uma só.
- "Renovação CRAF" SUBSTITUI o serviço que se chamava "CRAF" (mesma
  service_key `craf`, nome novo).
- "Ibama se for CAÇA", nas duas transferências: se a arma for do acervo
  de caça, é preciso também o CR do Ibama. Vira grupo próprio.
- Apostilamento e Guia de Tráfego não vieram em ficha e ficam como
  estavam -- as listas deles abaixo são as de 2026-08-27, intocadas.

Dois itens das fichas NÃO viraram item de checklist, por decisão do
usuário: "Senha gov.br" (Revalidação) virou campo próprio no cadastro do
cliente e do filiado -- ver core/motor_credenciais.py --, porque senha
não é arquivo e o contador X/Y nunca fecharia; e "ASSINAR" (Aut. Compra)
"não significa nada", nas palavras dele.

Na ficha do CR há um segundo número depois de alguns itens ("09-Segundo
endereço - 08"). Não entrou: não está claro o que é, e item de checklist
não pode carregar número que ninguém sabe ler.

O QUE ESTE SCRIPT FAZ, E A TRAVA QUE TEM:

1. Cria o serviço que ainda não existe na empresa (Progressão de Nível
   III, Transferência entre Acervos) e acerta o nome dos que existem.
2. Troca o checklist de cada serviço pela lista abaixo.
3. **Item antigo com documento marcado em algum processo NÃO é
   apagado** -- vira `ativo='Não'`. Apagar deixaria a marcação
   (documento_checklist) apontando para item inexistente; desativar tira
   o item da tela e deixa o registro de que aquele documento foi
   conferido. O documento em si continua no caso, e a pessoa marca de
   novo no item novo.
4. Serviço cuja lista ativa já é idêntica à daqui não é tocado -- é o
   que deixa rodar de novo sem desativar o que acabou de ser criado.

Por padrão só MOSTRA o que faria. Para gravar:

    .venv\\Scripts\\python.exe -m core.db.revisar_checklist_cac
    .venv\\Scripts\\python.exe -m core.db.revisar_checklist_cac --aplicar
"""
import sys
from datetime import datetime, timezone

from core.conexao import conectar
from core.motor_empresas import EMPRESA_PADRAO, exigir_empresa

DOCUMENTOS = "Documentos"
CERTIDOES = "Certidões criminais"
IBAMA = "IBAMA"
SE_CACA = "Se a arma for do acervo de caça"


def _certidao(nome: str, quantidade: int = 1, grupo=None) -> list:
    """'Federal', 3 -> três itens. A quantidade é o número entre
    parênteses da ficha."""
    if quantidade == 1:
        return [(grupo, f"Certidão {nome}")]
    return [(grupo, f"Certidão {nome} — {n} de {quantidade}") for n in range(1, quantidade + 1)]


def _certidoes_criminais() -> list:
    """O bloco 'Certidões criminais' das fichas com marcadores: uma de cada."""
    itens = []
    for nome in ("Federal", "Estadual", "Militar", "Eleitoral"):
        itens += _certidao(nome, 1, CERTIDOES)
    return itens


# service_key -> (nome do serviço, categoria, [(grupo, item), ...])
#
# Fichas numeradas (CR, Aut. Compra, Renovação CRAF) ficam SEM grupo e na
# ordem exata da ficha -- a numeração é a ordem em que o despachante
# confere, e agrupar embaralharia isso. As fichas com marcadores já vêm
# divididas em blocos, e os blocos viram grupos.
CHECKLISTS = {
    # --- Ficha "CR" -----------------------------------------------------
    "primeiro_cr": ("Primeiro CR", "Regularização documental", [
        (None, "Laudo de capacidade técnica"),
        *_certidao("Federal", 3),
        (None, "Declaração de idoneidade"),
        (None, "RG e CNH"),
        (None, "Laudo psicológico"),
        (None, "Comprovante de endereço"),
        (None, "Comprovante de renda"),
        (None, "Declaração de filiação (caça)"),
        (None, "Comprovante do segundo endereço de acervo"),
        *_certidao("Estadual", 3),
        (None, "Declaração de segurança do acervo"),
        (None, "Declaração de compromisso"),
        (None, "Ibama"),
        (None, "Declaração de filiação"),
        *_certidao("Militar"),
        *_certidao("Eleitoral"),
    ]),

    # --- Ficha "Revalidação CR" -----------------------------------------
    "renovacao_cr": ("Revalidação do CR", "Regularização documental", [
        (DOCUMENTOS, "RG ou CNH"),
        (DOCUMENTOS, "Comprovante de renda"),
        (DOCUMENTOS, "Comprovante de endereço"),
        (DOCUMENTOS, "Comprovante do segundo endereço de acervo"),
        (DOCUMENTOS, "Laudo psicológico"),
        (DOCUMENTOS, "Laudo de capacidade técnica"),
        (DOCUMENTOS, "Declaração de filiação"),
        (DOCUMENTOS, "Declaração de segurança do acervo"),
        (DOCUMENTOS, "Declaração de compromisso"),
        (DOCUMENTOS, "Declaração de proprietário"),
        *_certidoes_criminais(),
        (IBAMA, "CAR"),
        (IBAMA, "CTF"),
        (IBAMA, "CR do Ibama"),
        (IBAMA, "Autorização de caça"),
    ]),

    # --- Ficha "Transferência de CAC p/ CAC" ----------------------------
    "transferencia_arma": ("Transferência de CAC para CAC", "Transferência", [
        (DOCUMENTOS, "RG ou CNH"),
        (DOCUMENTOS, "Comprovante de renda"),
        (DOCUMENTOS, "Comprovante de endereço"),
        (DOCUMENTOS, "Laudo psicológico"),
        (DOCUMENTOS, "Laudo de capacidade técnica"),
        (DOCUMENTOS, "Termo de transferência"),
        (DOCUMENTOS, "Declaração de idoneidade"),
        (DOCUMENTOS, "Declaração de segurança do acervo"),
        (DOCUMENTOS, "Declaração de habitualidade"),
        (DOCUMENTOS, "Declaração de proprietário"),
        *_certidoes_criminais(),
        (SE_CACA, "CR do Ibama"),
    ]),

    # --- Ficha "AUT. COMPRA" --------------------------------------------
    "aquisicao_arma": ("Autorização de Compra", "Aquisição", [
        (None, "Laudo de capacidade técnica"),
        (None, "Declaração de habitualidade e filiação"),
        (None, "Declaração de segurança do acervo"),
        *_certidao("Federal", 2),
        (None, "Declaração de idoneidade"),
        (None, "RG e CNH"),
        (None, "Laudo psicológico"),
        (None, "Comprovante de endereço e declaração"),
        (None, "Comprovante de ocupação lícita"),
        *_certidao("Militar", 2),
        *_certidao("Estadual", 3),
        *_certidao("Eleitoral", 1),
    ]),

    # --- Ficha "Progressão de Nível III" --------------------------------
    "progressao_nivel_3": ("Progressão de Nível III", "Regularização documental", [
        (DOCUMENTOS, "RG ou CNH"),
        (DOCUMENTOS, "Declaração de idoneidade"),
        (DOCUMENTOS, "Declaração de filiação"),
        (DOCUMENTOS, "Declaração de habitualidade"),
        *_certidoes_criminais(),
    ]),

    # --- Ficha "Transferência entre ACERVO" -----------------------------
    "transferencia_acervo": ("Transferência entre Acervos", "Transferência", [
        (DOCUMENTOS, "RG ou CNH"),
        (DOCUMENTOS, "Comprovante de renda"),
        (DOCUMENTOS, "Comprovante de endereço"),
        (DOCUMENTOS, "Laudo psicológico"),
        (DOCUMENTOS, "Laudo de capacidade técnica"),
        (DOCUMENTOS, "Declaração de idoneidade"),
        (DOCUMENTOS, "Declaração de segurança do acervo"),
        (DOCUMENTOS, "Declaração de habitualidade"),
        (DOCUMENTOS, "Declaração de proprietário"),
        *_certidoes_criminais(),
        (SE_CACA, "CR do Ibama"),
    ]),

    # --- Ficha "RENOVAÇÃO CRAF" (substitui o antigo "CRAF") -------------
    "craf": ("Renovação de CRAF", "CRAF", [
        *_certidao("Federal", 2),
        *_certidao("Estadual", 3),
        *_certidao("Eleitoral"),
        *_certidao("Militar", 2),
        (None, "Comprovação de rendimento"),
        (None, "Comprovação de residência atual"),
        (None, "Comprovação do segundo endereço de acervo"),
        (None, "Comprovante de capacidade técnica de arma de fogo"),
        (None, "Comprovante de aptidão psicológica"),
        (None, "Declaração de não estar respondendo a inquérito policial ou processo criminal"),
        (None, "Declaração de filiação"),
        (None, "Declaração de habitualidade (36 meses)"),
    ]),

    # --- Sem ficha: listas de 2026-08-27, intocadas ---------------------
    "guia_trafego": ("Guia de Tráfego", "Regularização documental", [
        ("Documentos a coletar", "CR válido."),
        ("Documentos a coletar", "CRAF válido de cada arma que vai trafegar."),
        ("Documentos a coletar", "Documento de identidade com foto (RG ou CNH) e CPF."),
        ("Documentos a coletar", "Comprovante de filiação ao clube de tiro (declaração de vínculo ativo)."),
        ("Documentos a coletar", "Declaração de habitualidade do clube, quando o trajeto for para treino."),
        ("Documentos a coletar", "Requerimento com origem, destino e período do trânsito."),
        ("Documentos a coletar", "Comprovante de pagamento da taxa (GRU), quando aplicável."),
        ("Documentos a coletar", "Comprovante de inscrição no campeonato, quando o trajeto for para competição."),
        ("Requisitos (conferir, não coletar)", "Guia é POR ARMA — conferir se todas as armas do trajeto estão no pedido."),
        ("Requisitos (conferir, não coletar)", "Trajeto e período declarados cobrem a viagem inteira, ida e volta."),
        ("Requisitos (conferir, não coletar)", "CRAF de cada arma dentro da validade na data do trânsito."),
    ]),
    "apostilamento": ("Apostilamento", "Regularização documental", [
        ("Documentos a coletar", "CR válido."),
        ("Documentos a coletar", "CRAF atual da arma."),
        ("Documentos a coletar", "Documento de identidade com foto (RG ou CNH) e CPF."),
        ("Documentos a coletar", "Requerimento indicando exatamente o que deve ser alterado ou corrigido."),
        ("Documentos a coletar", "Documento que comprova a alteração (nota fiscal da peça, laudo técnico ou documento com o dado correto)."),
        ("Documentos a coletar", "Comprovante de pagamento da taxa (GRU), quando aplicável."),
        ("Requisitos (conferir, não coletar)", "A alteração pretendida é permitida para o nível do CR."),
        ("Requisitos (conferir, não coletar)", "Dado a corrigir confere com o documento de origem da arma."),
    ]),
}


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo(con, tabela: str, coluna: str, prefixo: str) -> int:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return maior + 1


def _resumo(itens: list) -> str:
    """`servico.documentos_obrigatorios` -- o resumo curto que o Consultor
    usa na resposta de catálogo. Tem que acompanhar a lista nova, senão a
    IA recitaria a lista antiga numa pergunta genérica. Certidões
    repetidas ("1 de 3", "2 de 3"...) viram uma menção só."""
    vistos = []
    for _, item in itens:
        base = item.split(" — ")[0]
        if base not in vistos:
            vistos.append(base)
    return "; ".join(vistos) + "."


def revisar(empresa_id: str, aplicar: bool = True) -> dict:
    """Devolve o que mudou (ou mudaria, com aplicar=False) por serviço."""
    con = conectar(empresa_id)
    try:
        saida = {"servicos": [], "itens": 0, "aplicado": aplicar}
        numero_dex = _proximo(con, "documento_exigido", "documento_exigido_id", "DEX")

        for chave, (nome, categoria, itens) in CHECKLISTS.items():
            desejado = [(g, i) for g, i in itens]
            relato = {"chave": chave, "nome": nome, "depois": len(desejado),
                      "criado": False, "renomeado_de": None, "igual": False,
                      "apagados": 0, "desativados": 0, "processos_afetados": []}

            servico = con.execute(
                "SELECT service_id, nome_servico FROM servico WHERE empresa_id = ? AND service_key = ?",
                (empresa_id, chave),
            ).fetchone()

            if not servico:
                relato["criado"] = True
                relato["antes"] = 0
                if aplicar:
                    service_id = f"SER-{_proximo(con, 'servico', 'service_id', 'SER'):06d}"
                    con.execute(
                        "INSERT INTO servico (service_id, empresa_id, service_key, nome_servico, "
                        "categoria, documentos_obrigatorios, ativo) VALUES (?,?,?,?,?,?,'Sim')",
                        (service_id, empresa_id, chave, nome, categoria, _resumo(desejado)),
                    )
                else:
                    service_id = None
                atuais = []
            else:
                service_id = servico["service_id"]
                if servico["nome_servico"] != nome:
                    relato["renomeado_de"] = servico["nome_servico"]
                # Só os itens do SERVIÇO. Os extras de um processo (a
                # segunda capacidade técnica de alguém) não são da ficha e
                # nunca são tocados por aqui.
                atuais = con.execute(
                    "SELECT documento_exigido_id, grupo, item FROM documento_exigido "
                    "WHERE empresa_id = ? AND servico_id = ? AND ativo = 'Sim' "
                    "AND processo_id IS NULL ORDER BY ordem",
                    (empresa_id, service_id),
                ).fetchall()
                relato["antes"] = len(atuais)

            if [(a["grupo"], a["item"]) for a in atuais] == desejado and not relato["renomeado_de"]:
                relato["igual"] = True
                saida["servicos"].append(relato)
                saida["itens"] += len(desejado)
                continue

            if [(a["grupo"], a["item"]) for a in atuais] != desejado:
                for antigo in atuais:
                    marcas = con.execute(
                        "SELECT DISTINCT processo_id FROM documento_checklist "
                        "WHERE empresa_id = ? AND documento_exigido_id = ?",
                        (empresa_id, antigo["documento_exigido_id"]),
                    ).fetchall()
                    if marcas:
                        relato["desativados"] += 1
                        for m in marcas:
                            if m["processo_id"] not in relato["processos_afetados"]:
                                relato["processos_afetados"].append(m["processo_id"])
                        if aplicar:
                            con.execute(
                                "UPDATE documento_exigido SET ativo = 'Não' "
                                "WHERE documento_exigido_id = ? AND empresa_id = ?",
                                (antigo["documento_exigido_id"], empresa_id),
                            )
                    else:
                        relato["apagados"] += 1
                        if aplicar:
                            con.execute(
                                "DELETE FROM documento_exigido WHERE documento_exigido_id = ? "
                                "AND empresa_id = ?",
                                (antigo["documento_exigido_id"], empresa_id),
                            )
                if aplicar:
                    for ordem, (grupo, item) in enumerate(desejado, start=1):
                        con.execute(
                            "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, "
                            "servico_id, grupo, item, ordem, ativo) VALUES (?,?,?,?,?,?,'Sim')",
                            (f"DEX-{numero_dex:06d}", empresa_id, service_id, grupo, item, ordem),
                        )
                        numero_dex += 1

            if aplicar and not relato["criado"]:
                con.execute(
                    "UPDATE servico SET nome_servico = ?, documentos_obrigatorios = ? "
                    "WHERE service_id = ? AND empresa_id = ?",
                    (nome, _resumo(desejado), service_id, empresa_id),
                )

            saida["servicos"].append(relato)
            saida["itens"] += len(desejado)

        if aplicar:
            con.commit()
        else:
            con.rollback()
        return saida
    finally:
        con.close()


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    aplicar = "--aplicar" in sys.argv
    empresa_id = argumentos[0] if argumentos else EMPRESA_PADRAO
    exigir_empresa(empresa_id)

    saida = revisar(empresa_id, aplicar=aplicar)
    print(("APLICADO" if aplicar else "SIMULAÇÃO -- nada foi gravado") + f" ({empresa_id})\n")
    for s in saida["servicos"]:
        if s["igual"]:
            print(f"  {s['nome']:<32} sem mudança ({s['depois']} itens)")
            continue
        linha = f"  {s['nome']:<32} {s['antes']:>2} -> {s['depois']:>2} itens"
        if s["criado"]:
            linha += "  [serviço NOVO]"
        if s["renomeado_de"]:
            linha += f"  [antes: {s['renomeado_de']}]"
        print(linha)
        if s["desativados"]:
            print(f"      {s['desativados']} item(ns) antigo(s) com documento marcado ficam "
                  f"desativados, não apagados. Processos para remarcar: "
                  f"{', '.join(s['processos_afetados'])}")
    print(f"\n  Total: {saida['itens']} itens.")
    if not aplicar:
        print("\n  Para gravar: acrescente --aplicar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
