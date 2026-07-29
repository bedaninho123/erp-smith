# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

ERP Smith: um ERP inteligente de atendimento e gestão de processos, desenhado para ser multi-domínio (não específico de um segmento). O piloto em produção é para um **despachante especializado em Clube de Tiro** (documentação de CR/CRAF, transferência de arma, habitualidade). O documento de arquitetura original — visão de produto, princípios, fases de migração planejadas — está em `../PROJETO_1.md` (um nível acima da raiz do repo). Leia-o antes de qualquer mudança estrutural.

## Comandos

A suíte automatizada (`pytest`) cobre só o que dói perder: isolamento de dado entre clientes do Portal e entre empresas nos dois apps, o token de login sem senha, o freio determinístico do Auditor, e uma varredura estática (`tests/test_empresa_id_propagado.py`) que confere se toda função que exige `empresa_id` está sendo chamada com ele — ela lê o código em vez de executar, então alcança os caminhos que os testes de verdade nunca percorrem. O resto continua sendo validado rodando os módulos diretamente — a maioria tem um bloco `if __name__ == "__main__":` com um teste de fumaça usando dado real do banco — e testando o fluxo completo pelo painel web ou por e-mail real.

```bash
# Ambiente (sempre usar o venv, nunca o Python global)
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Suíte de testes
.venv\Scripts\python.exe -m pytest tests/ -v

# Painel administrativo (localhost:5000) -- ferramenta principal de dev e uso diário
.venv\Scripts\python.exe -m webapp.app

# Definir/redefinir a senha de um usuário do painel (interativo, nunca digitar a senha em outro lugar)
.venv\Scripts\python.exe -m webapp.definir_senha

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

# Rodar um módulo isolado do Motor IA (a maioria aceita ser chamada assim para smoke test)
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

# Conferir se a tabela documento bate com os arquivos em disco (só relata, nunca apaga)
.venv\Scripts\python.exe -m core.db.auditar_documentos
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

### webapp/ é o painel administrativo real, não uma ferramenta descartável

Flask + Jinja + JS puro (sem build step, sem framework front-end) servido via CDN para o tema AdminLTE 3. Autenticação por sessão simples (`werkzeug.security`, `usuario.senha_hash`) — sem biblioteca de auth adicional. Todas as rotas `/api/*` exigem login (`@login_required`); a senha de um usuário nunca é definida por código, só via `webapp/definir_senha.py` rodado interativamente pelo próprio usuário. A UI inteira é uma SPA de uma página só (`webapp/templates/index.html`) alternando divs `.view` via JS — não há rotas de URL por tela.

### portal/ é um app Flask separado, nunca reaproveita a sessão do painel

Ver `docs/portal_cliente_arquitetura.md` para o rascunho completo. Autoatendimento pro cliente real (não staff), rodando em porta própria (5002) com `secret_key` e nome de cookie (`SESSION_COOKIE_NAME = "portal_session"`) totalmente separados de `webapp/` — os dois podem rodar ao mesmo tempo no mesmo navegador sem misturar sessão. Login sem senha: link mágico de token único por e-mail (`core/motor_portal_auth.py`), nunca reaproveita `usuario.senha_hash`. MVP é só leitura (status do caso + checklist de documentos) + upload — sem chat com a IA pelo Portal ainda. Toda rota que recebe `caso_id`/`documento_id` do cliente **sempre** confere se o dono bate com `session["cliente_id"]` antes de ler ou escrever qualquer coisa — esse é o único ponto realmente crítico de segurança do Portal (primeira superfície pública do sistema, domínio regulado de arma de fogo): um bug aqui vaza documento de um cliente para outro.

### Checklist de documento: quem liga o arquivo ao item define o estado

`documento_checklist` liga um arquivo recebido a um item de `documento_exigido`. Quem cria essa ligação determina em que estado ela nasce, e essa é a regra inteira: marcação feita no painel nasce `Aprovado` (o funcionário abriu o arquivo pra decidir — a conferência aconteceu no mesmo gesto), envio pelo Portal nasce `Aguardando aprovação` (é uma afirmação do cliente, ninguém conferiu). `Recusado` guarda o `motivo_recusa`, que é mostrado ao cliente, e para efeito de checklist conta como faltando. **Pendente não conta na contagem X/Y nem no anel de progresso** — contar infla o progresso com trabalho que ninguém fez. A decisão continua sendo sempre humana: a IA nunca decide que um PDF é a certidão X.

O envio pelo Portal manda `processo_id` e `documento_exigido_id` vindos do navegador do cliente — `portal/app.py::upload_documento` confere que o processo pertence ao caso que já se sabe ser dele. O filtro de empresa **não** cobre isso: dois clientes da mesma empresa são o caso perigoso. Ver `tests/test_aprovacao_documentos.py`.

### Integrações externas simuladas até haver credencial

`integracoes/shooting_house.py` (CR e habitualidade do atirador) devolve dado simulado determinístico por CPF enquanto `SHOOTING_HOUSE_USER`/`PASSWORD` não estão configurados em `.env` — isso permite testar o pipeline inteiro sem depender do suporte do fornecedor liberar acesso. Mesmo padrão vale para qualquer integração externa nova: sempre ter um modo simulado que não bloqueia o desenvolvimento.
