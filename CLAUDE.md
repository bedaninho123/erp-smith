# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

ERP Smith: um ERP inteligente de atendimento e gestão de processos, desenhado para ser multi-domínio (não específico de um segmento). O piloto em produção é para um **despachante especializado em Clube de Tiro** (documentação de CR/CRAF, transferência de arma, habitualidade). O documento de arquitetura original — visão de produto, princípios, fases de migração planejadas — está em `../PROJETO_1.md` (um nível acima da raiz do repo). Leia-o antes de qualquer mudança estrutural.

## Comandos

Não existe suíte de testes automatizada (nenhum `pytest`/`unittest`). A validação é feita rodando os módulos diretamente — a maioria tem um bloco `if __name__ == "__main__":` com um teste de fumaça usando dado real do banco — e testando o fluxo completo pelo painel web ou por e-mail real.

```bash
# Ambiente (sempre usar o venv, nunca o Python global)
.venv\Scripts\python.exe -m pip install -r requirements.txt

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

# Recriar/migrar os bancos SQLite a partir do schema + dados de teste
.venv\Scripts\python.exe -m core.db.migrate_dados_teste
.venv\Scripts\python.exe -m core.db.gerar_clientes_ficticios
.venv\Scripts\python.exe -m domain.clube_tiro.db.popular_conhecimento

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

### Integrações externas simuladas até haver credencial

`integracoes/shooting_house.py` (CR e habitualidade do atirador) devolve dado simulado determinístico por CPF enquanto `SHOOTING_HOUSE_USER`/`PASSWORD` não estão configurados em `.env` — isso permite testar o pipeline inteiro sem depender do suporte do fornecedor liberar acesso. Mesmo padrão vale para qualquer integração externa nova: sempre ter um modo simulado que não bloqueia o desenvolvimento.
