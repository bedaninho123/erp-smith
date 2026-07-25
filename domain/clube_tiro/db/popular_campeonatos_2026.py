"""Popula o calendário de campeonatos/provas de 2026 a partir do
calendário público do clube (https://www.smithclube.com.br/calendario/2026/),
lido em 2026-07-25. Origem='manual' porque foi extraído do site, não da
API do Shooting House (sem credencial liberada ainda -- ver
domain/clube_tiro/motor_campeonatos.py).

Onde o site mostrava a mesma etapa dividida em duas tabelas mensais
consecutivas (ex.: "2ª Etapa Prova de Precisão" aparecendo em
Setembro e voltando em 1º de Outubro), as duas entradas foram unidas
num único intervalo -- é a mesma prova, só a grade visual do site que
quebra por mês.

Rode com `python -m domain.clube_tiro.db.popular_campeonatos_2026`.
Idempotente checando pelo nome + data_inicio antes de inserir.
"""
from domain.clube_tiro.motor_campeonatos import conectar, criar_campeonato

CAMPEONATOS_2026 = [
    ("Prova 4 Armas Smith Clube", "2026-01-27", "2026-01-31"),

    ("REINIT - Rede Internacional Interclubes 2ª Etapa Bravo", "2026-02-03", "2026-02-28"),
    ("Campeonato Nacional Linade - 1ª Etapa", "2026-02-06", "2026-02-21"),
    ("Prova Silhuetas Metálicas Armas Curtas e Longas", "2026-02-08", "2026-02-08"),
    ("Prova 4 Armas Smith Clube", "2026-02-19", "2026-02-28"),

    ("REINIT - Rede Internacional Interclubes 3ª Etapa Charlie", "2026-03-03", "2026-03-31"),
    ("Campeonato Nacional Linade 2ª Etapa", "2026-03-13", "2026-03-28"),
    ("Prova 4 Armas Smith Clube", "2026-03-17", "2026-03-31"),
    ("Prova de Alvos Metálicos Contra o Tempo Armas Curtas e Longas", "2026-03-29", "2026-03-29"),

    ("REINIT - Rede Internacional Interclubes 4ª Etapa Delta", "2026-04-01", "2026-04-30"),
    ("Campeonato Nacional Linade 3ª Etapa", "2026-04-10", "2026-04-25"),
    ("Prova 4 Armas Smith Clube", "2026-04-14", "2026-04-30"),
    ("Prova Trigun Smith Clube", "2026-04-19", "2026-04-19"),

    ("REINIT - Rede Internacional Interclubes 5ª Etapa Echo", "2026-05-01", "2026-05-29"),
    ("Campeonato Nacional Linade 4ª Etapa", "2026-05-08", "2026-05-23"),
    ("Prova Silhuetas Metálicas Armas Curtas e Longas", "2026-05-17", "2026-05-17"),
    ("Prova 4 Armas Smith Clube", "2026-05-19", "2026-05-30"),

    ("REINIT - Rede Internacional Interclubes 6ª Etapa Foxtrot", "2026-06-02", "2026-06-30"),
    ("Campeonato Nacional Linade - 5ª Etapa", "2026-06-12", "2026-06-27"),
    ("Prova 4 Armas Smith Clube", "2026-06-16", "2026-06-30"),
    ("Prova de Alvos Metálicos Contra o Tempo Armas Curtas e Longas", "2026-06-21", "2026-06-21"),

    ("REINIT - Rede Internacional Interclubes 7ª Etapa Golf", "2026-07-01", "2026-07-31"),
    ("Campeonato Nacional Linade - 6ª Etapa", "2026-07-10", "2026-07-25"),
    ("Prova 4 Armas Smith Clube", "2026-07-22", "2026-07-31"),
    ("Prova Silhuetas Metálicas Armas Curtas e Longas", "2026-07-26", "2026-07-26"),

    ("REINIT - Rede Internacional Interclubes 8ª Etapa Hotel", "2026-08-01", "2026-08-31"),
    ("Campeonato Nacional Linade 7ª Etapa", "2026-08-14", "2026-08-29"),
    ("Prova 4 Armas Smith Clube", "2026-08-18", "2026-08-29"),
    ("1ª Etapa Prova de Precisão Smith Clube", "2026-08-18", "2026-08-30"),

    ("REINIT - Rede Internacional Interclubes 9ª Etapa India", "2026-09-02", "2026-09-30"),
    ("Campeonato Nacional Linade - 8ª Etapa", "2026-09-11", "2026-09-26"),
    ("Prova 4 Armas Smith Clube", "2026-09-15", "2026-09-30"),
    ("2ª Etapa Prova de Precisão Smith Clube", "2026-09-15", "2026-10-01"),

    ("REINIT - Rede Internacional Interclubes 10ª Etapa Juliet", "2026-10-01", "2026-10-30"),
    ("Campeonato Nacional Linade - 9ª Etapa", "2026-10-07", "2026-10-22"),
    ("3ª Etapa Prova de Precisão Smith Clube", "2026-10-13", "2026-10-30"),

    ("REINIT - Rede Internacional Interclubes 11ª Etapa Kilo", "2026-11-03", "2026-11-28"),
    ("Campeonato Nacional Linade - Playoff", "2026-11-12", "2026-11-22"),
    ("Prova 4 Armas Smith Clube", "2026-11-17", "2026-11-28"),
    ("4ª Etapa Prova de Precisão Smith Clube", "2026-11-17", "2026-11-29"),

    ("REINIT - Rede Internacional Interclubes 12ª Etapa Lima", "2026-12-01", "2026-12-22"),
    ("Etapa FINAL - Prova de Precisão Smith Clube + Confraternização 13/12", "2026-12-01", "2026-12-13"),
    ("Prova 4 Armas Smith Clube", "2026-12-01", "2026-12-22"),
]


def main():
    con = conectar()
    try:
        existentes = {
            (row["nome"], row["data_inicio"])
            for row in con.execute("SELECT nome, data_inicio FROM campeonato").fetchall()
        }
    finally:
        con.close()

    criados = 0
    for nome, data_inicio, data_fim in CAMPEONATOS_2026:
        if (nome, data_inicio) in existentes:
            continue
        criar_campeonato(nome, data_inicio, data_fim, origem="manual")
        criados += 1

    print(f"{criados} campeonato(s) inserido(s) ({len(CAMPEONATOS_2026) - criados} já existiam).")


if __name__ == "__main__":
    main()
