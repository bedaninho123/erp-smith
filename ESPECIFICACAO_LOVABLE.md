# ERP Smith — Especificação completa para reconstrução no Lovable

> **O que é este arquivo.** A descrição inteira de um ERP que hoje roda em
> Python/Flask + SQLite, escrita para que o Lovable (React + Supabase) possa
> reconstruí-lo do zero. Não é documentação do código antigo: é a receita do
> sistema novo — tabelas, políticas de acesso, telas, campos e as regras que
> não podem se perder na tradução.

---

## COMO USAR ESTE ARQUIVO NO LOVABLE

Não cole tudo de uma vez. O Lovable trabalha muito melhor com escopo pequeno, e
um prompt gigante faz ele "esquecer" o meio. A ordem que funciona:

1. **Primeiro prompt:** cole as seções `1` (Contexto), `2` (Stack) e `3`
   (Identidade visual). Peça só: *"Crie o projeto base com esse visual, sem
   telas ainda — só layout, sidebar, tipografia e cores."*
2. **Segundo prompt:** cole a seção `4` (Modelo de dados) inteira. Peça:
   *"Crie estas tabelas no Supabase com estas policies de RLS."*
3. **Terceiro prompt:** cole a seção `5` (Listas controladas) + `6` (Papéis e
   permissões). Peça o login e o controle de acesso.
4. **Daí em diante, uma tela por prompt**, colando só o bloco daquela tela na
   seção `8` ou `9`. Nunca duas telas no mesmo prompt.

A seção `7` (Regras de negócio) é a mais importante do arquivo. Cole os
parágrafos dela junto do prompt da tela correspondente — cada regra ali existe
porque a ausência dela já causou um erro real.

---

## 1. CONTEXTO — o que este sistema é

**ERP Smith** é um ERP de atendimento e gestão de processos, multi-empresa
(multi-tenant), desenhado para ser multi-domínio. O piloto em produção atende um
**despachante especializado em Clube de Tiro**: documentação de CR/CRAF,
transferência de arma, guia de tráfego, habitualidade de atirador.

**Quem usa, e são três públicos diferentes:**

| Público | Onde entra | O que faz |
|---|---|---|
| **Gestor** | Painel administrativo | Tudo, incluindo configuração, usuários, auditoria e dashboard |
| **Atendente** | Painel administrativo | Opera casos, clientes, tarefas e documentos. Sem área administrativa |
| **Cliente final** | Portal do Cliente (app separado) | Acompanha os próprios casos, envia documento, vê o dossiê dele |

**A entidade central é o CASO, não o Cliente.** A cadeia é:

```
Cliente → Caso → Processo → Documento
                     ↘ Tarefa (trabalho com dono e prazo)
```

Um cliente cadastrado **não** implica que ele seja atirador do clube — alguém
pode usar só o serviço de transferência de arma sem nunca ter treinado.

**Duas populações de pessoas, e juntá-las seria um erro grave:**

- `cliente` — quem o **despachante** atende (~dezenas). Cadastro nosso.
- `filiado` — quem passou pelo **clube** (~1450). Espelho de um sistema externo
  (Shooting House), sincronizado, somente leitura.

Ligação entre as duas é pelo **CPF**, nunca por chave estrangeira. Importar
todos os filiados para `cliente` seria guardar dado pessoal de gente que ninguém
atende.

---

## 2. STACK ALVO E O QUE FICA DE FORA

**Construir no Lovable:**

- React + TypeScript + Vite
- Tailwind CSS + shadcn/ui
- Supabase (Postgres + Auth + Storage + RLS)
- Recharts para os gráficos do Dashboard
- Dois apps ou duas áreas de rota: `/app/*` (Painel, staff) e `/portal/*`
  (Cliente). Ver seção 6 sobre por que as sessões precisam ser distintas.

**NÃO tentar reconstruir no Lovable — isto continua sendo um serviço Python
separado, que o front consome via API:**

| Peça | Por quê |
|---|---|
| **Motor IA** (Classificador → Planejador → Consultor → Redator → Auditor) | Pipeline de 6 etapas com prompts versionados, freios determinísticos e auditoria factual. Não é algo que se descreve num prompt de Lovable |
| **Integração Shooting House** | API externa do clube, credencial Basic Auth, somente leitura por obrigação contratual e regulatória |
| **Poller de e-mail (Gmail OAuth)** | Roda como tarefa agendada no servidor, a cada 2 min |
| **Envio de WhatsApp (Meta Cloud API)** | Exige HTTPS público e janela de 24h |
| **Sincronização de filiados / habitualidade** | Rodízio paginado, ~18 min por volta completa |

> **Consequência prática:** o Lovable entrega **o painel, o portal e o banco**.
> As telas que dependem do Motor IA ("Aprovações Pendentes", "Testar Pipeline")
> e as do clube ("Filiados", "Modalidades") devem ser construídas lendo tabelas
> do Supabase que o serviço Python vai **escrever**. Construa a tela contra a
> tabela, não contra a API externa.

---

## 3. IDENTIDADE VISUAL — a régua, que é regra e não sugestão

O sistema já tem um sistema de design fechado, e ele existe porque um dia
houve 16 botões com 3 alturas diferentes na mesma tela. Traduza para tokens do
Tailwind e **não invente valores fora desta lista**.

### Tipografia — cinco papéis, nada além disso

| Papel | Fonte | Tamanho / peso |
|---|---|---|
| Título de tela | `Big Shoulders` 700, MAIÚSCULA, `letter-spacing: .02em` | 30px |
| Texto corrente, corpo | `IBM Plex Sans` | 14px / line-height 1.5 |
| Título de card | `IBM Plex Sans` 600 | 15px |
| Rótulo de campo, cabeçalho de tabela | `IBM Plex Sans` 600, MAIÚSCULA, `letter-spacing: .07em` | 11px |
| Identificador, CPF, data, número | `IBM Plex Mono` | 13px |

Todas do Google Fonts. **Regra que não pode cair:** identificador
(`CAS-000001`), CPF e data vão **sempre** em monoespaçada — é o que faz uma
coluna de IDs ficar legível de relance.

### Cores

```css
--paper:        #EEF1F5;  /* fundo da página */
--paper-raised: #FFFFFF;  /* card */
--line:         #DFE3EA;  /* borda, divisória */
--ink:          #232428;  /* texto */
--ink-deep:     #131417;  /* título */
--steel:        #626873;  /* texto de apoio, rótulo */
--blue:         #396BB3;  /* ação primária */
--blue-deep:    #24487D;  /* link, hover */
--blue-bright:  #6FA0DC;
--blue-soft:    #E4ECF8;  /* fundo de destaque */
--signal:       #B23B2E;  /* erro, vencido, atrasado */
--signal-soft:  #F7E5E2;
--amber:        #7A5709;  /* atenção, vencendo, em conferência */
--amber-soft:   #F6EDDA;
--radius:       8px;
```

O âmbar é escuro de propósito: `#7A5709` sobre `--amber-soft` dá contraste
5.6:1. Um âmbar "bonito" e claro reprovaria em acessibilidade.

### Espaçamento — só estes seis valores

`4px, 8px, 12px, 16px, 24px, 32px`. Nunca um 7 ou um 13 solto.

### Controles — DUAS alturas, e só duas

- **38px** — ação principal e **todo campo de formulário**. Fonte 14px.
- **30px** — botão pequeno, ação dentro de linha de tabela. Fonte 13px.

Nada de 26px, 31px ou 34px. Se um controle não couber nessas duas alturas, ele
está errado, não a régua.

### Três regras de formatação que a tela nunca pode quebrar

1. **Data nunca vai crua para a tela.** O banco guarda ISO/UTC. A tela mostra
   `dd/mm/aaaa` para dia e `dd/mm/aaaa HH:MM` para instante, **sempre no fuso
   local do usuário**. Ver a regra 7.3, que é onde isso já mordeu.
2. **CPF é guardado só com dígitos** e formatado na exibição (`000.000.000-00`).
3. **Bloco de dados usa grade rótulo/valor** (`display: grid`, rótulo pequeno
   maiúsculo em cima ou à esquerda), nunca uma pilha de
   `<p><b>Rótulo:</b> valor</p>`.

### Cor semântica só quando o número pede ação

Zero em vermelho treina o olho a ignorar vermelho — e é justamente o vermelho
que precisa funcionar no dia em que houver 6 tarefas atrasadas. Contador em
zero fica neutro.

---

## 4. MODELO DE DADOS (Supabase / Postgres)

### 4.0 Convenções que valem para o banco inteiro

- **IDs são TEXT no formato `PREFIXO-000000`** (6 dígitos), gerados pelo
  sistema e imutáveis: `CLI-000001`, `CAS-000001`, `MSG-000001`. Não trocar por
  UUID: esses IDs aparecem na tela, em e-mail e em conversa com cliente, e um
  UUID ali é ilegível. A numeração é **global**, não por empresa — ver 7.9.
- **Toda tabela carrega `empresa_id`**, inclusive as que poderiam herdar do pai
  (`historico`, `documento_checklist`). A redundância é proposital: consulta que
  filtra direto, sem JOIN, é consulta com menos chance de esquecer o filtro.
- **Datas são `timestamptz`** (o Postgres já resolve o que o SQLite não
  resolvia). Campos que são um **dia** e não um instante — `prazo` de tarefa,
  `data_inicio` de campeonato, `data_validade` de documento — são `date`.
- **Tri-estado importa.** Onde o sistema antigo usava `'Sim'/'Não'/NULL`, use
  `boolean` **nullable**. `NULL` significa *"não sei / o campo não veio"*, e
  nunca pode ser exibido como se fosse `false`. Ver 7.1 — é a regra mais
  importante do sistema inteiro.

- **As tabelas abaixo estão agrupadas por assunto, não em ordem de criação.**
  Há referências para frente (`documento` aponta para `mensagem`, `perfil` aponta
  para `usuario` e `cliente`). Crie primeiro as tabelas sem dependência e
  acrescente essas chaves estrangeiras depois, com `alter table ... add
  constraint` — ou peça ao Lovable para resolver a ordem, que ele faz bem.

**Gerador de ID** — crie uma sequence por entidade e uma função:

```sql
create sequence seq_cliente;  create sequence seq_caso;
create sequence seq_processo; create sequence seq_documento;
create sequence seq_mensagem; create sequence seq_tarefa;
create sequence seq_conversa; create sequence seq_historico;
create sequence seq_usuario;  create sequence seq_servico;
-- ...uma por entidade

create or replace function novo_id(prefixo text, seq text)
returns text language plpgsql as $func$
begin
  return prefixo || '-' || lpad(nextval(seq)::text, 6, '0');
end $func$;

-- uso na tabela:  default novo_id('CAS', 'seq_caso')
```

### 4.1 Autenticação e tenant — a fundação de tudo

O sistema antigo tinha dois apps Flask com sessões separadas. No Supabase, os
dois públicos vivem no mesmo `auth.users`, e uma tabela `perfil` diz quem é
quem. **Sem isto, nenhuma policy abaixo funciona.**

```sql
create table empresa (
  empresa_id  text primary key,               -- EMP-000001
  nome        text not null,
  dominio     text not null,                  -- 'clube_tiro'
  ativo       boolean not null default true,  -- empresa suspensa vira false, nunca é apagada
  criado_em   timestamptz not null default now()
);

-- Liga o usuário do Supabase Auth a uma empresa E a um dos dois públicos.
create table perfil (
  id          uuid primary key references auth.users(id) on delete cascade,
  empresa_id  text not null references empresa(empresa_id),
  tipo        text not null check (tipo in ('staff', 'cliente')),
  usuario_id  text references usuario(usuario_id),   -- quando tipo='staff'
  cliente_id  text references cliente(cliente_id),   -- quando tipo='cliente'
  check (
    (tipo = 'staff'   and usuario_id is not null and cliente_id is null) or
    (tipo = 'cliente' and cliente_id is not null and usuario_id is null)
  )
);

-- As três funções que TODA policy vai usar.
create or replace function empresa_atual() returns text
language sql stable security definer set search_path = public as $f$
  select empresa_id from perfil where id = auth.uid()
$f$;

create or replace function eh_staff() returns boolean
language sql stable security definer set search_path = public as $f$
  select coalesce((select tipo = 'staff' from perfil where id = auth.uid()), false)
$f$;

create or replace function cliente_atual() returns text
language sql stable security definer set search_path = public as $f$
  select cliente_id from perfil where id = auth.uid()
$f$;
```

> **Por que `empresa_atual()` e não um `empresa_id` vindo do front:** a empresa
> **nunca** pode vir da requisição. No sistema antigo ela vinha da sessão do
> servidor; aqui vem do JWT, resolvido dentro do banco. Um front comprometido
> não consegue pedir dado de outra empresa nem por engano nem de propósito.

**Padrão de policy — repita para TODAS as tabelas:**

```sql
alter table caso enable row level security;

create policy caso_staff on caso for all to authenticated
  using      (empresa_id = empresa_atual() and eh_staff())
  with check (empresa_id = empresa_atual() and eh_staff());

-- Quando a tabela também é lida pelo Portal, uma SEGUNDA policy, só de leitura:
create policy caso_cliente on caso for select to authenticated
  using (empresa_id = empresa_atual() and cliente_id = cliente_atual());
```

### 4.2 Núcleo do atendimento

```sql
create table cliente (
  cliente_id       text primary key default novo_id('CLI','seq_cliente'),
  empresa_id       text not null references empresa(empresa_id),
  nome             text not null,
  cpf              text not null,                 -- SÓ DÍGITOS, sem pontuação
  email            text,
  telefone         text,
  cidade           text,
  status           text not null default 'Ativo', -- 'Ativo' | 'Inativo'
  atendimento_ia   boolean not null default true, -- false = a IA nunca responde por ele
  data_cadastro    timestamptz not null default now(),
  ultima_interacao timestamptz,
  observacoes      text,
  unique (empresa_id, cpf)   -- o MESMO CPF pode ser cliente de dois despachantes
);

create table usuario (
  usuario_id  text primary key default novo_id('USR','seq_usuario'),
  empresa_id  text not null references empresa(empresa_id),
  nome        text not null,
  email       text not null,
  papel       text not null,                  -- 'Gestor' | 'Atendente' — seção 6
  equipe      text,
  ativo       boolean not null default true,
  criado_em   timestamptz not null default now(),
  unique (empresa_id, email)
);

create table servico (
  service_id              text primary key default novo_id('SER','seq_servico'),
  empresa_id              text not null references empresa(empresa_id),
  service_key             text not null,        -- 'transferencia_arma'
  nome_servico            text not null,
  descricao               text,
  categoria               text not null,
  prazo_estimado_dias     integer,              -- NULL = "a confirmar". NUNCA 0
  valor_referencia        numeric(12,2),        -- NULL = "a confirmar". NUNCA 0
  documentos_obrigatorios text not null,        -- resumo curto, em texto corrido
  ativo                   boolean not null default true,
  observacoes             text,
  unique (empresa_id, service_key)
);

create table caso (
  caso_id             text primary key default novo_id('CAS','seq_caso'),
  empresa_id          text not null references empresa(empresa_id),
  cliente_id          text not null references cliente(cliente_id),
  titulo              text not null,
  descricao           text,
  categoria           text not null,   -- sai do catálogo de servico, não de lista fixa
  tipo_caso           text not null,
  origem              text not null,   -- 'Motor IA' | 'Painel' | 'Migração'
  canal_origem        text not null,   -- ver CANAIS_ORIGEM, seção 5
  status              text not null,   -- ver STATUS_CASO, seção 5
  fase                text,
  prioridade          text not null default 'Normal',
  responsavel_id      text references usuario(usuario_id),
  equipe_responsavel  text,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now(),
  prazo_previsto      date,
  encerrado_em        timestamptz,     -- carimba ao encerrar, APAGA ao reabrir (7.4)
  criado_por          text not null,
  alterado_por        text not null,
  versao              integer not null default 1,
  ativo               boolean not null default true,
  motivo_encerramento text,
  observacoes         text
);

create table processo (
  processo_id        text primary key default novo_id('PRO','seq_processo'),
  empresa_id         text not null references empresa(empresa_id),
  caso_id            text not null references caso(caso_id),
  cliente_id         text not null references cliente(cliente_id),
  servico_id         text not null references servico(service_id),
  protocolo          text,
  status             text not null,
  data_abertura      date not null default current_date,
  prazo_estimado     date,
  proxima_acao       text,      -- ESTADO perante o órgão. NÃO é uma tarefa (7.5)
  responsavel_id     text references usuario(usuario_id),
  ultima_atualizacao timestamptz not null default now(),
  observacoes        text
);

create table historico (
  historico_id   text primary key default novo_id('HIS','seq_historico'),
  empresa_id     text not null references empresa(empresa_id),
  caso_id        text not null references caso(caso_id),
  tipo_evento    text not null check (tipo_evento in
                   ('criacao','mudanca_status','troca_responsavel','encerramento','outro')),
  descricao      text,
  valor_anterior text,
  valor_novo     text,
  criado_em      timestamptz not null default now(),
  criado_por     text not null
);
```

### 4.3 Documentos, checklist e dossiê

```sql
-- O CHECKLIST de um serviço: FRASES DE EXIGÊNCIA, não nomes de arquivo.
-- Ex.: "Comprovante de residência fixa atual e dos últimos 5 anos."
create table documento_exigido (
  documento_exigido_id text primary key default novo_id('DEX','seq_documento_exigido'),
  empresa_id           text not null references empresa(empresa_id),
  servico_id           text not null references servico(service_id),
  grupo                text,          -- 'Pessoais', 'Certidões', 'Laudos'...
  item                 text not null,
  ordem                integer not null,
  ativo                boolean not null default true
);

create table documento (
  documento_id    text primary key default novo_id('DOC','seq_documento'),
  empresa_id      text not null references empresa(empresa_id),
  cliente_id      text not null references cliente(cliente_id),
  caso_id         text references caso(caso_id),
  processo_id     text references processo(processo_id),
  categoria       text not null default 'Caso' check (categoria in ('Caso','Dossiê')),
  tipo_documento  text not null,     -- TEXTO LIVRE. O catálogo é sugestão (7.7)
  nome_arquivo    text,
  storage_path    text,              -- caminho no Supabase Storage (bucket privado)
  status          text not null,
  data_envio      timestamptz,
  data_validade   date,              -- NULL = sem data cadastrada, NÃO "válido" (7.1)
  revisado_por_id text references usuario(usuario_id),
  observacoes     text,              -- guarda a REFERÊNCIA: "CRAF da pistola X" (7.7)
  mensagem_id     text references mensagem(mensagem_id),
  -- A trava que separa documento de um caso de documento permanente da pessoa:
  check (
    (categoria = 'Caso'   and (caso_id is not null or processo_id is not null)) or
    (categoria = 'Dossiê' and caso_id is null and processo_id is null)
  )
);

-- Liga um arquivo recebido a um item do checklist de um processo.
create table documento_checklist (
  documento_checklist_id text primary key default novo_id('DCK','seq_documento_checklist'),
  empresa_id             text not null references empresa(empresa_id),
  processo_id            text not null references processo(processo_id),
  documento_exigido_id   text not null references documento_exigido(documento_exigido_id),
  documento_id           text not null references documento(documento_id),
  marcado_em             timestamptz not null default now(),
  marcado_por            text not null,
  status                 text not null default 'Aprovado'
    check (status in ('Aguardando aprovação','Aprovado','Recusado')),
  revisado_em            timestamptz,
  revisado_por           text,
  motivo_recusa          text,   -- só quando 'Recusado'. É MOSTRADO ao cliente
  unique (processo_id, documento_exigido_id, documento_id)
);
```

### 4.4 Tarefas e prazos

```sql
create table tarefas (
  tarefa_id      text primary key default novo_id('TAR','seq_tarefa'),
  empresa_id     text not null references empresa(empresa_id),
  caso_id        text not null references caso(caso_id),       -- toda tarefa tem caso
  cliente_id     text not null references cliente(cliente_id), -- lido do CASO, nunca do form
  processo_id    text references processo(processo_id),
  tipo           text not null,      -- texto livre, com sugestões (seção 5)
  descricao      text,
  responsavel_id text references usuario(usuario_id),
  prazo          date,               -- É UM DIA, não um instante (7.3)
  prioridade     text not null default 'Normal',
  status         text not null default 'Pendente',
  data_conclusao timestamptz,        -- consequência do status, nunca digitada (7.6)
  observacoes    text
);
```

### 4.5 Atendimento: conversa e mensagem (CRM)

```sql
create table conversa (
  conversa_id        text primary key default novo_id('CON','seq_conversa'),
  empresa_id         text not null references empresa(empresa_id),
  cliente_id         text not null references cliente(cliente_id),
  caso_id            text references caso(caso_id),
  canal              text not null,  -- 'Email' | 'WhatsApp' — CHAVE, nunca rótulo (7.8)
  origem             text not null,
  status             text not null,  -- 'Aberta' | 'Aguardando cliente' | 'Encerrada'
  assunto_principal  text,
  iniciada_em        timestamptz not null default now(),
  ultima_mensagem_em timestamptz not null default now(),
  encerrada_em       timestamptz,
  responsavel_id     text references usuario(usuario_id),
  precisa_humano     boolean,
  total_mensagens    integer not null default 0,
  criado_por         text not null,
  atualizado_por     text not null,
  ativo              boolean not null default true,
  observacoes        text
);

create table mensagem (
  mensagem_id            text primary key default novo_id('MSG','seq_mensagem'),
  empresa_id             text not null references empresa(empresa_id),
  cliente_id             text not null references cliente(cliente_id),
  caso_id                text references caso(caso_id),
  conversa_id            text references conversa(conversa_id),
  processo_id            text references processo(processo_id),
  canal                  text not null,
  data_hora              timestamptz not null default now(),
  origem                 text not null,   -- 'Cliente' | 'Motor IA' | 'Atendente'
  email_remetente        text,
  assunto                text,
  mensagem               text,   -- o que o CLIENTE escreveu
  resposta_ia            text,   -- o que saiu como RESPOSTA
  intent                 text,
  resumo_ia              text,
  precisa_humano         boolean,
  status_processamento   text not null,
  id_externo             text,
  responsavel_id         text references usuario(usuario_id),
  tempo_processamento_ms integer,
  modelo_ia              text,
  observacoes_ia         text
);
```

> **Uma linha de `mensagem` vira ATÉ DUAS BOLHAS na tela**: a do cliente
> (`mensagem`) e a da resposta (`resposta_ia`). É assim que a tabela guarda
> desde sempre — um par por linha. Resposta escrita à mão pelo atendente entra
> como `origem='Atendente'` com `mensagem` vazia. **Não crie uma tabela nova
> para isso.**

### 4.6 Configuração, permissão, auditoria e IA

```sql
create table configuracoes (
  config_id  text primary key default novo_id('CFG','seq_config'),
  empresa_id text not null references empresa(empresa_id),
  chave      text not null,
  valor      text not null,   -- SEMPRE texto, mesmo número e booleano
  categoria  text not null,   -- 'empresa'|'contato'|'atendimento'|'mensagens'|'ia'|'sistema'|'portal'
  descricao  text,
  ativo      boolean not null default true,
  unique (empresa_id, chave)
);

create table usuario_permissao (
  usuario_id text not null references usuario(usuario_id),
  empresa_id text not null references empresa(empresa_id),
  funcao     text not null,
  ativo      boolean not null default true,
  primary key (usuario_id, funcao)
);

-- APPEND-ONLY. Não existe UPDATE, não existe DELETE, e nenhuma tela escreve aqui.
create table log_administrativo (
  log_administrativo_id text primary key default novo_id('ADM','seq_log_adm'),
  empresa_id            text not null references empresa(empresa_id),
  tipo_evento           text not null,  -- 'MUDANCA_PAPEL' | 'MUDANCA_PERMISSAO'
                                        -- | 'MUDANCA_CONFIGURACAO' | 'ACESSO_DADO_SENSIVEL'
  alvo                  text not null,  -- ID de usuário, de cliente, ou chave de config
  descricao             text,
  valor_anterior        text,
  valor_novo            text,
  criado_em             timestamptz not null default now(),
  criado_por            text not null
);

create table log_ia (
  log_id                 text primary key default novo_id('LOG','seq_log_ia'),
  empresa_id             text not null references empresa(empresa_id),
  caso_id                text references caso(caso_id),
  prompt_key             text not null,
  modelo                 text not null,
  tokens_entrada         integer,
  tokens_saida           integer,
  tempo_processamento_ms integer,
  resultado              text not null check (resultado in ('Sucesso','Erro')),
  erro                   text,
  criado_em              timestamptz not null default now()
);

-- Texto institucional com placeholders: {prazo_estimado_dias}, {valor_referencia}.
create table template (
  template_id  text primary key default novo_id('TPL','seq_template'),
  empresa_id   text not null references empresa(empresa_id),
  template_key text not null,
  nome         text not null,
  categoria    text,
  conteudo     text not null,
  canal        text,
  ativo        boolean not null default true,
  unique (empresa_id, template_key)
);
```

`sessao` (contexto curto do Motor IA) e `memoria_ia` (memória longa do cliente)
são escritas só pelo serviço Python. Crie as tabelas espelhando o que ele usa,
mas **não construa tela para elas** — não existe nenhuma hoje, e criar uma seria
expor rascunho de IA como se fosse registro.

### 4.7 Domínio Clube de Tiro — separado de propósito

No sistema antigo isto é um **arquivo de banco separado**, para garantir que o
Core nunca tenha referência ao domínio (é o que sustenta a tese de produto
multi-domínio: amanhã plugar "advocacia" sem tocar no Core). No Supabase, use um
**schema `dominio`** com o mesmo efeito. **Nenhuma tabela do Core pode
referenciar estas.**

```sql
create schema dominio;

-- CONHECIMENTO É COMPARTILHADO: sem empresa_id. É legislação federal, a mesma
-- para todo despachante. Duplicar por empresa = N cópias que divergem com o tempo.
create table dominio.conhecimento (
  conhecimento_id text primary key default novo_id('KNW','seq_conhecimento'),
  categoria       text not null,  -- CR, CRAF, Transferência, Habitualidade, Legislação...
  pergunta        text not null,
  resposta        text not null,
  aprovado        boolean not null default false,
  ativo           boolean not null default true,
  criado_em       timestamptz not null default now()
);

-- CAMPEONATO É DA EMPRESA: com empresa_id.
create table dominio.campeonato (
  campeonato_id text primary key default novo_id('CAM','seq_campeonato'),
  empresa_id    text not null references empresa(empresa_id),
  nome          text not null,
  data_inicio   date not null,
  data_fim      date not null,   -- igual a data_inicio quando é um dia só
  local         text,
  observacoes   text,
  origem        text not null default 'manual',
  ativo         boolean not null default true,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table dominio.resultado_campeonato (
  resultado_id  text primary key default novo_id('RES','seq_resultado'),
  empresa_id    text not null references empresa(empresa_id),
  campeonato_id text not null references dominio.campeonato(campeonato_id),
  cliente_id    text references cliente(cliente_id),  -- NULLABLE, e isso importa (7.12)
  nome_atirador text not null,
  modalidade    text,       -- TEXTO, não FK. O catálogo é sugestão (7.10)
  colocacao     integer,
  pontuacao     text,       -- texto livre: o formato varia por modalidade
  observacoes   text,
  origem        text not null default 'manual',
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table dominio.modalidade (
  modalidade_id    text primary key default novo_id('MOD','seq_modalidade'),
  empresa_id       text not null references empresa(empresa_id),
  grupo_id_sh      integer,
  grupo            text not null,  -- 'Sem grupo' quando o nome vem vazio da API
  modalidade_id_sh integer not null,
  nome             text not null,
  ativo            boolean not null default true,  -- saiu do catálogo => false, NUNCA delete
  sincronizado_em  timestamptz not null default now(),
  unique (empresa_id, grupo_id_sh, modalidade_id_sh)
);

-- ESPELHO somente leitura do sistema do clube. Escrito só pelo serviço Python.
create table dominio.filiado (
  filiado_id          text primary key default novo_id('FIL','seq_filiado'),
  empresa_id          text not null references empresa(empresa_id),
  idatirador          integer,
  matricula           text,
  nome                text not null,
  cpf                 text not null,   -- chave de ligação com cliente
  email               text,
  status_filiacao     text,            -- 'Ativo' | 'Inativo'
  data_filiacao       date,
  tipo_filiado        text,

  -- RETRATO de habitualidade, não a verdade sobre ela.
  -- NULL = nunca sincronizado. [] = consultado e não teve. Os dois são diferentes.
  participacoes_12m   integer,
  ultima_participacao date,
  participacoes_datas jsonb,           -- ["2026-08-22", ...]
  sincronizado_em     timestamptz,     -- TODA TELA que mostrar os números acima
                                       -- é OBRIGADA a mostrar este campo junto
  sincronizacao_erro  text,

  -- Situação financeira: boolean NULLABLE, e o NULL é "o campo não veio",
  -- nunca "está devendo".
  anuidade_em_dia     boolean,
  anuidade_validade   date,
  financeiro_em_dia   boolean,
  cr_numero           text,
  cr_validade         date,
  cr_em_dia           boolean,
  tem_pedido_aberto   boolean,

  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now(),
  unique (empresa_id, cpf)
);
create index on dominio.filiado (empresa_id, cpf);
create index on dominio.filiado (empresa_id, sincronizado_em);
```

**RLS no schema `dominio`:** `conhecimento` é leitura para qualquer autenticado
(não tem `empresa_id`). As outras quatro seguem o mesmo padrão de
`empresa_atual()`. `filiado` e `modalidade` são **somente leitura pelo front** —
quem escreve é o serviço Python, com a chave `service_role`.

### 4.8 Storage

Um bucket **privado** chamado `documentos`. Caminho do arquivo:

```
{empresa_id}/{cliente_id}/{documento_id}-{nome_arquivo}
```

As policies de Storage espelham as da tabela `documento`: staff da empresa lê
tudo da empresa; cliente lê **apenas** os arquivos cujo `documento.cliente_id`
seja igual a `cliente_atual()`. **Nunca** use bucket público nem URL permanente
— sempre signed URL de curta duração. Ver 7.11, que é onde isso vira segurança
de verdade e não preferência.

---

## 5. LISTAS CONTROLADAS

Estas listas vivem **no código do front e da API**, não como `CHECK` no banco
(exceto onde indicado). O motivo: acrescentar um valor não pode exigir
migração de banco. Mas o valor gravado é sempre o da lista — campo de texto
livre onde deveria haver lista cria uma fatia nova em todo gráfico a cada
digitação diferente.

```ts
// Status do Caso — 8 valores
export const STATUS_CASO = [
  'Aberto', 'Em triagem', 'Em andamento', 'Aguardando cliente',
  'Aguardando terceiro', 'Suspenso', 'Encerrado', 'Cancelado',
] as const;

// Prioridade — MESMA lista para Caso e para Tarefa, de propósito: as duas
// aparecem lado a lado na mesma tela, e duas escalas ("Média" num lugar,
// "Normal" no outro) fariam a pessoa traduzir de cabeça.
export const PRIORIDADES = ['Baixa', 'Normal', 'Alta', 'Urgente'] as const;

// Por onde o caso chegou. Inclui Telefone e Presencial, que a IA nunca vai
// usar — e que são justamente os mais comuns no caso aberto à mão.
export const CANAIS_ORIGEM = ['Email', 'WhatsApp', 'Telefone', 'Presencial', 'Portal'] as const;

// Status da Tarefa
export const STATUS_TAREFA = ['Pendente', 'Em andamento', 'Concluída', 'Cancelada'] as const;
// O que ainda pede trabalho de alguém. É esta lista que decide o que entra na
// fila e no que o painel conta como "em aberto" — tarefa cancelada não é
// pendência, é decisão registrada.
export const STATUS_TAREFA_ABERTOS = ['Pendente', 'Em andamento'] as const;

// Tipo de tarefa é TEXTO LIVRE, com estas sugestões numa datalist. Lista
// fechada aqui viraria dívida na primeira semana: o próximo domínio não tem
// os mesmos tipos de tarefa.
export const TIPOS_TAREFA_SUGERIDOS = [
  'Cobrar documento', 'Consultar andamento', 'Ligar para o cliente',
  'Protocolar', 'Conferir documento', 'Agendar',
] as const;

// Canal de conversa (CRM). O valor gravado é a CHAVE, nunca o rótulo de tela.
export const CANAIS_CONVERSA = ['Email', 'WhatsApp'] as const;
export const ROTULO_CANAL = { Email: 'E-mail', WhatsApp: 'WhatsApp' };

export const STATUS_CONVERSA = ['Aberta', 'Aguardando cliente', 'Encerrada'] as const;

export const STATUS_CHECKLIST = ['Aguardando aprovação', 'Aprovado', 'Recusado'] as const;

export const PAPEIS = ['Gestor', 'Atendente'] as const;
export const STATUS_CLIENTE = ['Ativo', 'Inativo'] as const;
export const CATEGORIA_DOCUMENTO = ['Caso', 'Dossiê'] as const;
```

**A `categoria` do Caso NÃO é uma lista fixa:** ela sai do catálogo de
`servico` da empresa. É o mesmo vocabulário do checklist e dos processos, e uma
lista à parte divergiria na primeira vez que alguém cadastrasse um serviço novo.

### 5.1 Catálogo de tipos de documento do dossiê (Domínio, sugestão de tela)

19 tipos em 5 grupos. `documento.tipo_documento` continua **texto livre** — isto
é uma `datalist`, não uma trava. `validade_meses` pré-preenche a data na tela; a
data que vale é a impressa no documento, digitada por quem está olhando para ele.

| Grupo | Item | Validade sugerida | Pede referência? |
|---|---|---|---|
| Registro e armas | CR — Certificado de Registro | 36 meses | não |
| Registro e armas | CRAF — Certificado de Registro de Arma de Fogo | — | **sim** |
| Registro e armas | Guia de Tráfego | — | **sim** |
| Registro e armas | Autorização de compra | — | **sim** |
| Registro e armas | Nota fiscal da arma | — | **sim** |
| Pessoais | Documento de identidade (RG ou CNH) | — | não |
| Pessoais | CPF | — | não |
| Pessoais | Comprovante de residência | 3 meses | não |
| Pessoais | Foto 3x4 | — | não |
| Laudos | Laudo de aptidão psicológica | 12 meses | não |
| Laudos | Laudo de capacidade técnica | 12 meses | não |
| Certidões | Certidão negativa — Justiça Federal | 3 meses | não |
| Certidões | Certidão negativa — Justiça Estadual | 3 meses | não |
| Certidões | Certidão negativa — Justiça Militar | 3 meses | não |
| Certidões | Certidão negativa — Justiça Eleitoral | 3 meses | não |
| Declarações e comprovantes | Comprovante de ocupação lícita | — | não |
| Declarações e comprovantes | Declaração de Segurança do Acervo (DSA) | — | não |
| Declarações e comprovantes | Comprovante de filiação a clube de tiro | 12 meses | não |
| Declarações e comprovantes | Comprovante de pagamento de taxa (GRU) | — | **sim** |

As **quatro certidões estão separadas de propósito**: são quatro emissões, em
quatro sites diferentes, que vencem em datas diferentes. Guardar como "certidões
negativas" num item só esconderia qual está velha.

**Alerta de validade: 30 dias.** Documento a menos de 30 dias do vencimento
entra como "vencendo" (âmbar). Um mês é o que dá tempo de tirar certidão nova
sem correria.

### 5.2 Chaves de configuração (tabela `configuracoes`)

A tela de Configurações é uma lista de pares chave/valor editáveis, agrupada por
`categoria`. As chaves que existem hoje:

| Categoria | Chaves |
|---|---|
| `empresa` | `nome_empresa`, `cidade`, `estado` |
| `contato` | `telefone`, `whatsapp`, `email_atendimento`, `site` |
| `atendimento` | `horario_semana`, `horario_sabado`, `horario_domingo`, `prazo_resposta_humano`, **`revisao_humana_ativa`** |
| `mensagens` | `saudacao_padrao`, `mensagem_fora_horario`, `mensagem_encaminhamento_humano`, `assinatura_email`, `aviso_valor`, `aviso_prazo`, `mensagem_cliente_nao_encontrado` |
| `ia` | `nome_assistente`, `modelo_openai`, `temperatura_ia`, `max_tokens`, `idioma_resposta`, `permitir_valores_referencia`, `permitir_prazos_referencia` |
| `sistema` | `moeda`, `idioma` |
| `portal` | `notificar_cliente_mudanca_status` |

Duas dessas chaves são **freios de segurança**, e mudar qualquer uma delas
**obriga** a gravar uma linha em `log_administrativo`:

- **`revisao_humana_ativa`** — enquanto `Sim`, toda resposta que a IA escreveu
  fica pendente de aprovação humana em vez de sair sozinha. É o freio da fase
  de validação, num domínio com risco regulatório (documentação de arma de
  fogo). Antes de o log existir, *"quem desligou a revisão humana?"* não tinha
  resposta nenhuma.
- **`notificar_cliente_mudanca_status`** — quando `Sim`, o cliente recebe um
  e-mail **genérico** (sem o novo status no corpo, só um link para o Portal)
  quando o status de um caso dele muda.

---

## 6. PAPÉIS, PERMISSÕES E CONTROLE DE ACESSO

### 6.1 Dois papéis

- **Gestor** — acesso total, intocável pelo catálogo de permissões.
- **Atendente** — opera casos, clientes, tarefas e documentos. **Sem** acesso
  administrativo.

### 6.2 O que é administrativo (só Gestor, sem exceção e sem toggle)

Estas áreas **não entram** no catálogo de permissões. Não existe botão que dê
isso a um Atendente:

- Tela de **Configurações** inteira (incluindo a gestão de usuários e
  permissões)
- Tela de **Auditoria**
- Tela de **Dashboard**
- As três ações de **remoção**: remover item de checklist, remover campeonato,
  remover resultado

### 6.3 Catálogo de funções (só tem efeito sobre Atendente)

```ts
export const FUNCOES = {
  atendimentos:         'Atendimentos (CRM)',
  casos:                'Casos',
  tarefas:              'Tarefas e Prazos',
  clientes:             'Clientes',
  aprovacoes_pendentes: 'Aprovações Pendentes',
  documentos_aprovar:   'Documentos a Aprovar',
  campeonatos:          'Campeonatos',
  resultados:           'Resultados',
  habitualidade:        'Habitualidade do Clube',
  testar_pipeline:      'Testar Pipeline',
  status_projeto:       'Status do Projeto',
} as const;
```

A tela **Início** fica de fora do catálogo de propósito: ela é resumo do que a
pessoa já pode ver, e cada bloco dela some sozinho para quem não tem a função
correspondente.

### 6.4 A regra central: **ausência de linha significa PERMITIDO**

`usuario_permissao` só ganha linha quando o Gestor desliga (ou religa) algo pela
tela. Ninguém perde acesso por falta de linha no banco.

```ts
function temPermissao(usuario, funcao) {
  if (usuario.papel === 'Gestor') return true;
  const linha = permissoes.find(p => p.funcao === funcao);
  return linha ? linha.ativo : true;   // sem linha => permitido
}
```

### 6.5 Duas travas, e a de interface é a mais fraca

- **Interface** — o menu e os botões só renderizam o que a pessoa pode. É
  conforto, não segurança.
- **Servidor / RLS** — a trava de verdade. Toda operação valida de novo, contra
  o banco. **Nunca confie no que o front mandou.**

Duas proteções que o sistema antigo aprendeu na marra e que precisam sobreviver
à migração:

1. **Uma rota é administrativa OU operacional, nunca as duas.** Não misture a
   checagem de Gestor com a checagem de função na mesma tela — isso cria uma
   porta que abre pelos dois lados.
2. **Uma rota que aceita várias funções libera se QUALQUER UMA bater.** A tela
   Início aceita cinco funções; se ela só checasse "alguma bateu", um Atendente
   com apenas `casos` receberia a fila de aprovações pendentes de brinde. Cada
   bloco precisa ser conferido **de novo**, individualmente, dentro da tela.

### 6.6 Senha e login

- **Staff:** e-mail + senha via Supabase Auth. Um usuário criado pela tela
  nasce **sem** login configurado — o próprio dono define a senha depois, por um
  convite/reset. Gestor nunca digita a senha de outra pessoa.
- **Um Gestor não pode mudar o próprio papel nem se desativar.** Sem esse
  bloqueio, a empresa pode ficar sem ninguém com acesso administrativo.
- **Cliente:** **magic link** por e-mail (Supabase Auth já faz nativamente).
  Nunca senha, nunca reaproveitando credencial de staff. Validade do link:
  15 minutos, uso único.
- **As duas sessões são separadas.** No sistema antigo eram cookies com nomes
  diferentes, para os dois apps rodarem no mesmo navegador sem se misturar. No
  Lovable, garanta que uma sessão de cliente **nunca** possa alcançar rota de
  `/app/*` — a checagem é `perfil.tipo`, no servidor.

---

## 7. REGRAS DE NEGÓCIO QUE NÃO PODEM SE PERDER

**Esta é a seção mais importante do arquivo.** Cada regra abaixo existe porque a
ausência dela já produziu um erro real, num sistema que hoje atende gente de
verdade num domínio regulado. Cole a regra relevante junto do prompt da tela
correspondente.

### 7.1 `NULL` é "não sei". `0` é "consultei e não teve". Nunca confunda os dois

A regra vale para o sistema inteiro, e é a que mais protege contra o painel
mentir. Num gráfico, "não sei" e "zero" viram a mesma barra baixinha — e é assim
que um painel começa a mentir sem ninguém perceber.

Onde ela aparece:

- `filiado.participacoes_12m` — `NULL` é *nunca sincronizado*, não *treinou
  zero vezes*.
- `filiado.anuidade_em_dia` — `NULL` é *o campo não veio da API*, não *está
  devendo*. **Acusar de inadimplente quem tem cadastro incompleto é o pior erro
  possível desta tela**, porque é dela que sai cobrança.
- `documento.data_validade` — `NULL` é *sem data cadastrada*. **Não é
  "válido".** Pintar de verde afirmaria o que ninguém conferiu. A situação de
  validade tem **quatro** estados: vencido / vencendo / válido / **sem data**.
- `servico.prazo_estimado_dias` e `valor_referencia` — `NULL` vira o texto
  *"a confirmar com nossa equipe"*, nunca um número inventado nem um zero.

Quando uma consulta externa falha, o sistema registra "fonte indisponível" e
**não preenche a chave**. Escrever `armas: []` seria a afirmação *"consultei,
essa pessoa não tem arma nenhuma"*.

### 7.2 Toda mudança de estado do Caso passa por uma função, nunca por UPDATE direto

Mudar status ou responsável **sempre** valida (status contra a lista, usuário
ativo) e **sempre** grava uma linha em `historico`, na mesma transação. Nenhuma
tela faz `update caso set status=...` direto.

No Supabase isso vira uma **Edge Function** ou uma função Postgres
`security definer` — não um `.update()` do cliente supabase-js. As policies de
`caso` devem permitir `select` para o front, e a escrita passa pela função.

O histórico registra criação, status, responsável e prazo. **Não** registra
edição de descrição, que viraria log de digitação. Sempre com
`tipo_evento='outro'` para eventos de tarefa: os outros quatro valores falam do
**Caso**, e um `mudanca_status` ali seria lido como status do Caso.

### 7.3 O banco grava UTC. A tela pensa em dia LOCAL

Esta é a armadilha que mais mordeu o sistema, e ela morde nos dois sentidos:

- **Usar a hora do banco para saber que dia é hoje.** Às 21h de Brasília o
  relógio UTC já virou o dia — então toda tarefa com prazo de hoje apareceria
  atrasada, justamente no fim do expediente. **Hoje** é sempre calculado no fuso
  local, nunca com `current_date` do servidor.
- **Usar o dia de hoje para ler a hora do banco.** Comparar direto tirava de
  "concluídos neste mês" o caso encerrado depois das 21h de Brasília, e jogava
  para o mês seguinte o que foi encerrado na noite do dia 31.

**Como fazer certo no Postgres:** converta antes de comparar —
`(encerrado_em at time zone 'America/Sao_Paulo')::date`. O deslocamento vem do
fuso configurado, **nunca de um número fixo no código**.

**Prazo de tarefa é um DIA** (`date`), não um instante. Compare dia com dia.

### 7.4 `encerrado_em` carimba ao encerrar e **apaga** ao reabrir

Sem apagar, um caso reaberto guardaria uma data de encerramento que já não
significa nada, e "quantos casos você concluiu em agosto?" passaria a mentir.
**`Cancelado` não conta como concluído.**

### 7.5 `proxima_acao` (Processo) e Tarefa são coisas diferentes

- `processo.proxima_acao` é o **estado** de um processo perante o órgão:
  *"aguardando comprovante"*.
- **Tarefa** é trabalho com dono e data, que alguém marca como feito.

Um processo parado pode ter três tarefas. Uma tarefa pode não ter processo
nenhum. Não junte os dois campos numa tela só.

### 7.6 `data_conclusao` é consequência do status, nunca digitada

Concluir carimba. Reabrir apaga. E **"atrasada" só vale para tarefa em aberto**:
trabalho feito ontem com prazo de anteontem não é pendência, é trabalho feito.

**Contagem e lista saem da MESMA função.** Duas implementações da regra de
atraso divergem, e aí a tela mostra "3 atrasadas" acima de uma lista com 2
linhas.

### 7.7 Documento do CASO e documento do DOSSIÊ

- **`categoria='Caso'`** — o comprovante que o cliente mandou num atendimento.
  Preso a um caso ou processo.
- **`categoria='Dossiê'`** — permanente **da pessoa**. O CR é do cliente: vale
  anos, atravessa vários casos e continua valendo quando todos fecharem.
  `caso_id` e `processo_id` **têm que ser NULL**.

Três regras que vêm junto:

1. **`observacoes` responde "de qual arma".** CRAF, guia de tráfego e nota
   fiscal existem mais de uma vez por pessoa; sem uma referência, três CRAFs no
   dossiê ficam indistinguíveis.
2. **O cliente NÃO envia documento pelo dossiê.** O dossiê é o que o despachante
   conferiu e guardou. Envio de cliente entra pelo **checklist do caso**, nasce
   `Aguardando aprovação` e passa por conferência humana. Deixar o cliente
   escrever direto no dossiê apagaria essa distinção.
3. **Não confunda `documento_exigido` com o catálogo de tipos.**
   `documento_exigido` é o checklist de um serviço — frases de exigência.
   O catálogo (5.1) são **nomes** de documento, que é o que serve de rótulo de
   arquivo guardado.

### 7.8 Quem cria a ligação do checklist define em que estado ela nasce

É a regra inteira, e ela é sutil:

- **Marcação feita no painel nasce `Aprovado`** — o funcionário abriu o arquivo
  para decidir; a conferência aconteceu no mesmo gesto.
- **Envio pelo Portal nasce `Aguardando aprovação`** — é uma afirmação do
  cliente, ninguém conferiu ainda.
- **`Recusado`** guarda `motivo_recusa`, que **é mostrado ao cliente**, e para
  efeito de checklist conta como faltando.

**Pendente NÃO conta na contagem X/Y nem no anel de progresso.** Contar infla o
progresso com trabalho que ninguém fez.

A decisão é **sempre humana**. A IA nunca decide que um PDF é a certidão X.

### 7.9 Multi-tenant: a empresa vem da sessão, nunca da requisição

Já coberto pelas policies de RLS (4.1), mas vale explicitar o que isso implica
para o front:

- **Nenhuma chamada do front manda `empresa_id`.** Se você vir isso num
  formulário ou numa query string, é bug.
- **Dois clientes da MESMA empresa são o caso perigoso.** O filtro de empresa
  não cobre isso. Toda rota que recebe um `caso_id`/`documento_id` vindo do
  navegador do cliente precisa conferir o **dono** — é a policy
  `cliente_id = cliente_atual()`.
- **Os IDs são numerados globalmente**, não por empresa. Fica estranho ver
  `CAS-000001` numa empresa e `CAS-000002` na outra, e é de propósito: numerar
  por empresa abriria risco de colisão em cinco geradores diferentes.

### 7.10 Catálogo é sugestão, não obrigação — e nada some, só desativa

`resultado_campeonato.modalidade` continua **texto**, não vira FK: os resultados
já cadastrados têm modalidade digitada à mão, e uma FK os quebraria. O catálogo
entra como `datalist` no formulário.

**Modalidade que sai do catálogo vira `ativo=false`, nunca `DELETE`.** Pode
haver resultado antigo mencionando ela, e apagar deixaria a tela sem como
explicar de onde veio aquele texto. A mesma escolha vale para filiado: a
sincronização nunca apaga ninguém.

### 7.11 Dado sensível: o que o sistema faz de propósito

O domínio é documentação de arma de fogo. Um erro aqui não é uma tela feia — é
número de série de arma, CPF e histórico de treino de uma pessoa real vazando.

- **O Portal é a primeira superfície pública do sistema.** Toda rota que recebe
  um ID do navegador do cliente confere o dono **antes** de ler ou escrever
  qualquer coisa. Visualizar o arquivo dentro da plataforma e baixar usam o
  **mesmo endpoint com a mesma checagem** — só muda o cabeçalho. Um caminho
  paralelo "só para visualizar" é exatamente como esse tipo de furo nasce.
- **Número de série de arma nunca entra em prompt de IA.** O que o modelo nunca
  recebe, ele nunca repete numa resposta. No Lovable isso significa: se você
  construir qualquer chamada de IA, o campo de série não vai junto.
- **CPF é mascarado antes de sair para serviço externo** (`***.***.789-**`), e
  **nunca** aparece em URL, mensagem de erro ou log. O CPF fica no caminho da
  URL da API do clube, e a exceção crua do cliente HTTP traz a URL inteira
  dentro — foi assim que ele quase foi parar num log e num e-mail de alerta.
- **Mensagem de recusa de acesso é fixa e igual para todos os motivos.** Dizer
  *"esse CPF não confere"* transforma a checagem num verificador de palpites.
- **Todo acesso a dado sensível, liberado OU negado, vira linha em
  `log_administrativo`** com `tipo_evento='ACESSO_DADO_SENSIVEL'`. Uma sequência
  de negados no mesmo cliente é o sinal mais visível de alguém tentando
  adivinhar o CPF de outra pessoa.

### 7.12 O que o sistema deliberadamente NÃO faz

Isto não é lista de pendência. São decisões, e reverter qualquer uma delas
piora o produto:

- **Não diz se alguém cumpriu o mínimo legal de habitualidade.** O mínimo do
  art. 35 do Decreto nº 11.615/2023 depende do nível do CR (8, ou 12+4, ou
  20+6), e a API do clube **não expõe o nível de ninguém**. O custo de errar é
  dizer a um atirador que está em dia quando não está.
- **Não mostra valor em reais do consumo de IA.** O preço por token é do
  fornecedor e muda sem avisar. Um "R$ 47" com preço chutado no código seria o
  número que ninguém confere e todo mundo repete. Mostre chamadas e tokens.
- **Não registra o que foi cobrado nem o que foi pago.** "Em andamento" no
  Dashboard é **valor de tabela**, não receita — e a tela precisa dizer isso com
  todas as letras. É a maior lacuna do sistema como ferramenta de gestão, e
  fingir o contrário seria pior que a lacuna.
- **`resultado_campeonato` mostra a classificação COMPLETA da prova**, não só o
  resultado do cliente logado. Por isso `nome_atirador` é sempre preenchido e
  `cliente_id` é opcional: dá para destacar "você" na lista sem exigir que todo
  participante esteja cadastrado como cliente.
- **A cópia local do dado do clube é RETRATO, não verdade.** O sistema externo é
  quem reporta à Polícia Federal e ao Exército. Toda tela que mostra esses
  números é **obrigada** a mostrar `sincronizado_em` junto, e nenhuma afirmação
  a cliente pode sair dali — pergunta de cliente se responde com consulta ao
  vivo.

---

## 8. PAINEL ADMINISTRATIVO — as telas, uma por uma

**Estrutura do menu lateral** (esta é a ordem, e ela importa: o trabalho do dia
vem antes do dado de referência):

```
Início
Dashboard                          [Gestor]

ATENDIMENTO
  Atendimentos                     [funcao: atendimentos]
  Casos                            [funcao: casos]
  Tarefas e Prazos                 [funcao: tarefas]
  Clientes Despachante             [funcao: clientes]
  Aprovações Pendentes             [funcao: aprovacoes_pendentes]
  Documentos a Aprovar             [funcao: documentos_aprovar]

CLUBE
  Filiados                         [funcao: habitualidade]
  Campeonatos                      [funcao: campeonatos]
  Modalidades                      [funcao: campeonatos OU resultados]
  Resultados                       [funcao: resultados]

SISTEMA
  Configurações                    [Gestor]
  Auditoria                        [Gestor]
  Status do Projeto                [funcao: status_projeto]
  Testar Pipeline                  [funcao: testar_pipeline]
```

---

### 8.1 Início — resumo COM CAMINHO, não painel de números

Responde a uma pergunta só: *"o que precisa da minha atenção hoje?"*

**Nenhuma contagem nova é implementada aqui.** Cada bloco chama exatamente a
mesma consulta da tela de destino. Duas implementações da mesma contagem
divergem, e aí o número da Início não bate com a lista que ele abre.

**O valor da tela é o caminho:** cada número é um botão que leva à tela onde
aquele trabalho é feito, **já com o filtro aplicado** (atrasadas → Tarefas
filtrado por atrasadas). Número que não leva a lugar nenhum é decoração.

Blocos:

| Bloco | Número | Leva para |
|---|---|---|
| Tarefas atrasadas | tarefas em aberto com `prazo < hoje` | Tarefas, filtro "atrasadas" |
| Tarefas para hoje | em aberto com `prazo = hoje` | Tarefas, filtro "hoje" |
| Casos parados | caso vivo sem atualização há **7 dias** | Casos, ordenado por mais parado |
| Aprovações pendentes | respostas da IA aguardando revisão | Aprovações Pendentes |
| Documentos a aprovar | checklist `Aguardando aprovação` | Documentos a Aprovar |
| Conversas abertas | conversas com status `Aberta` | Atendimentos |

**"Caso parado" é caso vivo sem atualização há 7 dias.** A tela de Casos promete
mostrar "o que está parado", mas ordenada por data ela mostra o que é
**recente** — o parado fica no fim, que é onde ninguém olha.

**Cada bloco confere a permissão de novo, individualmente** (ver 6.5, item 2).

---

### 8.2 Dashboard — o painel do dono, com travas para ele não mentir

Só Gestor. É a única tela que cruza o Core e o Domínio de propósito.

**Blocos:**

1. **Casos** — abertos, concluídos no mês, tempo médio até encerrar.
2. **Processos por status** — barras. "Em andamento" mostra o **valor de
   tabela**, com o rótulo dizendo isso (não é receita — ver 7.12).
3. **Casos por canal de origem** — de onde o cliente chega.
4. **Volume de mensagens por mês.**
5. **Consumo de IA** — chamadas e tokens. **Nunca reais.**
6. **Habitualidade do clube por dia** (últimos 30 dias) — barras.
7. **Novos filiados por mês** — a partir de `data_filiacao`, a data **real**.
8. **Situação financeira do clube** — quantos em cada estado.

**As quatro travas do Dashboard:**

- **Mês em curso NUNCA se compara com mês fechado.** Toda comparação é contra o
  **mesmo pedaço** do mês anterior (dia 1 até o dia equivalente), e a barra do
  mês corrente aparece esmaecida. Sem isso, dia 5 de todo mês pareceria
  desastre. Use `min(dia_de_hoje, ultimo_dia_do_mes_anterior)` — 31 de março não
  existe em fevereiro, e sem esse `min` o Dashboard sai do ar em três dias do
  ano.
- **Todo recorte por dia ou por mês converte para o fuso local antes de
  comparar** (7.3).
- **Onde o banco não sabe, mostre "—", nunca zero** (7.1).
- **Cobertura junto do gráfico de habitualidade:** *"X de Y filiados ativos já
  têm datas"*. Um gráfico subindo pode ser o clube treinando mais **ou** a
  sincronização alcançando mais gente — sem esse número ao lado, os dois são
  indistinguíveis, e a leitura errada é a otimista.
- **Estado vazio só quando NINGUÉM foi consultado.** Trinta dias zerados com
  gente consultada é uma afirmação legítima ("não houve movimento"). Dizer "não
  há datas no banco" ao lado de um quadro marcando 100% de cobertura foi um
  defeito real.

---

### 8.3 Atendimentos (CRM) — lista de conversas + thread

**Lista:** conversa por linha, com cliente, canal (com ícone), status, última
mensagem (data + trecho), responsável. Filtros: canal, status, responsável.

**Regra de agrupamento: UMA conversa por (cliente, canal).** E-mail e WhatsApp
da mesma pessoa são fios **distintos de propósito** — têm ritmo e histórico
próprios, e juntá-los produziria uma thread ilegível.

**Conversa encerrada nunca é reaproveitada.** Encerrar é gesto deliberado do
atendente; a próxima mensagem abre uma conversa nova.

**Thread (detalhe):** bolhas. Cada linha de `mensagem` vira **até duas** (4.5).
Bolha do cliente à esquerda, resposta à direita, com etiqueta de origem
(`Motor IA` ou `Atendente`) e horário.

**Caixa de resposta** no rodapé. **Resposta digitada no painel não passa pelo
Motor IA nem pelo Auditor**, de propósito: quem digitou já é o humano que a
revisão humana existe para garantir.

**Aviso permanente no topo quando o WhatsApp está em modo simulado:** a
confirmação de envio precisa dizer **"NÃO enviado"** com todas as letras. O pior
resultado possível é o usuário achar que o cliente recebeu algo que ninguém
recebeu.

---

### 8.4 Casos — lista, ficha e abertura à mão

**Lista:** ID (mono), cliente, título, categoria, status (badge colorido),
prioridade, responsável, última atualização. Filtros por status, responsável,
prioridade. Ordenação por "mais parado" disponível.

**Ficha do caso** — uma tela, com blocos:

- **Cabeçalho:** ID em mono, título grande, badges de status e prioridade.
- **Ficha de dados** em grade rótulo/valor: cliente (link), categoria, origem,
  canal, responsável, criado em, prazo previsto.
- **Ações:** mudar status (select), trocar responsável (select de usuários
  ativos), editar descrição.
- **Processos** — cada um com serviço, protocolo, status, próxima ação, prazo. E
  dentro de cada processo, o **checklist de documentos**: anel de progresso X/Y
  + lista de itens agrupados por `grupo`. Cada item mostra se tem arquivo, o
  status (`Aprovado` / `Aguardando aprovação` / `Recusado` + motivo) e permite
  anexar.
- **Tarefas do caso** — a mesma tarefa que aparece na tela Tarefas.
- **Documentos do caso** — upload e lista.
- **Histórico** — linha do tempo, só leitura.

**Abrir caso à mão** (tela própria, não modal): o cliente ligou ou apareceu na
porta. Campos: cliente (busca por nome/CPF, **com cadastro de cliente novo na
mesma tela**), título, categoria (do catálogo de serviços), canal de origem
(inclui Telefone e Presencial), prioridade, responsável, descrição.

O caso aberto à mão se distingue por `origem='Painel'` e por `criado_por` ser o
nome de quem estava logado, não "Motor IA". **Usa exatamente o mesmo caminho de
criação que o Motor IA usa** — duas formas de um caso nascer, com regras
diferentes, seria a primeira divergência a aparecer no histórico.

---

### 8.5 Tarefas e Prazos

**Lista com filtros que são o produto:** atrasadas / hoje / esta semana / todas
em aberto / concluídas. Colunas: prazo (mono, com cor), tipo, descrição, caso
(link), cliente, responsável, prioridade, status.

Cores: prazo vencido em `--signal`, hoje em `--amber`, futuro neutro. **Só para
tarefa em aberto** (7.6).

**Criar/editar:** caso (obrigatório), tipo (datalist com sugestões), descrição,
responsável, prazo (date), prioridade. **O `cliente_id` é lido do caso**, nunca
de um campo do formulário.

Botão "Concluir" na linha. Concluir carimba `data_conclusao`; reabrir apaga.

---

### 8.6 Clientes Despachante

**Lista:** nome, CPF (mono, formatado), telefone, cidade, status, último
atendimento. Busca por nome ou CPF.

**Ficha do cliente:**

- Dados cadastrais (grade rótulo/valor), editáveis.
- **Bloco "No clube"** — se o CPF bater com um `filiado`, mostra matrícula,
  status de filiação, retrato de habitualidade (participações em 12m, última
  data) **com `sincronizado_em` ao lado**, e situação de anuidade/CR. Se não
  bater, diz "não localizado como filiado" — que é diferente de "não é
  atirador".
- **Casos do cliente** — lista com link.
- **Dossiê** — os documentos permanentes da pessoa (`categoria='Dossiê'`).
  Agrupados pelo catálogo (5.1). Cada um com tipo, referência, data de validade
  e **situação em quatro estados**: válido (azul), vencendo (âmbar, ≤30 dias),
  vencido (vermelho), **sem data (neutro, nunca verde)**. Upload e remoção.

**Cadastro de cliente novo:** nome, CPF, e-mail, telefone, cidade. Ao digitar o
CPF, oferece consultar o clube para pré-preencher — mas o cadastro é nosso, e
o dado do clube nunca é copiado automaticamente para dentro dele.

---

### 8.7 Aprovações Pendentes

A fila do freio de segurança. Enquanto `revisao_humana_ativa='Sim'`, toda
resposta que a IA escreveu com a ação "enviar" para aqui em vez de sair sozinha.

Cada item mostra: cliente, canal, **a pergunta do cliente**, **a resposta que a
IA escreveu**, e o que o Auditor disse. Dois botões: **Aprovar** (envia) e
**Rejeitar**.

**Aprovar devolve pelo CANAL DE ORIGEM da pergunta**, nunca sempre por e-mail.

---

### 8.8 Documentos a Aprovar

Fila dos arquivos que o **cliente** enviou pelo Portal e que ninguém conferiu
(`documento_checklist.status='Aguardando aprovação'`).

Cada item: cliente, caso, qual item do checklist ele diz ser, e o arquivo
(visualizável na própria tela). Botões: **Aprovar** e **Recusar com motivo** — o
motivo é obrigatório e **é mostrado ao cliente no Portal**.

Remover a ligação é ação de **Gestor**.

---

### 8.9 Filiados (clube) — somente leitura

Espelho do sistema do clube. **Nenhuma tela desta seção escreve.**

**Painel de cobertura no topo, obrigatório:** total de filiados, quantos ativos,
quantos já sincronizados, **quando foi a última sincronização**.

**Lista:** nome, CPF, matrícula, status de filiação, participações em 12m,
última participação, situação de anuidade. **Marca quem também é cliente do
despachante** (pelo CPF) com um selo que leva à ficha do cliente.

> **Como fazer o cruzamento sem matar o banco:** traga o lado pequeno inteiro
> (os clientes, dezenas) e cruze em memória por CPF. Uma consulta por linha em
> 1500 filiados, ou um `IN` com 1500 parâmetros, são os dois caminhos errados.

**Ficha do filiado:** dados, retrato de habitualidade com as datas, situação
financeira e de CR.

**Dois campos que NÃO são a mesma coisa, e a tela mostra os dois separados:**
`anuidade_em_dia` é o status que o sistema do clube calcula;
`anuidade_validade` é a data. Eles **discordam** para parte dos filiados reais.
Sem saber a regra do fornecedor, juntar num número só seria inventar uma
interpretação e apresentá-la como fato. A tela diz quantos estão em cada estado
**e avisa que os dois não coincidem**.

---

### 8.10 Campeonatos, Modalidades e Resultados

**Campeonatos:** lista (nome, data início/fim, local) + criar/editar. Remover é
de Gestor.

**Modalidades:** somente leitura, agrupada por grupo, com contagem. Dado de
referência das outras duas telas — **não é uma área nova**, por isso a permissão
é `campeonatos OU resultados`. Mostra `sincronizado_em`.

**Resultados:** dentro de um campeonato. Lista a **classificação completa da
prova** (colocação, nome do atirador, modalidade, pontuação), com destaque para
quem também é cliente. Criar/editar com `datalist` de modalidades. Remover é de
Gestor.

---

### 8.11 Configurações (Gestor)

Três abas:

1. **Chaves** — lista de `configuracoes` agrupada por categoria, cada uma com
   chave (mono, pequeno), descrição e campo editável. **A chave
   `revisao_humana_ativa` merece destaque visual e um texto explicando o que
   desligá-la significa.**
2. **Usuários** — lista com nome, e-mail, papel, ativo, e se o login já foi
   configurado. Criar usuário (nasce sem senha). Editar papel e ativo. Botão
   **Permissões** na linha de cada Atendente.
3. **Permissões** — um toggle por função do catálogo (6.3). Lembre: **ausência
   de linha = permitido**, então o toggle nasce ligado.

**Toda mudança nas três abas grava em `log_administrativo`, na mesma
transação.**

---

### 8.12 Auditoria (Gestor) — só leitura, e por quê

**Não existe rota de escrita nesta tela.** Registro que a própria pessoa
auditada pode alterar não audita nada.

Lista o `log_administrativo`: quando, quem, tipo de evento, alvo, de que valor
para que valor.

**O que a tela acrescenta a listar linhas** — e era justamente o que ninguém
via: um aviso no topo dizendo **quantos pedidos de dado sensível foram
RECUSADOS nos últimos 7 dias**, e explicando o que isso significa. Um recusado
isolado é cliente digitando o CPF errado. Vários seguidos no mesmo cliente é
alguém tentando adivinhar CPF de outra pessoa.

**Traduza ID para nome de gente na exibição, com o ID ao lado.** O log guarda ID
de propósito (nome muda, ID não), mas tela de auditoria que exige decorar
identificador não é lida por ninguém.

---

### 8.13 Status do Projeto e Testar Pipeline

Duas telas de desenvolvimento. **Construa por último, ou nem construa.**

- **Status do Projeto** — panorama do que existe no banco (contagens por tabela)
  e do que está configurado.
- **Testar Pipeline** — caixa de texto onde se digita uma mensagem fictícia e se
  vê o que cada etapa do Motor IA respondeu. Só faz sentido depois que o serviço
  Python estiver conectado.

---

## 9. PORTAL DO CLIENTE — app separado

Autoatendimento para o cliente final. **Não é staff.** Sessão totalmente
separada da do painel (6.6).

**Visual:** mesmas fontes do painel de propósito (são dois apps do mesmo
sistema), mas mais leve — cards com `--radius: 8px` sobre `--paper`, menos
densidade, tudo maior. Tem que funcionar bem no celular: é onde o cliente vai
abrir.

**Acessibilidade não é opcional aqui:** link "pular a navegação", foco visível
(`outline: 2px solid var(--blue)`), e o âmbar escuro de 5.6:1 (seção 3).

### 9.1 Entrar

Uma tela: campo de e-mail e um botão. Manda o **magic link**. A mensagem de
retorno é **sempre a mesma**, tenha o e-mail cadastro ou não — dizer "e-mail não
encontrado" transforma a tela num verificador de quem é cliente de quem.

### 9.2 Telas

| Tela | O que mostra |
|---|---|
| **Início** | Resumo: casos em andamento, o que está pendente **dele** (documento faltando, documento recusado com o motivo) |
| **Meus casos** | Lista com status em linguagem de cliente, não jargão interno |
| **Caso (detalhe)** | Status, o que está acontecendo, os processos e **o checklist**: o que já foi entregue, o que falta, o que foi recusado e por quê. Botão de **enviar documento** por item |
| **Meus processos** | Todos os processos, com protocolo e próxima ação |
| **Minha habitualidade** | Consulta **ao vivo** ao sistema do clube. Ver 9.3 |
| **Campeonatos** | Calendário das provas |
| **Resultados** | Classificação completa das provas, com "você" destacado |
| **Minha conta** | O **dossiê**: os documentos dele. Lista, visualiza **dentro da plataforma** e baixa |

### 9.3 A tela de habitualidade tem TRÊS estados, não dois

Este é o detalhe que mais importa no Portal inteiro:

1. **Tem registro** — mostra as participações.
2. **Sem registro de atirador** — afirmação legítima: *"consultamos, você não
   tem participação registrada"*.
3. **Consulta indisponível** — *"não conseguimos consultar agora"*. Visualmente
   **diferente** do estado 2.

Sem o terceiro estado, uma falha de rede vira a afirmação "você não treinou",
para um atirador que treinou. É a regra 7.1 vista pelo lado do cliente.

### 9.4 Upload de documento pelo cliente

Ele manda o arquivo dizendo a qual item do checklist ele corresponde. O envio
carrega `processo_id` e `documento_exigido_id` **vindos do navegador dele** — e
por isso o servidor **confere que aquele processo pertence a um caso que já se
sabe ser dele**, antes de gravar qualquer coisa.

Nasce `Aguardando aprovação` (7.8). A tela precisa dizer isso: *"recebido,
aguardando conferência"* — nunca "documento aprovado".

### 9.5 Três cores para três ações no dossiê

Azul = válido. Âmbar = vencendo. Vermelho = vencido. No primeiro desenho os dois
últimos eram vermelho, e o cliente não distinguia *"já venceu"* de *"vai
vencer"* — que são duas urgências completamente diferentes. Documento sem data
cadastrada fica neutro.

---

## 10. ORDEM DE CONSTRUÇÃO SUGERIDA

Não construa na ordem do menu. Construa na ordem em que uma tela sustenta a
próxima:

1. **Fundação** — projeto, visual (seção 3), `empresa`, `perfil`, as três
   funções de RLS, login de staff.
2. **Cliente e Serviço** — as duas tabelas que tudo referencia. Tela de
   Clientes (lista + ficha, sem dossiê ainda).
3. **Caso** — tabela, lista, ficha, abertura à mão, `historico`. **É aqui que o
   sistema começa a existir.**
4. **Processo + checklist** — dentro da ficha do Caso.
5. **Tarefas** — tela própria + bloco dentro da ficha do Caso.
6. **Início** — só depois que 3, 4 e 5 existem, porque ela só reaproveita as
   contagens deles.
7. **Documentos e dossiê** — Storage, upload, catálogo de tipos, validade.
8. **Papéis e permissões** — Configurações, usuários, `log_administrativo`,
   Auditoria.
9. **Portal do Cliente** — magic link, casos, checklist, upload, dossiê.
10. **Conversa e mensagem (CRM)** — depende do serviço Python para popular.
11. **Clube** — Filiados, Modalidades, Campeonatos, Resultados.
12. **Dashboard** — por último, porque ele lê tudo que veio antes.

---

## 11. AVISOS ANTES DE COMEÇAR

**1. Não jogue o banco atual dentro do Lovable.** O banco em produção tem nome,
CPF, e-mail, telefone e documento de pessoas reais — clientes do despachante e
~1450 filiados de um clube de tiro. Preview de Lovable é ambiente de
desenvolvimento. Para testar, use dados fictícios; o sistema atual já tem um
gerador deles.

**2. As policies de RLS não são opcional nem "depois".** Um projeto Supabase
sem RLS deixa qualquer pessoa com a chave `anon` — que fica **dentro do
JavaScript do navegador**, à vista de todos — ler o banco inteiro. Nesse domínio
isso é vazamento de dado de arma de fogo. Escreva a policy **junto** da tabela,
nunca em outro prompt.

**3. O Lovable vai propor simplificações que quebram regras da seção 7.** Ele
vai querer transformar `Sim/Não/NULL` em booleano simples, juntar `proxima_acao`
com tarefa, e usar `current_date` para "hoje". Quando isso acontecer, cole de
volta a regra correspondente. Cada uma delas está aqui porque a versão
"simples" já causou um erro real.

**4. A migração de dados é um trabalho à parte.** SQLite → Postgres, com
conversão de `'Sim'/'Não'` para boolean, texto ISO para `timestamptz`, e criação
de um `auth.users` + `perfil` para cada usuário e cada cliente. Não tente fazer
isso no mesmo prompt em que constrói uma tela.

**5. Rode os dois sistemas em paralelo antes de desligar o antigo.** O Flask
atual atende cliente de verdade, com e-mail chegando a cada 2 minutos e Tarefa
Agendada rodando backup às 3h. A troca só acontece quando o novo tiver
sobrevivido a uma semana de uso real ao lado do velho.
