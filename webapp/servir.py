"""Ponto de entrada de PRODUÇÃO -- serve painel administrativo E Portal do
Cliente NUM SÓ PROCESSO, usado só em hospedagem (Railway), nunca em
desenvolvimento local. Ali continua sendo `python -m webapp.app` (painel)
e `python -m portal.app` (Portal), cada um na sua porta (ver CLAUDE.md);
este arquivo não substitui nenhum dos dois, é um terceiro jeito de
SERVIR os mesmos dois `app`, juntos.

Por que juntos, e não dois serviços Railway separados (2026-09-03): os
dois apps leem e escrevem o MESMO banco SQLite (o Portal mostra o caso
que o painel abriu, o cliente sobe documento que o painel confere). Um
volume Railway só pode estar montado numa service por vez -- não existe
"montar o mesmo volume em duas services" na plataforma (conferido:
"a volume can be attached to one service"). Duas services com volumes
SEPARADOS seriam dois bancos DIVERGENTES -- o Portal mostraria um caso
que não existe pro painel. Um processo só, um volume só, resolve isso
sem precisar migrar de SQLite pra um banco de rede.

Como os dois dividem o mesmo domínio (Railway só dá UM domínio grátis
por service -- "Target Ports"/domínio por porta exige domínio próprio,
que não temos), a separação é por PREFIXO DE CAMINHO: tudo que começa
com /portal vai pro Portal, o resto vai pro painel. Por isso as rotas
`/`, `/entrar/<token>` e `/sair` do Portal viraram `/portal/login`,
`/portal/entrar/<token>` e `/portal/sair` (2026-09-03, ver portal/app.py)
-- SEM ISSO o Portal responderia em "/", que já é a tela inicial do
painel, e o despachante de caminho abaixo não saberia pra qual dos dois
mandar. A troca foi feita nos DECORATORS de rota (o endpoint Flask
continua se chamando "login"/"entrar"/"sair"), então todo `url_for(...)`
já aponta certo sozinho -- só o link do e-mail (montado como string, não
por url_for) precisou de ajuste manual.

Por que um arquivo separado: `app.run(...)` em webapp/app.py e
portal/app.py é o servidor de desenvolvimento do Flask -- ele mesmo
avisa no console que não é feito pra tráfego de verdade
(single-threaded, sem fila de conexão). Trocamos só o "como servir",
nunca a aplicação: mesmos objetos `app`, mesmas rotas, mesmo banco, zero
lógica de negócio aqui.

`waitress` em vez de `gunicorn`: gunicorn depende de `fork()`, que não
existe no Windows -- não daria pra testar este arquivo localmente antes
de subir pro Linux da hospedagem. waitress é Python puro, roda nos dois
sistemas, e é servidor de produção de verdade (não um shim de teste).

`ProxyFix`: a hospedagem termina o HTTPS na borda dela e fala HTTP puro
com este processo -- sem isto, o Flask acha que a conexão é HTTP e o
cookie de sessão (SESSION_COOKIE_SECURE, ligado via COOKIE_HTTPS=Sim)
se comporta errado. Aplicado nos DOIS apps, cada um com o seu -- fica só
aqui, não em webapp/app.py nem portal/app.py, porque em desenvolvimento
local não existe proxy nenhum na frente.

SINCRONIZAÇÃO DE HABITUALIDADE EM SEGUNDO PLANO (2026-09-03): local, isso
é uma Tarefa Agendada do Windows separada (ver
domain/clube_tiro/instalar_tarefa_habitualidade.bat), rodando 4x ao dia.
Na hospedagem não existe Tarefa Agendada -- e criar um SEGUNDO serviço no
Railway só para isso exigiria o mesmo volume (o banco) montado em dois
containers ao mesmo tempo, que a própria Railway desaconselha ("to
prevent data corruption, we prevent multiple deployments from being
active and mounted to the same service"). Mais simples e mais seguro:
uma thread de fundo dentro deste MESMO processo, escrevendo no MESMO
arquivo que o painel já usa -- exatamente o padrão que
core/conexao.py::busy_timeout já existe pra suportar (painel + poller
gravando ao mesmo tempo).

Trava de segurança: só roda de verdade se shooting_house_ativo() (a
CHAVE GERAL, não só a credencial -- ver integracoes/config.py). Sem essa
checagem, rodar isto com o modo real desligado gravaria HABITUALIDADE
SIMULADA em cima de filiado de VERDADE -- dado fictício de treino
carimbado no nome de uma pessoa real seria pior que não ter dado nenhum.

BACKUP DIÁRIO EM SEGUNDO PLANO (2026-09-03): local, isso é
`core/db/backup.py` rodando via Tarefa Agendada do Windows às 3h. Sem
ele, o banco hospedado não tinha proteção nenhuma contra exclusão ou
corrupção acidental -- exatamente o problema que motivou o backup local
existir, e que também vale aqui. Mesma solução da habitualidade: uma
thread de fundo, não um segundo serviço (mesma limitação de volume por
service).

`incluir_documentos=False` de propósito: BACKUP_DIR aqui aponta pra uma
subpasta do MESMO volume onde o banco já mora (não tem HD externo nem
Google Drive na hospedagem) -- isto protege contra "rodei uma migração
errada" ou "apaguei a linha errada por SSH", não contra o volume inteiro
sumir. Duplicar documento de cliente todo dia, com retenção de vários
dias, no mesmo volume de 500MB, encheria ele rápido; o `.db` sozinho é
pequeno. Backup externo de verdade (fora da hospedagem) continua sendo
trabalho futuro -- ver memória do projeto.
"""
import os
import threading
import time
import traceback
from datetime import datetime, timezone

from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from webapp.app import app as painel_app
from portal.app import app as portal_app

painel_app.wsgi_app = ProxyFix(painel_app.wsgi_app, x_for=1, x_proto=1, x_host=1)
portal_app.wsgi_app = ProxyFix(portal_app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _despachar_por_prefixo(environ, start_response):
    """WSGI mínimo: só decide qual dos dois `app` atende. Nenhuma
    reescrita de PATH_INFO/SCRIPT_NAME -- as rotas do Portal já nasceram
    com o prefixo /portal (ver docstring do módulo), então repassar o
    ambiente intocado é o que faz url_for, redirect e o <form method=
    "post"> sem action do Portal continuarem funcionando exatamente como
    localmente."""
    if environ.get("PATH_INFO", "").startswith("/portal"):
        return portal_app.wsgi_app(environ, start_response)
    return painel_app.wsgi_app(environ, start_response)

# Mesmo ritmo "4x ao dia" da Tarefa Agendada local (a cada 6h). A primeira
# rodada espera só 60s -- suficiente pro processo terminar de subir --
# em vez de esperar 6h pra ter o primeiro dado.
_INTERVALO_SEGUNDOS = 6 * 60 * 60
_ATRASO_INICIAL_SEGUNDOS = 60
_LIMITE_POR_RODADA = 150  # mesmo padrão default do script local


def _log(mensagem: str, origem: str = "sincronizador-habitualidade") -> None:
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{origem} {agora}] {mensagem}", flush=True)


def _loop_sincronizacao_habitualidade() -> None:
    from core.motor_empresas import listar_empresas
    from domain.clube_tiro.sincronizar_habitualidade import sincronizar
    from integracoes.config import shooting_house_ativo

    time.sleep(_ATRASO_INICIAL_SEGUNDOS)
    while True:
        if not shooting_house_ativo():
            _log("Shooting House em modo simulado -- pulando rodada "
                 "(nunca grava habitualidade simulada em filiado real).")
        else:
            for empresa in listar_empresas():
                try:
                    saida = sincronizar(empresa["empresa_id"], limite=_LIMITE_POR_RODADA)
                    hab = saida.get("habitualidade") or {}
                    _log(f"{empresa['empresa_id']}: lista {saida['lista']['total']} "
                         f"filiados, habitualidade consultada em "
                         f"{hab.get('consultados', 0)}.")
                except Exception:
                    _log(f"Falhou para {empresa['empresa_id']}:")
                    traceback.print_exc()
        time.sleep(_INTERVALO_SEGUNDOS)


# Uma vez por dia. Atraso inicial maior que o da habitualidade -- não faz
# sentido competir por I/O com a primeira sincronização logo que o
# processo sobe, e o banco recém-criado num deploy novo não tem nada
# ainda que valha a pena copiar.
_INTERVALO_BACKUP_SEGUNDOS = 24 * 60 * 60
_ATRASO_INICIAL_BACKUP_SEGUNDOS = 300


def _loop_backup() -> None:
    from core.db import backup as modulo_backup

    time.sleep(_ATRASO_INICIAL_BACKUP_SEGUNDOS)
    while True:
        try:
            modulo_backup.main(incluir_documentos=False)
        except Exception:
            _log("Falhou:", origem="backup")
            traceback.print_exc()
        time.sleep(_INTERVALO_BACKUP_SEGUNDOS)


if __name__ == "__main__":
    threading.Thread(target=_loop_sincronizacao_habitualidade, daemon=True).start()
    threading.Thread(target=_loop_backup, daemon=True).start()

    porta = int(os.environ.get("PORT", "8000"))
    print(f"Painel + Portal (produção) ouvindo em 0.0.0.0:{porta} "
          f"(/portal/* -> Portal do Cliente, resto -> painel)")
    serve(_despachar_por_prefixo, host="0.0.0.0", port=porta, threads=8)
