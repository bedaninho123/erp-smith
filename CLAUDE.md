# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

ERP Smith: um ERP inteligente de atendimento e gestão de processos, desenhado para ser multi-domínio (não específico de um segmento). O piloto em produção é para um **despachante especializado em Clube de Tiro** (documentação de CR/CRAF, transferência de arma, habitualidade). O documento de arquitetura original — visão de produto, princípios, fases de migração planejadas — está em `../PROJETO_1.md` (um nível acima da raiz do repo). Leia-o antes de qualquer mudança estrutural.

## Comandos

A suíte automatizada (`pytest`) cobre só o que dói perder: isolamento de dado entre clientes do Portal e entre empresas nos dois apps, o token de login sem senha, o freio determinístico do Auditor, e uma varredura estática (`tests/test_empresa_id_propagado.py`) que confere se toda função que exige `empresa_id` está sendo chamada com ele — ela lê o código em vez de executar, então alcança os caminhos que os testes de verdade nunca percorrem. O resto continua sendo validado rodando os módulos diretamente — a maioria tem um bloco `if __name__ == "__main__":` com um teste de fumaça usando dado real do banco — e testando o fluxo completo pelo painel web ou por e-mail real.

> **Quem roda o quê (decidido em 2026-08-25).** O Claude Code **não roda**
> os módulos cujo `__main__` lê o banco real (`motor_ia.classificador`,
> `motor_ia.orquestrador`, `motor_ia.consultor`, `motor_ia.demo_pipeline`,
> `motor_ia.identificador_cliente`, `core.motor_empresas`,
> `core.db.auditar_documentos`). Eles imprimem nome e dado de pessoa de
> verdade na tela, e tudo que o assistente lê entra na conversa que sobe
> para o servidor do modelo. Esses ficam para o usuário rodar quando
> quiser. O assistente usa `pytest`, que roda em banco temporário com
> gente fictícia, e os `__main__` que são só lógica ou dado simulado
> (`core.motor_identidade`, `integracoes.shooting_house`,
> `integracoes.diagnostico_shooting_house`) — este último por desenho
> nunca imprime valor, só nome de campo.

```bash
# Ambiente (sempre usar o venv, nunca o Python global)
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Suíte de testes
.venv\Scripts\python.exe -m pytest tests/ -v

# Painel administrativo (localhost:5000) -- ferramenta principal de dev e uso diário
.venv\Scripts\python.exe -m webapp.app

# Definir/redefinir a senha de um usuário do painel (interativo, nunca digitar a senha em outro lugar)
.venv\Scripts\python.exe -m webapp.definir_senha

# Painel de DEMONSTRAÇÃO (localhost:5010) -- banco temporário de gente fictícia,
# apagado ao fechar. Use este para conferir tela nova ou mostrar o sistema a
# alguém sem abrir nome, CPF e documento de cliente de verdade. Login e senha
# aparecem no console.
.venv\Scripts\python.exe -m webapp.rodar_demo

# Webhook de atendimento (localhost:5001) -- endpoint POST /webhook/mensagem
.venv\Scripts\python.exe -m atendimento.webhook

# Portal do Cliente (localhost:5002) -- autoatendimento, login sem senha por link mágico
.venv\Scripts\python.exe -m portal.app

# Verificar a caixa de entrada uma vez (usado pela Tarefa Agendada do Windows)
.venv\Scripts\python.exe -m atendimento.poller --uma-vez
# Verificar agora, com janela visível (uso manual) -- dá duplo-clique em:
atendimento\verificar_agora.bat
# Loop contínuo (uso manual, terminal aberto)
.venv\Scripts\python.exe -m atendimento.poller

# Instalar/remover a Tarefa Agendada do Windows que roda o poller a cada 2 min
atendimento\instalar_tarefa_agendada.bat
atendimento\remover_tarefa_agendada.bat

# Conferir a integração com o Shooting House SEM expor dado de ninguém
# (imprime só a estrutura da resposta; roda com SHOOTING_HOUSE_ATIVO desligado)
.venv\Scripts\python.exe -m integracoes.diagnostico_shooting_house

# Rodar um módulo isolado do Motor IA (smoke test). ATENÇÃO: estes leem o
# banco REAL e imprimem dado de pessoa na tela -- rodar você mesmo, não
# pedir ao assistente (ver "Quem roda o quê" acima)
.venv\Scripts\python.exe -m motor_ia.classificador
.venv\Scripts\python.exe -m motor_ia.orquestrador
.venv\Scripts\python.exe -m motor_ia.demo_pipeline   # pipeline completo com dado real

# Recriar os bancos SQLite do zero, na ordem (o --recriar guarda o banco atual
# como backup_AAAAMMDD_HHMMSS.db na mesma pasta antes de apagar)
.venv\Scripts\python.exe -m core.db.criar_banco --recriar
.venv\Scripts\python.exe -m core.db.migrate_dados_teste        # cria EMP-000001 + dado migrado da planilha
.venv\Scripts\python.exe -m core.db.gerar_clientes_ficticios   # aceita um empresa_id como argumento
.venv\Scripts\python.exe -m core.db.popular_documentos_exigidos
.venv\Scripts\python.exe -m core.db.migrar_aprovacao_documentos  # idempotente, roda sobre banco em uso
.venv\Scripts\python.exe -m core.db.migrar_papeis_usuario         # idempotente, normaliza usuario.papel para Gestor/Atendente
.venv\Scripts\python.exe -m core.db.migrar_permissoes_usuario     # idempotente, cria a tabela usuario_permissao
.venv\Scripts\python.exe -m core.db.migrar_log_administrativo     # idempotente, cria a tabela log_administrativo
.venv\Scripts\python.exe -m core.db.migrar_conversas_crm          # idempotente, liga mensagens antigas a conversas (tela Atendimentos)

# Conferir se a tabela documento bate com os arquivos em disco (só relata, nunca apaga)
.venv\Scripts\python.exe -m core.db.auditar_documentos

# Backup do banco (Core + Domínio) e da pasta de documentos, com rotação (manual)
.venv\Scripts\python.exe -m core.db.backup
# Instalar/remover a Tarefa Agendada do Windows que roda o backup todo dia às 3h
core\db\instalar_tarefa_backup.bat
core\db\remover_tarefa_backup.bat
# Panorama de habitualidade do clube: espelha a lista de filiados e conta
# participações. --limite controla quantos CPFs por rodada (padrão 150)
.venv\Scripts\python.exe -m domain.clube_tiro.sincronizar_habitualidade
.venv\Scripts\python.exe -m domain.clube_tiro.sincronizar_habitualidade --somente-lista
# Instalar/remover a Tarefa Agendada que roda isso 4x ao dia
domain\clube_tiro\instalar_tarefa_habitualidade.bat
domain\clube_tiro\remover_tarefa_habitualidade.bat
# Banco de Domínio já em uso, sem a tabela filiado: idempotente
.venv\Scripts\python.exe -m domain.clube_tiro.db.migrar_filiados

.venv\Scripts\python.exe -m domain.clube_tiro.db.criar_banco --recriar
.venv\Scripts\python.exe -m domain.clube_tiro.db.popular_conhecimento
.venv\Scripts\python.exe -m domain.clube_tiro.db.popular_campeonatos_2026

# Listar as empresas cadastradas (multi-tenant)
.venv\Scripts\python.exe -m core.motor_empresas

# Autorizar o Gmail (OAuth2 -- interativo, roda uma vez por máquina, o usuário faz o consentimento no navegador)
.venv\Scripts\python.exe -m integracoes.gmail_autorizar
```

Ao editar `.env`, use `.env.example` como referência da lista completa de variáveis esperadas.

## Arquitetura

O sistema é dividido em camadas com uma regra inegociável: **a IA nunca contém regra de negócio.** Regra de negócio (validação de status, quem pode ser responsável, o que conta como "cliente ativo") vive no Core; conhecimento de domínio (o que é CR, quantos treinos exige habitualidade) vive no Domínio; a camada Motor IA só interpreta, planeja, consulta e redige.

```
core/          -- genérico, reutilizável entre qualquer domínio futuro (não é específico de clube de tiro)
domain/clube_tiro/ -- conhecimento específico deste domínio, banco físico separado
motor_ia/      -- Classificador → Planejador → Consultor → Redator → Auditor → Atualizador de Memória
atendimento/   -- canais de entrada (webhook, poller de e-mail) -- todos chamam o mesmo orquestrador
integracoes/   -- OpenAI, Gmail, Shooting House (API externa do clube de tiro)
webapp/        -- painel administrativo Flask (ferramenta de uso real, não só de dev)
```

### Dois bancos SQLite físicos, uma conexão lógica

`core/db/erp_smith.db` (Core) e `domain/clube_tiro/db/dominio_clube_tiro.db` (Domínio) são arquivos separados de propósito — a separação física é o que garante que o Core nunca tenha uma referência hardcoded ao domínio de clube de tiro (pré-requisito para o dia em que um segundo domínio, ex. advocacia, for plugado). `core/conexao.py` conecta só ao Core; `motor_ia/conexao.py` importa `CORE_DB` de lá e faz `ATTACH DATABASE` do banco de Domínio na mesma conexão sob o alias `dominio`, permitindo joins entre os dois numa única query sem misturar os arquivos. SQLite não aplica FK entre bancos ATTACHed — a integridade referencial cross-domínio é responsabilidade do código, não do banco.

### Multi-tenant: toda linha pertence a uma empresa

Ver `docs/schema_multi_tenant.md`. Em resumo: toda tabela do Core tem `empresa_id`, e `core/conexao.py::conectar(empresa_id)` **exige** a empresa — registra a função SQL `empresa_atual()`, que é o que faz as views do Core se filtrarem sozinhas. Quem precisa enxergar o banco inteiro (só scripts de setup e `core/motor_empresas.py`) usa `conectar_admin()`, que de propósito **não** registra a função: uma view consultada por ali levanta `no such function: empresa_atual` em vez de devolver dado de todas as empresas misturado. Falha fechado, não aberto.

No Domínio a regra se divide em duas: `conhecimento` é compartilhado (legislação federal, sem `empresa_id`), `campeonato` e `resultado_campeonato` são dado operacional da empresa e têm a coluna — e como o banco de Domínio é anexado, não passa pelas views do Core: filtro por `empresa_id` na mão, sempre.

Os IDs (`CLI-000001`…) continuam com numeração **global**, não por empresa. Fica estranho ver `CAS-000001` numa empresa e `CAS-000002` na outra, e é de propósito: numerar por empresa exigiria o filtro nos 5 geradores e abriria risco de colisão.

Nos apps (`webapp/`, `portal/`) as views não protegem nada — os dois consultam tabela crua, então **todo `WHERE` precisa do filtro de empresa escrito à mão**. A empresa vem sempre da sessão (`session["empresa_id"]`, posta no login a partir de `usuario.empresa_id` ou `cliente.empresa_id`) e **nunca** da requisição. Nos canais de entrada (`atendimento/`), vem da configuração do servidor (`ERP_EMPRESA_ID`), também nunca do corpo do POST: o webhook só tem um segredo compartilhado como autenticador. Antes de dar por pronta qualquer consulta nova nesses arquivos, rodar `tests/test_isolamento_painel.py` e `tests/test_isolamento_portal.py`.

### Atendimentos (CRM): a Conversa é o envelope, e cada canal é um fio separado

`core/motor_conversas.py` (2026-08-21) alimenta a tabela `conversa`, que
existia desde o Core mínimo mas **nunca era escrita pelo pipeline** — só
tinha linha de migração. Sem ela, cada `mensagem` ficava solta e não
havia histórico navegável de um cliente. A tela "Atendimentos" do painel
é quem lê isso.

Regra de agrupamento: **uma conversa por (cliente, canal)**. E-mail e
WhatsApp da mesma pessoa são fios distintos de propósito — têm ritmo e
histórico próprios, e juntá-los produziria uma thread ilegível.
Conversa encerrada nunca é reaproveitada (encerrar é gesto deliberado do
atendente); a próxima mensagem abre uma nova.

Não confundir `conversa` com `sessao`: sessão é contexto curto do Motor
IA, expira sozinha, existe pra IA saber do que se falava agora. Conversa
é registro longo pra uma **pessoa** ler depois, nunca expira. Um cliente
tem várias sessões dentro de uma conversa.

Na thread, cada linha de `mensagem` vira **até duas bolhas**: o que o
cliente escreveu (`mensagem`) e o que saiu como resposta (`resposta_ia`)
— é assim que a tabela guarda desde sempre, um par por linha. Resposta
escrita à mão pelo painel entra como `origem='Atendente'` com `mensagem`
vazia, sem tabela nova.

Resposta digitada no painel **não passa pelo Motor IA nem pelo Auditor**,
de propósito: quem digitou já é o humano que a revisão humana existe pra
garantir.

`CANAIS_VALIDOS` é lista controlada em código (mesmo padrão de
`STATUS_VALIDOS` do Caso e `PAPEIS_VALIDOS`), não `CHECK` no schema. O
valor gravado é sempre a chave (`"Email"`), nunca o rótulo de tela
(`"E-mail"`) — escrever o rótulo no banco quebra o filtro por canal.
Banco em uso com mensagem anterior a isso: rodar
`core.db.migrar_conversas_crm` (idempotente) — liga as mensagens órfãs,
faz as conversas reconstruídas nascerem `Encerrada` (histórico, não
fila) e normaliza rótulos de canal legados da planilha/Make (`Webhook` →
`Email`), relatando na tela o que mudou.

### Toda saída pro cliente passa por `entregar_resposta()`

`atendimento/processar.py::entregar_resposta(canal, destino, texto)` é o
ponto único de saída do sistema. Antes dela, `processar_mensagem` mandava
e-mail direto e tratava qualquer outro canal como "não envia" — toda
resposta de WhatsApp teria sido gerada e descartada em silêncio. O painel
usa a mesma função (por isso ela é pública, não `_privada`): ter uma
segunda implementação de "como se manda mensagem" lá repetiria o erro que
a existência do próprio `processar.py` evitou entre webhook e poller.

Aprovar um rascunho pendente devolve pelo **canal de origem da pergunta**
(`mensagem.canal`), nunca sempre por e-mail.

### WhatsApp: simulado até o número ser migrado, e isso tem custo real

`integracoes/whatsapp.py`, mesmo padrão de `shooting_house.py`: sem
`WHATSAPP_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` no `.env`, grava o que teria
sido enviado em `integracoes/whatsapp_simulado.log` (gitignored — guarda
texto de atendimento real) e devolve `simulado: True`. A tela avisa isso
em cima, e a confirmação de envio diz "NÃO enviado" com todas as letras —
o pior resultado possível seria o usuário achar que o cliente recebeu
algo que ninguém recebeu.

Três coisas que **não** são detalhe técnico e precisam estar claras antes
de configurar credencial:

1. O aplicativo **WhatsApp Business não tem API**. Migrar o número para a
   Cloud API o **tira do aplicativo** — não dá pra ter os dois no mesmo
   número. Todo atendimento passa a acontecer pelo painel.
2. A Meta entrega mensagem recebida só em **HTTPS público**. Enquanto
   tudo roda em localhost com port-forward (decisão de 2026-07-25), não
   há endereço pra ela chamar: receber exige resolver hospedagem antes.
3. **Janela de 24h**: fora de 24h da última mensagem do cliente, a Meta
   só aceita template aprovado por ela, não texto livre. `enviar_mensagem`
   propaga o erro real da Meta em vez de um 400 seco, porque é esse o
   caso comum.

Bibliotecas não-oficiais de WhatsApp Web (`whatsapp-web.js` e afins)
ficaram deliberadamente de fora: violam os termos da Meta e o risco é o
número do clube ser banido — caro demais num negócio com um número só.

Identificação no WhatsApp é pelo **telefone**, então
`motor_ia/identificador_cliente.py` passou a buscar por ele (prioridade
CPF > e-mail > telefone > nome). O casamento é pelos **8 últimos
dígitos**: `cliente.telefone` é texto livre com todo tipo de formato no
cadastro histórico, a Meta manda só dígitos com DDI, e o nono dígito
brasileiro varia. Oito dígitos dentro de uma empresa só é específico o
bastante — e o filtro de `empresa_id` continua sendo a trava real.

### O Caso é a entidade central, não Cliente nem Processo

`Cliente → Caso → Processo → Documento`, mais `Sessão`/`Memória_IA` (contexto de conversa) e `Histórico`/`log_ia` (auditoria). Um cliente cadastrado **não implica** que ele seja um atirador ativo do clube — alguém pode só usar o serviço de transferência de arma sem nunca ter sido atirador (ver `integracoes/shooting_house.py`: CPF sem perfil conhecido retorna "sem registro", nunca dado fabricado).

Todo ID segue o padrão `PREFIXO-NNNNNN` (6 dígitos, ex. `CAS-000001`, `CLI-000001`, `MSG-000001`). Gerado com `MAX(CAST(SUBSTR(id, N) AS INTEGER))+1` sobre a tabela — o mesmo padrão é reimplementado em cada `motor_*.py` do Core (`core/motor_casos.py`, `core/motor_mensagens.py`, `core/motor_log_ia.py`, `motor_ia/atualizador_memoria.py`), não há um gerador de ID compartilhado.

### Motor IA só lê Views, nunca tabela crua

`core/db/views.sql` define `VW_CLIENTE`, `VW_PROCESSO`, `VW_SERVICO`, `VW_CHECKLIST_SERVICO` — essa é a fronteira de leitura que qualquer módulo do Motor IA deve respeitar. `motor_ia/consultor.py` é o único módulo que efetivamente consulta dado (views do Core + tabela `conhecimento` do Domínio + `integracoes/shooting_house.py` externo), guiado por `motor_ia/planejador.py` (roteamento determinístico, não chama IA nenhuma). Ao adicionar uma fonte de dado "genérica" nova ao Consultor (catálogo, base de conhecimento), pensar se ela precisa de filtro por relevância antes de entrar no bloco de fatos — já aconteceu duas vezes (`VW_SERVICO` e `conhecimento`) de a IA despejar um catálogo inteiro numa pergunta que só precisava de um item, porque a fonte foi incluída sem filtro. `VW_CHECKLIST_SERVICO` segue a mesma cautela: o Consultor só anexa o checklist completo (`documento_exigido`, agrupado em Python) quando `classificacao.servico_mencionado` bateu exato com um serviço; na resposta de catálogo inteiro (pergunta genérica) continua usando o resumo curto de `servico.documentos_obrigatorios`.

### Prompts são arquivos, nunca hardcoded

`motor_ia/prompts/*.md`, carregados em runtime e com placeholders (`{lista_servicos}`, `{lista_categorias_conhecimento}`) preenchidos dinamicamente a partir do banco — nunca uma lista fixa no código.

### Datas e contas nunca são feitas pela IA

Onde a resposta depende de aritmética de data (ex. próxima confirmação cadastral do CR), o cálculo é feito em Python antes de chegar no prompt (`integracoes/shooting_house.py`), e o texto final só fraseia o número pronto. LLM não deve fazer conta.

### Fluxo do orquestrador

`motor_ia/orquestrador.py::atender_mensagem()` é o ponto de entrada único: identificar cliente → classificar → planejar → localizar/criar sessão e caso → consultar → redigir → auditar → (se aprovado) atualizar sessão/memória. `atendimento/webhook.py` e `atendimento/poller.py` chamam a mesma função via `atendimento/processar.py` — nenhuma lógica duplicada por canal (webhook vs. e-mail).

O Auditor (`motor_ia/auditor.py`) tem duas camadas: uma checagem determinística sem IA (se o Planejador já sinalizou "precisa humano", nunca chama a OpenAI, força `encaminhar_humano`) e uma checagem factual via IA que compara a resposta do Redator contra o mesmo bloco de fatos, podendo reter (`revisar`) uma resposta com inconsistência.

**Modo de revisão humana** (`configuracoes.revisao_humana_ativa`, ligado por padrão): enquanto ativo, toda resposta com ação `enviar` fica pendente de aprovação manual no painel (aba "Aprovações Pendentes") em vez de sair sozinha — freio de segurança para a fase de validação, dado o risco regulatório do domínio (documentação de arma de fogo). Desligar mudando o valor na tabela `configuracoes` (editável pela própria tela de Configurações do painel), sem precisar mudar código.

### Toda mudança de estado do Caso passa pelo Core, nunca é feita direto no banco pela camada de cima

`core/motor_casos.py::atualizar_status()` / `atualizar_responsavel()` validam (status contra lista controlada, usuário ativo) e sempre gravam em `historico`. O webapp (`webapp/app.py`) só chama essas funções — não faz `UPDATE` direto na tabela `caso`.

### Tarefas: trabalho com dono e data, diferente de `proxima_acao`

(2026-08-27.) A tabela `tarefas` existia no schema desde o Core mínimo e
**nunca foi usada** — só o script de dado de teste escrevia nela, e só
`motor_ia/montador_contexto.py` lia. Prazo de despachante não morava em
lugar nenhum. `core/motor_tarefas.py` é o motor que faltava; a tela
"Tarefas e Prazos" e o bloco dentro da ficha do Caso são as duas
superfícies (a mesma tarefa aparece nos dois).

Não confundir com `processo.proxima_acao`: aquilo é o **estado** de um
processo perante o órgão ("aguardando comprovante"). Tarefa é trabalho
com dono e data, que alguém marca como feito. Um processo parado pode
ter três tarefas; uma tarefa pode não ter processo nenhum.

Regras que vivem no motor, e por isso nenhuma tela pode reimplementar:

- **Toda tarefa pertence a um caso** (`caso_id`/`cliente_id` são NOT
  NULL), e o `cliente_id` é lido do caso, nunca de quem chamou.
- **`data_conclusao` é consequência do status**: concluir carimba,
  reabrir apaga. Tarefa reaberta com "concluída em" de antes seria data
  que já não significa nada.
- **"Atrasada" só vale para tarefa em aberto** — trabalho feito ontem
  com prazo de anteontem não é pendência.
- **Hoje é calculado em Python** (`hoje_local()`), nunca com
  `date('now')` do SQLite, que é UTC: às 21h de Brasília toda tarefa do
  dia apareceria atrasada, justamente no fim do expediente.
- **Prazo é um DIA** (`AAAA-MM-DD`). As linhas migradas da planilha
  guardam ISO completo, e `'...T00:00:00Z' > '2026-08-27'` na comparação
  de texto — daí o `SUBSTR(prazo, 1, 10)` em todo filtro de data.
- **Contagem e lista saem da mesma função** (`contar_tarefas` chama
  `listar_tarefas`): duas implementações da regra de atraso divergem, e
  aí a tela mostra 3 atrasadas numa lista com 2 linhas.

O histórico do Caso registra criação, status, responsável e prazo — não
edição de descrição, que viraria log de digitação. Sempre com
`tipo_evento='outro'`: os outros quatro valores do CHECK falam do Caso, e
um `mudanca_status` ali seria lido como status **do Caso**.

`tarefas` entrou no catálogo de `FUNCOES_VALIDAS`. As rotas de
criar/editar/concluir levam `funcao_required("tarefas", "casos")` porque
a tarefa é alcançável das duas telas.

### Tela inicial: resumo com caminho, não painel de números

(2026-08-27.) O painel abria direto na lista de Casos e não havia lugar
que respondesse "o que precisa da minha atenção hoje?". `/api/inicio`
junta o que já existe em outras telas — **nenhuma contagem nova é
implementada ali**, cada bloco chama a mesma função da tela de destino.

O valor da tela é o caminho: cada número é um botão que leva à tela onde
aquele trabalho é feito, já com o filtro aplicado (atrasadas → Tarefas
filtrado por atrasadas). Número que não leva a lugar nenhum é decoração.

Dois cuidados que não são óbvios: (a) cor semântica só quando o número
pede ação — zero em vermelho treina o olho a ignorar vermelho, e é o
vermelho que precisa funcionar no dia em que houver 6 atrasadas; (b) a
rota tem `funcao_required` com as cinco funções, mas isso **libera se
qualquer uma bater** — então cada bloco é conferido de novo com `_pode()`
dentro da rota. Sem isso, um Atendente com só "casos" receberia a fila de
aprovações pendentes de brinde. Coberto por `tests/test_tela_inicial.py`.

"Caso parado" é caso vivo sem atualização há 7 dias. A tela de Casos
promete mostrar "o que está parado" desde sempre, mas ordenada por data
ela mostra o que é **recente** — o parado fica no fim, que é onde ninguém
olha.

### Auditoria: o registro passou a ser lido por gente

(2026-08-27.) O `log_administrativo` existia desde a auditoria de riscos
de 2026-07-30, e a única forma de ler era `SELECT` na mão — ou seja, na
prática ninguém lia. A tela "Auditoria" (Gestor, `@gestor_required`,
**fora** do catálogo de permissões como Configurações) é só leitura: não
existe rota de escrita, porque registro que a própria pessoa auditada
pode alterar não audita nada.

O que a tela acrescenta a listar linhas: avisa quantos pedidos de dado
sensível foram **recusados** nos últimos 7 dias e explica o que isso
significa (um recusado isolado é cliente digitando o CPF errado; vários
seguidos no mesmo cliente é alguém tentando adivinhar CPF de outra
pessoa — ver o portão de identidade). Esse era o sinal mais importante do
registro, e era justamente o que ninguém via.

`USR-000003` e `CLI-000012` são traduzidos para nome de gente na
exibição, com o ID ao lado: o log guarda ID de propósito (nome muda, ID
não), mas tela de auditoria que exige decorar identificador não é lida.

### webapp/ é o painel administrativo real, não uma ferramenta descartável

Flask + Jinja + JS puro (sem build step, sem framework front-end) servido via CDN para o tema AdminLTE 3. Autenticação por sessão simples (`werkzeug.security`, `usuario.senha_hash`) — sem biblioteca de auth adicional. Todas as rotas `/api/*` exigem login (`@login_required`); a senha de um usuário nunca é definida por código, só via `webapp/definir_senha.py` rodado interativamente pelo próprio usuário. A UI inteira é uma SPA de uma página só (`webapp/templates/index.html`) alternando divs `.view` via JS — não há rotas de URL por tela.

### Dois papéis, Gestor e Atendente, validados em código, não no schema

`usuario.papel` (2026-07-29) tem dois valores de verdade —
`core/motor_usuarios.PAPEIS_VALIDOS` — Gestor (acesso total) e Atendente
(opera casos, clientes e documentos, sem acesso administrativo). Mesmo
padrão do `status` do Caso: a validação vive num motor do Core
(`core/motor_usuarios.py`), não em `CHECK` no `schema.sql`.

O papel vem para a sessão no login (`session["papel"]`) e o decorator
`gestor_required` (`webapp/app.py`, sempre depois de `@login_required`)
protege o que é administrativo: a tela de Configurações inteira (incluindo
a própria gestão de usuários) e as três ações de remoção (checklist,
campeonato, resultado). O resto do painel — casos, clientes, documentos,
aprovar/recusar checklist, criar/editar campeonato e resultado — continua
igual para os dois papéis. No template, os botões de remoção e o item de
menu Configurações só renderizam para Gestor (`usuario_papel` no Jinja,
`USUARIO_PAPEL` no JS) — reforço de interface, a trava de verdade é o
decorator.

Criar usuário é feito pela própria tela (Configurações → Usuários, Gestor
only), mas isso não inclui senha: nasce com `senha_hash=NULL` ("login
ainda não configurado") e continua exigindo `webapp/definir_senha.py`
rodado pelo próprio dono — regra inegociável, não muda com esta mudança.
Um Gestor não consegue mudar o próprio papel nem se desativar (bloqueio
na rota, comparando `usuario_id` do alvo com `session["usuario_id"]`) —
sem isso a empresa poderia ficar sem ninguém com acesso administrativo.

Banco já em uso, com `usuario.papel` fora desses dois valores: rodar
`core.db.migrar_papeis_usuario` (idempotente) — normaliza tudo para
`'Gestor'`, e o próprio Gestor rebaixa quem quiser depois pela tela.

### Dentro de Atendente, permissão granular por função

(2026-07-30) Gestor continua com acesso total e intocável — o catálogo
abaixo só tem efeito pra quem é Atendente. Catálogo em
`core/motor_usuarios.FUNCOES_VALIDAS`, mapeado 1:1 com as seções do menu
(`atendimentos`, `casos`, `tarefas`, `clientes`, `aprovacoes_pendentes`,
`documentos_aprovar`, `campeonatos`, `resultados`, `testar_pipeline`,
`status_projeto` — `atendimentos` entrou em 2026-08-21 com a tela de CRM,
`tarefas` em 2026-08-27). A tela **Início** fica de fora do catálogo de
propósito: ela é resumo do que a pessoa já pode ver, e cada bloco some
sozinho para quem não tem aquela função.
Remoção (checklist/campeonato/resultado) e a área administrativa
(Configurações, gestão de usuário e de permissão) não entram no catálogo
— seguem travadas só pro Gestor, sem toggle, de propósito.

Regra central da tabela `usuario_permissao`: **ausência de linha
significa permitido**. Só ganha linha quando o Gestor desliga ou religa
algo pela tela de Usuários (botão "Permissões" na linha do Atendente).
Mesmo espírito do `migrar_papeis_usuario`: ninguém perde acesso por falta
de linha no banco. `core/motor_usuarios.tem_permissao()` é quem decide
isso; `funcao_required(<chave>)` (`webapp/app.py`, sempre depois de
`@login_required`, nunca junto de `@gestor_required` — uma rota é
administrativa OU operacional, não as duas) é o decorator que aplica.

No template, `funcoes_ativas` (calculado em `index()` a partir de
`listar_permissoes`, ou o catálogo inteiro direto se Gestor) decide o que o menu
mostra — reforço de interface, a trava de verdade é o decorator, que
consulta o banco de novo em cada rota. `documento_arquivo`
(`/api/documentos/<id>/arquivo`) fica de fora do catálogo, sem
`funcao_required`, de propósito: é usado tanto pela ficha do Caso quanto
pela do Cliente, e a barreira real (documento de outra empresa) já é o
filtro de `empresa_id`, não isto.

Banco já em uso sem a tabela: rodar `core.db.migrar_permissoes_usuario`
(idempotente, só cria a tabela — sem seed, porque ausência de linha já
significa permitido).

### Endurecimento de produção (auditoria de riscos, 2026-07-30)

Uma auditoria pedida pelo usuário sobre pressupostos fracos do projeto
levantou cinco pontos, todos corrigidos:

- **Rede de segurança pro controle de acesso.** `funcao_required(...)`
  (`webapp/app.py`) valida cada chave contra `FUNCOES_VALIDAS` **na hora
  de decorar a rota** (import time, não só em teste) — um typo estoura
  já ao subir o app, em vez de virar acesso liberado em silêncio
  (`tem_permissao()` devolve `True` quando não acha a chave). Os três
  decorators (`login_required`, `gestor_required`, `funcao_required`)
  gravam um marcador em si mesmos (`_login_protegido`,
  `_controle_acesso`) que `tests/test_controle_acesso_propagado.py` usa
  pra varrer `app.url_map` de verdade e confirmar que toda rota `/api/*`
  tem os dois — mesmo espírito do `test_empresa_id_propagado.py`, só que
  por introspecção de função em vez de AST. Rota nova que fique sem
  controle de acesso quebra a suíte, não precisa que alguém lembre de
  escrever um teste específico pra ela.
- **Log administrativo.** `core/motor_log_administrativo.py` registra
  (append-only, mesma transação da mudança) toda troca de papel, ativo
  ou permissão de usuário, e toda mudança de configuração da empresa —
  inclusive `revisao_humana_ativa`, o freio que faz a IA parar de enviar
  sozinha. Antes disso, "quem desligou a revisão humana" não tinha
  resposta nenhuma. Só existe pra consulta manual (`listar()` ou SELECT
  direto) por enquanto, não tem tela própria no painel.
- **SQLite em modo WAL + `busy_timeout`** (`core/conexao.py`,
  `motor_ia/conexao.py`, e os dois motores do Domínio que conectam
  direto — `domain/clube_tiro/motor_campeonatos.py`,
  `motor_resultados.py`). Sem isso, painel + poller (a cada 2 min) +
  webhook escrevendo no mesmo arquivo SQLite ao mesmo tempo eventualmente
  batia em "database is locked". WAL é propriedade do arquivo (uma vez
  ligado, fica ligado); `busy_timeout` é por conexão, por isso todo
  `sqlite3.connect()` do projeto pede de novo.
- **Backup diário** (`core/db/backup.py`, instalado via
  `core/db/instalar_tarefa_backup.bat`, roda às 3h). Copia banco do Core
  e do Domínio via `Connection.backup()` do próprio SQLite (não cópia
  crua do arquivo — em modo WAL, parte do commit recente só existe no
  `-wal`, cópia crua perderia isso) e a pasta
  `atendimento/documentos_recebidos/`, com rotação (`BACKUP_MANTER_ULTIMOS`,
  padrão 14). Por padrão grava dentro do próprio projeto (`BACKUP_DIR`) —
  protege contra exclusão/corrupção acidental, **não** contra falha
  física do disco; para isso, `BACKUP_DIR` precisa apontar pra fora desta
  máquina.

  Três correções ao configurar destino externo de verdade (2026-07-29):
  o módulo não chamava `load_dotenv()`, então `BACKUP_DIR` no `.env` —
  que o próprio docstring, o `.env.example` e este arquivo mandavam usar
  — não tinha efeito nenhum e o backup seguia gravando na pasta do
  projeto, calado. Agora carrega o `.env` por caminho explícito (a
  Tarefa Agendada pode rodar com outro diretório de trabalho).
  `_validar_destino()` exige que a pasta-mãe do `BACKUP_DIR` exista, em
  vez de `mkdir(parents=True)` recriar a árvore num lugar errado quando
  o destino externo não está acessível (Drive não montado, pen drive
  desconectado) e terminar com "sucesso" sem proteger nada. E tudo é
  registrado em `core/db/backup.log` (hora local), com código de saída
  != 0 na falha: a tarefa roda com `pythonw.exe`, sem console, então
  `print()` ali é descartado em silêncio — sem o log, uma falha às 3h da
  manhã não deixava rastro em lugar nenhum.
- **`WEBHOOK_SECRET` configurado.** `atendimento/webhook.py` já avisava
  no console quando essa variável está vazia ("aceita qualquer chamada
  sem autenticação") — era o estado real do `.env` até esta auditoria.

### O painel tem régua: tamanho e tipografia são regra no CSS, não escolha por tela

Padronizado em 2026-07-29, depois de medir 16 botões com **três** alturas (26/31/38px) e duas fontes na mesma tela. A causa era `style="..."` escrito direto na marcação, tela a tela. As regras vivem no `<style>` de `webapp/templates/index.html`, no bloco "SISTEMA VISUAL DO PAINEL", e valem para toda tela nova:

- **Duas alturas de controle, só**: 38px (ação principal, e todo `.form-control`) e 30px (`.btn-sm`, ação dentro de linha). Fonte 14px e 13px respectivamente.
- **Tipografia**: Big Shoulders nos títulos de tela, IBM Plex Sans no texto, IBM Plex Mono em identificador (`CAS-000001`), CPF e data — as mesmas do Portal, de propósito: são dois apps do mesmo sistema.
- **Espaçamento**: só os múltiplos `--e1`…`--e6` (4/8/12/16/24/32).
- **Bloco de dados** usa `.ficha` (grade rótulo/valor), nunca pilha de `<p><b>Rótulo:</b> valor</p>`.
- **Data nunca vai crua pra tela**: `dataBr()` para dia, `dataHoraBr()` para instante, `cpfFormatado()` para CPF (o banco guarda só dígitos).

As exceções têm nome e comentário explicando o porquê — `.miniatura` (botão que embrulha foto, não pode ter altura forçada), `.form-check-label` e `.config-chave` (texto de leitura e identificador, não viram maiúscula). Ao criar uma exceção nova, seguir o mesmo padrão: classe com nome + motivo no comentário, nunca `style` solto na marcação.

### portal/ é um app Flask separado, nunca reaproveita a sessão do painel

Ver `docs/portal_cliente_arquitetura.md` para o rascunho completo. Autoatendimento pro cliente real (não staff), rodando em porta própria (5002) com `secret_key` e nome de cookie (`SESSION_COOKIE_NAME = "portal_session"`) totalmente separados de `webapp/` — os dois podem rodar ao mesmo tempo no mesmo navegador sem misturar sessão. Login sem senha: link mágico de token único por e-mail (`core/motor_portal_auth.py`), nunca reaproveita `usuario.senha_hash`. MVP é só leitura (status do caso + checklist de documentos) + upload — sem chat com a IA pelo Portal ainda. Toda rota que recebe `caso_id`/`documento_id` do cliente **sempre** confere se o dono bate com `session["cliente_id"]` antes de ler ou escrever qualquer coisa — esse é o único ponto realmente crítico de segurança do Portal (primeira superfície pública do sistema, domínio regulado de arma de fogo): um bug aqui vaza documento de um cliente para outro.

### Checklist de documento: quem liga o arquivo ao item define o estado

`documento_checklist` liga um arquivo recebido a um item de `documento_exigido`. Quem cria essa ligação determina em que estado ela nasce, e essa é a regra inteira: marcação feita no painel nasce `Aprovado` (o funcionário abriu o arquivo pra decidir — a conferência aconteceu no mesmo gesto), envio pelo Portal nasce `Aguardando aprovação` (é uma afirmação do cliente, ninguém conferiu). `Recusado` guarda o `motivo_recusa`, que é mostrado ao cliente, e para efeito de checklist conta como faltando. **Pendente não conta na contagem X/Y nem no anel de progresso** — contar infla o progresso com trabalho que ninguém fez. A decisão continua sendo sempre humana: a IA nunca decide que um PDF é a certidão X.

O envio pelo Portal manda `processo_id` e `documento_exigido_id` vindos do navegador do cliente — `portal/app.py::upload_documento` confere que o processo pertence ao caso que já se sabe ser dele. O filtro de empresa **não** cobre isso: dois clientes da mesma empresa são o caso perigoso. Ver `tests/test_aprovacao_documentos.py`.

### Dado real de pessoa: a chave geral, o portão de CPF e o "não sei"

(2026-08-25, quando a credencial do Shooting House chegou.) Até aqui todo
dado de atirador era simulado, e um erro produzia no máximo uma resposta
errada. Com a API real, o mesmo erro entrega número de série de arma,
calibre e histórico de treino de uma pessoa de verdade. Quatro travas
nasceram disso, e nenhuma delas é opcional:

**1. `SHOOTING_HOUSE_ATIVO` é a chave geral, separada da credencial.**
Antes, a simples presença de usuário/senha no `.env` punha o sistema
inteiro em modo real de uma vez — inclusive o poller, que roda a cada 2
min pela Tarefa Agendada. Não existia como guardar a credencial e
conferir uma resposta antes de já estar atendendo cliente com ela.
`integracoes/config.py::shooting_house_ativo()` exige as três coisas:
credencial presente, chave ligada, URL em HTTPS (`validar_base_url()`
falha alto se não for — Basic Auth manda usuário e senha em toda
chamada). É também o botão de pânico: apagar o "Sim" devolve tudo pro
simulado sem mexer em código.

Para conferir a API sem ligar nada e sem dado de ninguém na tela:
`integracoes/diagnostico_shooting_house.py` — imprime só a **planta** da
resposta (nomes de campo, tipos, quantidades), nunca valores, e diz se o
mapeamento de `_normalizar_habitualidade_real()` bate com a resposta de
verdade (ele foi escrito lendo a documentação, nunca testado contra uma
resposta real). O CPF é pedido por `getpass`, então não fica no histórico
do terminal.

Achados da leitura da especificação pública completa (2026-08-25 — 40
endpoints, `api.swaggerhub.com/apis/shootinghouse/Parceiros/1.0.1`),
que contrariam o que este arquivo dizia antes:

- **`GET /checkAuth`** testa a credencial sem consultar CPF nenhum — é
  como `verificar_credencial()` e o diagnóstico respondem "a credencial é
  deste ambiente?" sem usar o dado de uma pessoa real como material de
  teste.
- **A conversão CPF → `idatirador` existe**: `/registers/shooters/{id}` e
  `/registers/shooters/weapon/{id}` aceitam `?searchBy=` ("usado para
  buscar por outro ID como CPF"). O bloqueio que justificava `consultar_cr`
  e `consultar_armas` serem eternamente simuladas **não existe** — as duas
  podem ser implementadas de verdade. `Shooter.documents.cr` traz `status`,
  `number` e `expirationDate`.
- **O mapeamento de habitualidade foi CONFIRMADO contra uma resposta real**
  (2026-08-25, credencial no `.env` com a chave geral ainda desligada): os
  cinco campos existem com os nomes exatos, e a conversão somou 38
  participações em 2 grupos de arma. Duas diferenças entre especificação e
  realidade, nenhuma em campo que usamos: a spec diz `qtd_arma`, a resposta
  traz `qtd_armas`; e existe um `evento_2` que a spec não menciona.
- **`data_participacao` vem com hora** (`"09/10/2025 16:30"`).
  `_separar_data_e_hora()` separa em `data_participacao` + `hora_participacao`,
  porque `portal/app.py` ordena com `strptime(..., "%d/%m/%Y")` e quebraria
  a tela inteira na primeira consulta real.
- **O webhook deles NÃO serve para habitualidade** — confirmado pelo
  suporte em 2026-08-26: *"o Webhook é utilizado para realizar
  sincronizações, principalmente relacionadas ao módulo Financeiro"*. Bate
  com a especificação (os campos são de inscrição em campeonato e
  pagamento). Ou seja: **não existe aviso automático quando um atirador
  lança habitualidade no tablet**, e a consulta periódica de
  `sincronizar_habitualidade.py` é o único caminho, não uma escolha.
- **O Shooting House registra acesso pela leitora Control iD**
  (confirmado pelo suporte em 2026-08-26: entrada e depois saída,
  automaticamente). Mas **a API de Parceiros não expõe leitura disso** —
  só `POST /registers/entity/access` e `/visit`, que gravam; não há GET
  nenhum de histórico de acesso. Então o sistema deles sabe quem entrou e
  o nosso não tem como perguntar. Pendente de confirmação com eles se
  existe algum endpoint fora da especificação pública.
- **A credencial ESCREVE**, não só lê: cadastra filiado, **registra evento
  de habitualidade**, registra visita, grava biometria, adiciona crédito,
  paga pedido; e `/registers/shooters/paginate` lista o clube inteiro. O
  risco de vazamento dela não é "alguém lê dado", é "alguém fabrica
  habitualidade em nome do seu cliente". Vale pedir credencial somente-leitura
  ao fornecedor.

  **Nosso cliente é somente leitura, e isso é regra.** O Shooting House é
  o sistema de registro que reporta à Polícia Federal e ao Exército
  (confirmado com o usuário em 2026-08-25): registro gravado por nós
  entraria nessa cadeia, e numa divergência quem vale é a fonte deles.
  Some-se a isso o contrato de uso da API, que veda construir sistema
  que confronte o Shooting House. `tests/test_shooting_house_somente_leitura.py`
  lê o código-fonte (AST) e falha se um `requests.post/put/patch/delete`
  aparecer nos módulos da integração — não existe teste de comportamento
  que prove a AUSÊNCIA de uma chamada, e uma escrita acrescentada daqui a
  seis meses num caminho que a suíte não percorre só apareceria gravando
  registro de verdade.

  Pelo mesmo motivo o módulo **nunca guarda cópia** do que leu (consulta
  ao vivo, sempre) — o princípio "consultar, não copiar" das views do
  Core deixou de ser elegância arquitetural e virou exigência regulatória.

**2. `ShootingHouseIndisponivel`: "não sei" nunca vira "não tem".**
Com o modo real ligado, `consultar_cr` e
`consultar_documentos_vencimento` **levantam a exceção em vez de cair no
simulado** — essas duas ainda não têm implementação real. Sem isso, um
atirador de verdade perguntando "meu CR está em dia?" receberia "não
temos registro do seu CR", porque o CPF dele não está na tabela de teste.

(`consultar_armas` **ganhou modo real em 2026-08-26** e saiu dessa lista:
o `searchBy` resolve o CPF → `idatirador`, o mesmo parâmetro que a busca
de cadastro usa. A regra continua valendo para ela em outra forma —
lista vazia é a afirmação "consultei, não tem arma", então falha de rede
vira exceção e nunca lista vazia.)
`motor_ia/consultor.py::_buscar_externo` registra a falha em
`dados["fontes_indisponiveis"]` e **não preenche a chave** (`"armas": []`
seria a afirmação "consultei, não tem nenhuma"); o Auditor tem um segundo
freio determinístico, sem gastar IA, que manda isso pra humano. No Portal
o mesmo cuidado aparece como um terceiro estado na tela: "consulta
indisponível" é visualmente diferente de "sem registro de atirador".

**3. Portão de identidade (`core/motor_identidade.py`).** Para
`CONSULTA_HABITUALIDADE`, `CONSULTA_CR` e `CONSULTA_DOCUMENTOS_VENCIMENTO`
vindas de canal não autenticado, exige o CPF escrito **na própria
mensagem**, conferindo com o cadastro de quem o e-mail/telefone
identificou. Roda no orquestrador **antes** do Consultor, então o CPF de
quem não passou nem chega a ser enviado pra API. Regra de negócio, por
isso vive no Core.

Duas sutilezas que não podem se perder: (a) identificação feita **só pelo
nome** nunca libera (`ORIGENS_INSUFICIENTES`) — o nome exibido no
cabeçalho "De:" é escolhido por quem manda, então nome + CPF viriam da
mesma mão e o portão não estaria conferindo nada; por isso
`identificar_cliente` passou a devolver a chave `identificado_por`. (b) A
mensagem de recusa é **fixa e igual para todos os motivos** — dizer "esse
CPF não confere" transformaria o portão num verificador de palpites.
Todo acesso, liberado ou negado, vai pro `log_administrativo` como
`ACESSO_DADO_SENSIVEL`; uma sequência de negados no mesmo cliente é o
sinal mais visível de alguém tentando adivinhar CPF.

Isto **não** é autenticação forte, e a honestidade sobre isso importa:
CPF circula muito no Brasil, e quem tiver CPF e falsificar o e-mail
passa. O que a regra faz é subir o degrau e compor com os outros freios
(revisão humana, filtro por empresa, registro de acesso). Autenticação de
verdade pra dado sensível é o link mágico do Portal.

**3b. O CPF é extraído em Python, e sai mascarado rumo à OpenAI.**
O portão acima chegou a comparar contra `classificacao.cpf_mencionado` —
ou seja, apoiava uma decisão de **segurança** num valor produzido pela IA
a partir da mesma mensagem que o atacante escreve. Hoje quem acha CPF em
texto é `core/motor_identidade.py::extrair_cpfs` (expressão regular,
determinística), e é essa lista que o portão usa; `cpf_mencionado` segue
existindo no Classificador mas **não decide nada** (tem comentário no
próprio campo dizendo isso).

O mesmo módulo resolve o efeito colateral que o portão criou: exigir o
CPF na mensagem fez CPF de gente real passar a fluir constantemente até
a OpenAI. `mascarar_cpfs_no_texto()` troca todo CPF por `***.***.789-**`
**no texto que vai para o Classificador** — o Classificador precisa da
intenção da frase, não do número. O texto original continua inteiro em
`mensagem`, sessão e memória: o banco é nosso, e ali o dado completo é
legítimo. O padrão também casa com telefone de 11 dígitos, o que é
aceitável nos dois usos (candidato que não é CPF simplesmente não bate
com o cadastro; e mascarar um telefone por engano erra pro lado certo).

**3c. Número de série de arma nunca entra no prompt.**
`motor_ia/redator.py::_arma_sem_serie` tira a série do bloco de dados —
que é o texto literal enviado ao Redator e ao Auditor. Duas razões: (a)
nenhuma resposta legítima precisa recitar número de série, o cliente sabe
qual arma é dele; (b) o que o modelo nunca recebe, ele nunca repete numa
resposta nem entrega a uma mensagem construída pra extrair. É a única
proteção desse tipo que não depende de a IA cooperar.

Não basta omitir o campo `serie`: a API real manda `arma_formatada` como
`"(ABA212416) Pistola - TH380 CLUBE - 380 ACP"`, com a série embutida
dentro do texto descritivo — daí a limpeza por expressão regular. O
número continua no dado (o Portal, que tem login, mostra pro dono); o
que muda é só o que atravessa a rede.

**4. Identificação ambígua não escolhe ninguém.**
`motor_ia/identificador_cliente.py` fazia `fetchone()` sobre buscas com
`LIKE` (telefone pelos 8 últimos dígitos, nome aproximado): duas pessoas
casando, o SQLite devolvia calada a primeira da varredura, e o
atendimento inteiro seguia tratando um cliente como se fosse outro.
Agora `_buscar_unico` usa `fetchmany(2)` e devolve `_AMBIGUO` — que
interrompe a identificação em vez de cair pro próximo identificador. O
orquestrador então pede o CPF, que é exato.

E o CPF não vaza mais por mensagem de erro: ele está no caminho da URL
(`.../habitualities/12345678900`), e a exceção crua do `requests` traz a
URL inteira dentro — que ia parar em `atendimento/poller.log`, na coluna
`log_ia.erro` do banco **e** num e-mail de alerta. `_chamar_api()` embrulha
toda falha em `ShootingHouseIndisponivel` com texto já limpo (`raise ...
from None` para o traceback não reexibir o original), e `_mascarar_cpf()`
existe pra qualquer texto que possa acabar em log. `allow_redirects=False`
pelo mesmo motivo de sempre: redirect para outro host reenviaria a
credencial.

Coberto por `tests/test_dado_sensivel.py`.

### Panorama de habitualidade: filiado ≠ cliente, e é retrato, não verdade

(2026-08-25.) O clube precisa ver quem está atrasado em habitualidade —
o clube inteiro, não só quem o despachante atende. Isso trouxe uma
**segunda população** para o sistema, e a distinção é inegociável:

- `core.cliente` — quem o **despachante** atende. Registro nosso, criado
  à mão quando o primeiro caso da pessoa aparece.
- `dominio.filiado` — quem passou pelo **clube**. Espelho de
  `GET /registers/shooters/paginate`, sincronizado.

Ligação pelo CPF, sem FK (bancos diferentes). Juntar as duas destruiria o
sentido de `cliente`: o clube tem ~1450 filiados e o despachante atende
um subconjunto — importar todo mundo para `cliente` seria guardar dado
pessoal de gente que ninguém atende. `filiado` fica no Domínio pelo mesmo
critério de `campeonato`: um escritório de advocacia nunca terá um.

As duas telas do painel se chamam **Clientes Despachante** e **Filiados**,
e **se enxergam pelo CPF** (2026-08-26): a lista de Filiados marca quem
também é cliente e leva à ficha; a ficha traz um bloco "no clube" com o
retrato de habitualidade (`motor_filiados.obter_por_cpf`). O cruzamento é
feito em Python trazendo o lado pequeno inteiro (`_clientes_por_cpf` em
`webapp/app.py`) — uma consulta por linha em 1500 filiados, ou um `IN` com
1500 parâmetros, seriam os dois caminhos errados.

**Os números de habitualidade em `filiado` são um retrato com data, não a
verdade.** Existem só porque desenhar um panorama do clube consultando ao
vivo seriam centenas de chamadas por tela (a API só lê habitualidade por
CPF, uma pessoa por vez). Três regras que vêm junto: toda tela mostra
`sincronizado_em`; nenhuma afirmação a cliente sai daí (pergunta de
cliente é consulta ao vivo, como o Portal já faz); e `NULL` ("nunca
consultado") nunca pode parecer `0` ("consultei, não teve").

**O sistema NÃO diz se alguém cumpriu o mínimo legal**, e isso é decisão,
não pendência. O mínimo do art. 35 do Decreto nº 11.615/2023 depende do
nível do CR (8, ou 12+4, ou 20+6) — e a API do Shooting House **não expõe
o nível de ninguém** (`documents.cr` só tem status, número e validade).
Mesmo princípio que o usuário aplicou em 2026-07-25 sobre `nivel_cr`: não
fabricar critério que ninguém confirmou. Aqui o custo de errar é dizer a
um atirador que está em dia quando não está.

A sincronização (`domain/clube_tiro/sincronizar_habitualidade.py`) roda
por Tarefa Agendada 4x ao dia e atende por rodada os `--limite` filiados
**há mais tempo sem sincronizar** — é o rodízio que cobre 900 pessoas sem
despejar tudo na API de uma vez. Falha de um não derruba a rodada nem
apaga o retrato anterior dele.

### Integrações externas simuladas até haver credencial

`integracoes/shooting_house.py` (CR e habitualidade do atirador) devolve dado simulado determinístico por CPF enquanto `SHOOTING_HOUSE_USER`/`PASSWORD` não estão configurados em `.env` — isso permite testar o pipeline inteiro sem depender do suporte do fornecedor liberar acesso. Mesmo padrão vale para qualquer integração externa nova: sempre ter um modo simulado que não bloqueia o desenvolvimento.

**Achados lendo a especificação real da API (SwaggerHub, 2026-07-30), antes mesmo de ter credencial:**

- **Bug corrigido antes de acontecer:** o branch real de `consultar_habitualidade()` só fazia `resposta.json()` cru. A resposta real de `GET /registers/habitualities/{cpf}` é colunar — `habitualidades[grupo_arma][id_arma]` com arrays paralelos por índice —, bem diferente do formato simples (`{"eventos": [...]}`) que `portal/app.py` e `motor_ia/consultor.py` já esperam desde sempre (porque só o dado simulado existia até agora). Sem correção, a integração quebraria no primeiro CPF real consultado. `_normalizar_habitualidade_real()` faz essa conversão — estrutura inferida da documentação, **nunca testada contra uma resposta de verdade**; conferir os nomes de campo (`_CAMPOS_EVENTO_HABITUALIDADE_REAL`) assim que a credencial existir.
- **CR tem mais dado do que o código assumia.** O comentário antigo dizia "endpoint real ainda não documentado" — mas `GET /registers/shooters/{shooterId}` tem `documents.cr.expirationDate`. Guardado agora em `data_expiracao_bruta`, separado de `proxima_confirmacao`, porque não está confirmado que esse campo bruto da API corresponde à regra de negócio já validada (Decreto nº 11.615/2023: CR não vence). Nenhuma lógica lê esse campo ainda.
- **`consultar_armas()` e `consultar_documentos_vencimento()` (guia de tráfego, SIMAF)** — capacidade nova, dado que a API do Shooting House expõe e o projeto não modelava. **Correção de 2026-08-26:** este parágrafo dizia que os dois endpoints só aceitam `shooterId` interno e que por isso as duas funções seriam sempre simuladas. Isso valia para `documentos-por-data-vencimento` (que filtra por intervalo de data e devolve o clube inteiro), mas **não** para armas: `/registers/shooters/weapon/{id}` aceita `?searchBy=`, e `consultar_armas` passou a ter modo real por ali. `consultar_documentos_vencimento` segue simulada.

  Ligadas ao Planejador/Consultor/Redator em seguida, no mesmo dia: `SHOOTING_HOUSE_ARMAS` entra como fonte extra de `CONSULTA_HABITUALIDADE` (o prompt do Classificador já tratava "pergunta sobre arma registrada" como parte dessa intenção, então não precisou de categoria nova); `SHOOTING_HOUSE_DOCUMENTOS_VENCIMENTO` ganhou intenção própria, `CONSULTA_DOCUMENTOS_VENCIMENTO` (diferente de `CONSULTA_DOCUMENTOS`, que é sobre exigência de serviço novo, não status de documento já existente). Testado de ponta a ponta com a OpenAI de verdade (`motor_ia/demo_pipeline.py`) — as duas intenções classificaram certo e o Auditor aprovou.

  **Bug pego no mesmo teste:** o formato de evento de habitualidade ganhou campos que às vezes são `None` (`competicao`, na maioria dos treinos que não são competição). `motor_ia/redator.py::montar_bloco_dados` fazia `"; ".join(f"{k}: {v}" for k, v in evento.items())` sem filtrar vazio — a IA copiou isso quase literal e mandou "Competição: None" pro cliente. Corrigido filtrando `if v` antes do join. Vale lembrar disso ao adicionar qualquer campo opcional novo em bloco de dados que vai pro Redator.
