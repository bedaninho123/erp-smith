"""Popula a base de conhecimento (FAQ institucional) do Domínio Clube de
Tiro com perguntas frequentes.

Estas 10 entradas foram revisadas e aprovadas pelo usuário em 2026-07-23,
com base na leitura direta do Decreto nº 11.615/2023 (regulamenta a Lei
nº 10.826/2003 -- aquisição, registro, posse, porte de armas de fogo),
já consolidado com as alterações do Decreto nº 12.345/2024. Fonte:
https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/decreto/d11615.htm

Por isso nascem com aprovado='Sim' -- diferente do padrão geral do
projeto (conteúdo novo/não revisado deve nascer 'Não', ver
domain/clube_tiro/db/aprovar_conhecimento.py). Qualquer pergunta NOVA
adicionada aqui no futuro deve voltar a nascer 'Não' até ser revisada
com a mesma atenção.
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "domain/clube_tiro/db/dominio_clube_tiro.db"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PERGUNTAS = [
    ("CR", "O que é o CR?",
     "O CR (Certificado de Registro) é o documento emitido pelo Comando do "
     "Exército que autoriza e registra a pessoa física ou jurídica para "
     "exercer atividades relacionadas a armas de fogo — como atirador "
     "desportivo, caçador ou colecionador —, conforme o Decreto nº "
     "11.615/2023."),
    ("CR", "Por quanto tempo o CR é válido?",
     "O CR do atirador desportivo não tem um prazo fixo que expira sozinho: "
     "exige confirmação cadastral anual e o cumprimento contínuo da "
     "habitualidade mínima (frequência de treinos/competições) para "
     "continuar válido. Já o CRAF — o registro de cada arma especificamente "
     "— tem prazo definido: 3 anos para atirador desportivo, caçador "
     "excepcional e colecionador, e 5 anos para posse (Decreto nº "
     "11.615/2023, art. 24). Fale com a gente pra confirmar a situação "
     "específica do seu registro."),
    ("CR", "Quais categorias de CR existem?",
     "As principais categorias são Colecionador, Atirador Desportivo "
     "(dividido em níveis 1, 2 e 3, conforme a frequência de treino) e "
     "Caçador (excepcional, para controle de fauna invasora, ou de "
     "subsistência). Cada uma tem requisitos próprios — fale com a gente "
     "pra entender qual se aplica ao seu caso."),
    ("CRAF", "O que é o CRAF?",
     "O CRAF (Certificado de Registro de Arma de Fogo) é o documento que "
     "registra formalmente uma arma de fogo específica em nome do "
     "proprietário — diferente do CR, que autoriza a pessoa, não a arma "
     "(Decreto nº 11.615/2023, art. 2º)."),
    ("Habitualidade", "O que é habitualidade e por que ela é exigida?",
     "Habitualidade é a comprovação de que o atirador desportivo pratica "
     "tiro com a frequência mínima exigida por lei. Pelo Decreto nº "
     "11.615/2023 (art. 35), o mínimo varia por nível: Nível 1 exige 8 "
     "treinos ou competições a cada 12 meses; Nível 2 exige 12 treinos + 4 "
     "competições; Nível 3 exige 20 treinos + 6 competições. É essa "
     "frequência que sustenta a manutenção do CR como atirador desportivo."),
    ("Habitualidade", "Como faço para comprovar minha habitualidade?",
     "A comprovação é feita através dos registros de participação em "
     "treinos e competições no clube — hoje a lei exige que as entidades de "
     "tiro mantenham esse controle por biometria ou reconhecimento facial. "
     "Nossa equipe pode te ajudar a consultar seu histórico de "
     "participações."),
    ("Aquisição", "Como funciona o processo de aquisição de uma arma de fogo?",
     "O processo (Decreto nº 11.615/2023, art. 15) exige: ter no mínimo 25 "
     "anos, apresentar documentação pessoal, comprovar a necessidade "
     "efetiva da posse/porte (não é automático, precisa justificar), "
     "certidões de antecedentes criminais, comprovante de residência, "
     "capacidade técnica atestada por instrutor credenciado e laudo de "
     "aptidão psicológica. Nossa equipe acompanha esse processo com você "
     "do início ao fim."),
    ("Transferência", "Posso transferir uma arma para outra pessoa?",
     "Sim, é possível. A transferência exige autorização prévia da Polícia "
     "Federal ou do Comando do Exército (dependendo de onde a arma está "
     "registrada), e quem vai receber a arma precisa cumprir os mesmos "
     "requisitos de quem está adquirindo pela primeira vez (Decreto nº "
     "11.615/2023, art. 22). A entrega só pode acontecer depois da "
     "autorização sair."),
    ("Guias", "O que é a guia de tráfego de arma de fogo?",
     "A guia de tráfego autoriza o transporte da arma de fogo desmuniciada "
     "entre a sua residência e locais como o clube de tiro — ela não "
     "autoriza portar a arma, só transportá-la, e apenas no trajeto "
     "especificado (Decreto nº 11.615/2023, art. 21)."),
    ("Legislação", "A legislação sobre armas de fogo muda com frequência?",
     "Sim, e bastante — o próprio Decreto nº 11.615/2023 já foi alterado "
     "pelo Decreto nº 12.345/2024 em diversos pontos. Por isso sempre "
     "confirmamos a informação mais atual com você antes de qualquer "
     "decisão."),
]


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        maior = con.execute(
            "SELECT MAX(CAST(SUBSTR(conhecimento_id, 5) AS INTEGER)) FROM conhecimento"
        ).fetchone()[0] or 0

        agora = _agora_iso()
        linhas = [
            (f"KNW-{maior + i + 1:06d}", categoria, pergunta, resposta, "Sim", "Sim", agora)
            for i, (categoria, pergunta, resposta) in enumerate(PERGUNTAS)
        ]
        con.executemany(
            "INSERT INTO conhecimento VALUES (?,?,?,?,?,?,?)", linhas
        )
        con.commit()
        print(f"{len(linhas)} perguntas inseridas, já aprovadas "
              "(revisadas com base no Decreto nº 11.615/2023 em 2026-07-23).")
    finally:
        con.close()


if __name__ == "__main__":
    main()
