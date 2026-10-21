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

POLLER DE E-MAIL EM SEGUNDO PLANO (2026-09-23): local, isso é
`atendimento/poller.py --uma-vez` via Tarefa Agendada do Windows a cada
2 min. Achado ao investigar por que um e-mail de teste não foi
respondido: essa tarefa estava falhando com `invalid_grant` (token do
Gmail expirado/revogado) desde 2026-07-30 -- quase dois meses sem
ninguém perceber, porque o próprio alerta de falha também tenta mandar
e-mail pelo mesmo Gmail quebrado. E mesmo com o token em dia, o Railway
nunca chegou a checar a caixa de entrada: o Procfile só sobe este
processo web, sem worker nenhum pro poller. Resultado: o atendimento por
e-mail dependia inteiramente do PC do usuário estar ligado -- o ponto
mais frágil do deploy inteiro. Mesma solução das duas rotinas acima: uma
thread de fundo chamando direto `atendimento.poller.loop` (que já tem
seu próprio `while True` + intervalo de 60s + try/except por rodada;
nada aqui reimplementa esse loop).

Pré-requisito que este arquivo não resolve sozinho: `ERP_GMAIL_TOKEN_PATH`
(configurado como `/data/token.json`, ver docstring de
`integracoes/gmail.py`) precisa apontar para um token válido DENTRO do
volume antes do processo subir -- copiar o `token.json` local pra lá é
operação manual de quem tem acesso ao Railway (`railway ssh`), feita uma
vez. Sem o arquivo lá, `gmail_configurado()` volta `False` e esta thread
só imprime "Gmail ainda não autorizado" a cada rodada, sem quebrar o
processo.

Trava de corrida que este arquivo NÃO cobre sozinho: o poller usa um
lock de ARQUIVO local (`atendimento/poller.lock`) pra não processar o
mesmo e-mail duas vezes se duas execuções se sobrepuserem -- isso
protege contra corrida dentro do MESMO filesystem, mas o Windows local
e o container do Railway são filesystems diferentes. Rodar esta thread
aqui e deixar a Tarefa Agendada do Windows ligada ao mesmo tempo faz as
duas caixas de entrada (a mesma conta Gmail) serem lidas por dois
processos independentes, cada um marcando e-mail como lido e escrevendo
num banco DIFERENTE (local vs. volume do Railway) -- por isso a Tarefa
Agendada local precisa ser desativada
(`atendimento\remover_tarefa_agendada.bat`) quando esta thread entrar
em produção, não as duas ao mesmo tempo.

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


# UM ENDEREÇO PARA CADA APP (2026-10-14). Com domínio próprio
# (smithclubedetiro.com.br), o mesmo serviço Railway responde em dois
# subdomínios, e quem decide o app passa a ser o ENDEREÇO, não o caminho:
#
#   PORTAL_HOST -> tudo vai pro Portal. O painel não existe ali: um
#                  cliente que digite /login não cai na tela da equipe.
#   PAINEL_HOST -> painel. /portal... ali redireciona pro PORTAL_HOST,
#                  para link antigo continuar levando ao lugar certo.
#   outro       -> a regra antiga por prefixo, sem mudança nenhuma: é o
#                  endereço *.up.railway.app, que continua no ar (e-mail
#                  já enviado e a política de privacidade cadastrada no
#                  Google apontam para ele) e o uso local.
#
# Vazias = comportamento de antes, inteiro. Por isso este código pode
# subir antes de o domínio existir.
#
# As rotas do Portal continuam com /portal mesmo no endereço próprio
# (portal.../portal/login): tirar o prefixo mexeria em toda rota, no
# escopo do app instalado e no link dos e-mails, só para encurtar a URL.
PORTAL_HOST = os.environ.get("PORTAL_HOST", "").strip().lower()
PAINEL_HOST = os.environ.get("PAINEL_HOST", "").strip().lower()


def _host_pedido(environ) -> str:
    # X-Forwarded-Host primeiro: é o endereço que o visitante digitou,
    # visto pela borda do Railway. Falsificar isso só escolheria qual dos
    # dois apps públicos responde -- cada um continua com o próprio login.
    bruto = environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST") or ""
    return bruto.split(",")[0].strip().split(":")[0].lower()


def _redirecionar(destino: str, start_response):
    # 302, não 301: navegador guarda 301 para sempre, e um erro de
    # configuração aqui ficaria gravado no celular do cliente.
    start_response("302 Found", [("Location", destino), ("Content-Length", "0")])
    return [b""]


def _despachar_por_prefixo(environ, start_response):
    """WSGI mínimo: só decide qual dos dois `app` atende. Nenhuma
    reescrita de PATH_INFO/SCRIPT_NAME -- as rotas do Portal já nasceram
    com o prefixo /portal (ver docstring do módulo), então repassar o
    ambiente intocado é o que faz url_for, redirect e o <form method=
    "post"> sem action do Portal continuarem funcionando exatamente como
    localmente."""
    caminho = environ.get("PATH_INFO", "")
    host = _host_pedido(environ)
    if PORTAL_HOST and host == PORTAL_HOST:
        return portal_app.wsgi_app(environ, start_response)
    if PAINEL_HOST and PORTAL_HOST and host == PAINEL_HOST:
        if caminho.startswith("/portal"):
            consulta = environ.get("QUERY_STRING", "")
            return _redirecionar(
                f"https://{PORTAL_HOST}{caminho}" + (f"?{consulta}" if consulta else ""),
                start_response,
            )
        return painel_app.wsgi_app(environ, start_response)
    if caminho.startswith("/portal"):
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


def _enviar_backup_ao_drive(pasta_backup) -> None:
    """Cópia FORA do Railway (2026-10-14): a pasta de main() fica no mesmo
    volume do banco e sem documentos. Aqui vai tudo -- bancos, documentos,
    fotos -- num .zip para o Google Drive do dono, guardando os últimos
    BACKUP_MANTER_ULTIMOS. Falha aqui só vira log: o backup local da
    rodada já está salvo, e o processo nunca cai por causa do Drive."""
    import tempfile
    from pathlib import Path

    from core.db import backup as modulo_backup
    from integracoes import google_drive

    if not google_drive.drive_configurado():
        _log("Google Drive não autorizado -- cópia externa pulada "
             "(ver integracoes/drive_autorizar.py).", origem="backup-drive")
        return
    with tempfile.TemporaryDirectory() as temporaria:
        nome = f"erp_smith_producao_{Path(pasta_backup).name}.zip"
        arquivo = modulo_backup.empacotar_para_envio(Path(pasta_backup), Path(temporaria) / nome)
        saida = google_drive.enviar_backup(arquivo, manter_ultimos=modulo_backup.MANTER_ULTIMOS)
    # Batimento só com o .zip FORA do Railway: o backup no próprio volume
    # sozinho não protege do que mais importa (core/saude.py).
    from core import saude
    saude.registrar("backup")
    _log(f"Enviado ao Drive: {nome} ({saida['tamanho'] // 1024} KB); "
         f"{len(saida['apagados'])} antigo(s) apagado(s).", origem="backup-drive")


def _loop_backup() -> None:
    from core.db import backup as modulo_backup

    time.sleep(_ATRASO_INICIAL_BACKUP_SEGUNDOS)
    while True:
        try:
            pasta = modulo_backup.main(incluir_documentos=False)
            try:
                _enviar_backup_ao_drive(pasta)
            except Exception:
                _log("Falhou o envio ao Drive:", origem="backup-drive")
                traceback.print_exc()
        except Exception:
            _log("Falhou:", origem="backup")
            traceback.print_exc()
        time.sleep(_INTERVALO_BACKUP_SEGUNDOS)


def _loop_poller_email() -> None:
    # atendimento.poller.loop() já é o loop pronto (verificar a cada 60s,
    # try/except por rodada) -- rodar como thread aqui é só trocar QUEM
    # chama, nunca reimplementar COMO verifica.
    from atendimento.poller import loop as poller_loop

    poller_loop()


if __name__ == "__main__":
    # Migrações idempotentes rodam na subida: produção já recebeu tabela
    # atrasada duas vezes porque ninguém rodou o script à mão.
    from core.db.migrar_itens_por_processo import migrar as _migrar_itens_por_processo
    print("Migração itens por processo:", _migrar_itens_por_processo(), flush=True)
    from core.db.migrar_codigo_portal import migrar as _migrar_codigo_portal
    print("Migração código do Portal:", _migrar_codigo_portal(), flush=True)
    from core.db.migrar_convite_usuario import migrar as _migrar_convite_usuario
    print("Migração convite de usuário:", _migrar_convite_usuario(), flush=True)
    from core.db.migrar_documento_final import migrar as _migrar_documento_final
    print("Migração documento final do processo:", _migrar_documento_final(), flush=True)
    threading.Thread(target=_loop_sincronizacao_habitualidade, daemon=True).start()
    threading.Thread(target=_loop_backup, daemon=True).start()
    threading.Thread(target=_loop_poller_email, daemon=True).start()

    porta = int(os.environ.get("PORT", "8000"))
    print(f"Painel + Portal (produção) ouvindo em 0.0.0.0:{porta} "
          f"(/portal/* -> Portal do Cliente, resto -> painel)")
    serve(_despachar_por_prefixo, host="0.0.0.0", port=porta, threads=8)
