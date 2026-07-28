# Schema — Multi-tenant (`empresa_id`)

> **Status: DECISÕES FECHADAS (2026-07-28) — implementação em andamento.** Este documento fechou as decisões antes da migração, seguindo a regra do `PROJETO_1.md` §8 ("não pular etapas de projeto/documentação/validação antes de implementar"). As três decisões que estavam em aberto foram resolvidas na seção 7.
> Fonte: `PROJETO_1.md` §7 (Fase 6 — Produto), `core/db/schema.sql` (18 tabelas), `docs/portal_cliente_arquitetura.md` (isolamento de dado).
> Pré-requisito já entregue: suíte de testes de isolamento (`tests/`), commit `0c71e42` — é ela que vai provar que a migração não abriu vazamento.

---

## Como ler este documento

- **Tenant** = inquilino. Cada empresa que usa o sistema é um tenant. "Multi-tenant" = um sistema só, atendendo várias empresas, sem que uma enxergue o dado da outra.
- **`empresa_id`** = a coluna que responde "de quem é esta linha?".
- **Constraint `UNIQUE`** = regra do banco que proíbe valor repetido numa coluna.
- **RLS** (*Row Level Security*) = recurso do PostgreSQL onde o próprio banco recusa devolver linha de outra empresa, mesmo se o programador esquecer o filtro.

---

## 1. O problema, em uma frase

Hoje toda linha do banco pertence implicitamente à Smith. Não existe coluna dizendo isso porque só existe uma empresa. No minuto em que um segundo despachante entrar, cada linha precisa dizer de quem ela é — senão a Smith vê o cliente do concorrente, e vice-versa.

Num domínio de documentação de arma de fogo, esse vazamento não é um bug comum: é dado pessoal sensível de terceiro, com implicação regulatória.

---

## 2. Tabela nova: `empresa`

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `empresa_id` | TEXT | Sim | PK | Formato `EMP-000001`, mesmo padrão de ID do resto do projeto. |
| `nome` | TEXT | Sim | — | Ex.: `Smith Clube de Tiro`. |
| `dominio` | TEXT | Sim | — | Qual pacote de Domínio a empresa usa: `clube_tiro`, `advocacia`… É o campo que liga a Fase 5 (domínio como plugin) à Fase 6 (produto). |
| `ativo` | TEXT (`Sim`/`Não`) | Sim | — | Empresa suspensa por falta de pagamento fica `Não`, nunca é apagada. |
| `criado_em` | TEXT (ISO 8601) | Sim | — | Imutável. |

A Smith vira `EMP-000001` e todo o dado existente hoje passa a ser dela.

---

## 3. As 18 tabelas do Core, em três grupos

### Grupo A — dado de atendimento (recebe `empresa_id` direto)

`cliente` · `caso` · `processo` · `documento` · `sessao` · `memoria_ia` · `conversa` · `mensagem` · `tarefas` · `log_ia`

São 10 tabelas. Nenhuma surpresa aqui: é dado de cliente, e cliente pertence a uma empresa.

Destaque para **`log_ia`**: com `empresa_id`, ele passa a responder *quanto de IA cada empresa consumiu* — que é literalmente a base para cobrar assinatura depois. Vale a pena não deixar essa de fora achando que log é "só técnico".

### Grupo B — catálogo e configuração da empresa (recebe também)

`servico` · `documento_exigido` · `configuracoes` · `template` · `usuario`

São 5 tabelas, e é o grupo que costuma passar batido:

- **`servico`** tem `prazo_estimado_dias` e `valor_referencia`. Outro despachante cobra outro preço e promete outro prazo. Hoje esses valores são globais.
- **`configuracoes`** guarda `nome_empresa`, `telefone`, `horario_semana`, `assinatura_email`. Tudo isso é por empresa — inclusive `revisao_humana_ativa`: uma empresa pode querer o freio de revisão ligado e outra não.
- **`usuario`** — funcionário pertence a uma empresa.

### Grupo C — herda pelo pai (não precisa da coluna, mas eu colocaria)

`historico` (herda de `caso`) · `documento_checklist` (herda de `processo`) · `portal_token` (herda de `cliente`)

Tecnicamente dá para descobrir a empresa por JOIN. **Proposta: duplicar `empresa_id` mesmo assim**, porque toda query pode filtrar direto sem JOIN, e uma query mais simples é uma query com menos chance de esquecer o filtro. A redundância paga por si em segurança.

---

## 4. As cinco `UNIQUE` que quebram em silêncio

Este é o ponto mais importante do documento, porque **não dá erro na migração — dá comportamento errado meses depois**.

| Tabela | Constraint hoje | Precisa virar | Por quê |
|---|---|---|---|
| `cliente` | `cpf UNIQUE` (linha 16) | `UNIQUE(empresa_id, cpf)` | **A mesma pessoa pode ser cliente de dois despachantes.** Do jeito atual, o segundo a cadastrar aquele CPF recebe um erro sem sentido. |
| `usuario` | `email UNIQUE` (linha 238) | `UNIQUE(empresa_id, email)` | Duas empresas podem ter funcionários com e-mail pessoal parecido, ou o mesmo contador terceirizado. |
| `servico` | `service_key UNIQUE` (linha 69) | `UNIQUE(empresa_id, service_key)` | Toda empresa vai querer ter um serviço com a chave `renovacao_cr`. |
| `configuracoes` | `chave UNIQUE` (linha 366) | `UNIQUE(empresa_id, chave)` | Hoje só pode existir **uma** linha com `chave = 'telefone'` no banco inteiro. |
| `template` | `template_key UNIQUE` (linha 318) | `UNIQUE(empresa_id, template_key)` | Cada empresa tem sua assinatura de e-mail. |

### Uma exceção proposital

**`portal_token.token` continua `UNIQUE` global.** É um segredo aleatório de autenticação; dois tokens iguais em empresas diferentes seria uma falha de segurança, não uma conveniência.

As outras constraints já estão protegidas pelo pai e não mudam:
- `idx_memoria_ia_cliente_ativo` — escopo já é `cliente_id`
- `idx_documento_checklist_par` — escopo já é `processo_id`

---

## 5. Como impedir o vazamento de verdade

Espalhar `WHERE empresa_id = ?` à mão por dezenas de queries é frágil: basta esquecer **uma vez** para vazar. Precisamos de um ponto único de estrangulamento.

### Proposta: função de contexto na conexão + views filtradas

O SQLite permite registrar uma função Python que a SQL enxerga. Isso dá para transformar as views (que já são a fronteira de leitura obrigatória do Motor IA) em views que se filtram sozinhas:

```python
# core/conexao.py
def conectar(empresa_id: str) -> sqlite3.Connection:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.create_function("empresa_atual", 0, lambda: empresa_id)
    return con
```

```sql
-- core/db/views.sql
CREATE VIEW VW_CLIENTE AS
SELECT ... FROM cliente c
LEFT JOIN memoria_ia m ON ...
WHERE c.empresa_id = empresa_atual();
```

Três motivos para eu preferir esse caminho:

1. **Aproveita uma regra que o projeto já tem.** O `CLAUDE.md` já obriga o Motor IA a ler só por view. Com isso, o Motor IA fica isolado por construção, sem alterar nenhum módulo dele.
2. **Vira RLS de graça depois.** Quando o PostgreSQL entrar, essa mesma ideia é a `CREATE POLICY` nativa — o desenho não é jogado fora, só troca de mecanismo.
3. **Falha fechado.** Se `empresa_atual()` não for definida, a query dá erro em vez de devolver tudo. Vazar por engano fica mais difícil do que negar por engano.

**Limite honesto desta proposta:** ela protege leitura via view. `webapp/app.py` e `portal/app.py` fazem `SELECT` direto em tabela, então esses continuam precisando do filtro à mão — e é por isso que a suíte de testes de isolamento tem que crescer junto com a migração, não depois.

### Verificado, não presumido — 2026-07-28

A ideia foi testada em SQLite antes de entrar neste documento, e as três propriedades se confirmaram:

| O que se esperava | Resultado |
|---|---|
| A view devolve só o cliente da empresa conectada | ✅ `EMP-000001` viu só a Ana; `EMP-000002` viu só o Bruno |
| Dá para trocar de empresa na mesma conexão | ✅ `create_function` redefinida na hora, sem reconectar |
| Sem contexto de empresa, falha em vez de vazar | ✅ `OperationalError: no such function: empresa_atual` |

A terceira é a que mais importa: o modo de falha é *negar*, não *devolver tudo*.

---

## 6. O que muda fora do banco

| Onde | O que muda | Peso |
|---|---|---|
| `integracoes/gmail.py` + `atendimento/poller.py` | Hoje o sistema vigia **uma** caixa do Gmail, com **um** `token.json`. Cada empresa tem a caixa dela → uma credencial OAuth por empresa. | **Alto** — provavelmente o item mais trabalhoso de todos |
| `webapp/app.py` | `session["empresa_id"]` junto do `usuario_id`; toda rota `/api/*` filtra por ele | Médio |
| `portal/app.py` | O cliente já pertence a uma empresa via `cliente.empresa_id`; a sessão herda daí | Baixo |
| `PORTAL_URL_BASE` | Hoje é um endereço só. Com várias empresas: `smith.portal.com`, com a marca de cada uma | Médio |
| `core/db/views.sql` | As 4 views passam a filtrar por `empresa_atual()` | Baixo |
| `integracoes/shooting_house.py` | `SHOOTING_HOUSE_USER`/`PASSWORD` viram credencial por empresa, não do `.env` global | Médio |
| `motor_ia/*` | **Nada**, se a proposta da seção 5 for adotada | Nenhum |

### Gerador de ID: manter global

Os IDs são gerados com `MAX(CAST(SUBSTR(id, N) AS INTEGER)) + 1`, reimplementado em 5 módulos. **Proposta: manter a numeração global**, não por empresa.

Ficaria estranho o `CAS-000001` da Smith e o `CAS-000002` de outra empresa? Fica. Mas numerar por empresa exige `WHERE empresa_id = ?` em todos os 5 lugares e abre risco de duas empresas gerarem o mesmo ID ao mesmo tempo. Estranho é melhor que colidido.

---

## 7. Decisões tomadas — 2026-07-28

### 7.1 O Domínio passa a ter duas naturezas explícitas ✅

O pacote de Domínio hoje junta coisas de natureza diferente. A separação fica assim:

| Tabela | Natureza | `empresa_id`? |
|---|---|---|
| `conhecimento` | O Decreto nº 11.615/2023 é **a mesma lei para todo despachante de clube de tiro** | **Não** — compartilhado entre todas as empresas do domínio |
| `campeonato` | Calendário de provas **de uma empresa específica** | **Sim** |
| `resultado_campeonato` | Classificação das provas dessa empresa | **Sim** |

**Por que não mover `campeonato` para o Core** (opção considerada e descartada): o `PROJETO_1.md` §7 (Fase 5) define como teste de sucesso "validar que o Core funciona sem nenhuma referência hardcoded ao domínio de clube de tiro". Um escritório de advocacia nunca terá um campeonato — colocar essa tabela no Core faria a validação da Fase 5 falhar por construção, e é justamente a pureza do Core que sustenta a tese de produto multi-domínio.

**O padrão que isso estabelece para domínios futuros:** todo pacote de Domínio pode ter as duas áreas.

| Domínio | Conhecimento (compartilhado) | Dado operacional (por empresa) |
|---|---|---|
| `clube_tiro` | Legislação de CR/CRAF, habitualidade | `campeonato`, `resultado_campeonato` |
| `advocacia` (futuro) | Prazos processuais, ritos | `audiencia`, `peticao` |

### 7.2 Implementar em SQLite agora, PostgreSQL depois ✅

O desenho de schema deste documento é idêntico nos dois caminhos — só muda o mecanismo de enforcement. Com a proposta da seção 5 (views que se filtram sozinhas), nada do trabalho é jogado fora: quando o PostgreSQL entrar, `empresa_atual()` vira `CREATE POLICY` nativa.

### 7.3 Um domínio por empresa ✅

`empresa.dominio` é campo único. Um despachante que atendesse clube de tiro **e** veículos teria duas linhas em `empresa`. Mais simples agora, e evolui para vários domínios depois sem migração dolorosa.

---

## 8. Plano de migração

Como você lembrou, os 23 clientes são fictícios (`core/db/gerar_clientes_ficticios.py`) — o que **simplifica muito** esta etapa. O SQLite não permite alterar uma constraint `UNIQUE` sem recriar a tabela e copiar os dados; com dado descartável, não precisamos desse cuidado cirúrgico.

1. Atualizar `core/db/schema.sql` com `empresa` + `empresa_id` nas 18 tabelas + as 5 `UNIQUE` compostas
2. Atualizar `core/db/views.sql` com o filtro `empresa_atual()`
3. Recriar o banco do zero e repopular (`migrate_dados_teste` → `gerar_clientes_ficticios` → `popular_documentos_exigidos`), tudo sob `EMP-000001`
4. Ajustar `core/conexao.py` e os motores do Core para propagar `empresa_id`
5. Ajustar `webapp/` e `portal/` (sessão + filtros diretos)
6. **Ampliar `tests/` com um segundo tenant** — cliente da empresa A tentando alcançar dado da empresa B, no mesmo espírito dos testes de cliente que já existem
7. Rodar a suíte inteira: os 26 testes atuais precisam continuar verdes

O passo 6 não é opcional. Foi exatamente esse tipo de teste que provou, por mutação, que o isolamento entre clientes funciona — e o isolamento entre empresas é o mesmo problema, uma camada acima.

### Estado da implementação — 2026-07-28

> ⚠️ **O sistema não roda enquanto esta tabela tiver linha pendente.** O schema já mudou, mas `webapp/` e `portal/` ainda não passam `empresa_id` — subir o painel agora dá erro. Isso é esperado no meio do refactor; cada commit é um bloco coerente.

| Etapa | Estado | Commit |
|---|---|---|
| `core/db/schema.sql` + as 5 UNIQUE compostas | ✅ | `4e1e1cf` |
| `core/db/views.sql` com `empresa_atual()` | ✅ | `4e1e1cf` |
| Schema do Domínio (duas naturezas) | ✅ | `4e1e1cf` |
| `core/*.py` — 13 módulos | ✅ | `0563d8b` |
| `motor_ia/*.py` — 8 módulos | ✅ | `0563d8b` |
| `domain/clube_tiro/motor_*.py` | ✅ | `f6d0548` |
| `core/motor_empresas.py` (tabela `empresa`) | ✅ | |
| Scripts de dados do Core e do Domínio | ✅ | |
| Recriar o banco sob `EMP-000001` | ✅ | |
| **`atendimento/` (processar, poller, webhook)** | ⬜ **próximo** | |
| `webapp/app.py` (906 linhas) e `portal/app.py` (656) | ⬜ | |
| Testes de isolamento entre empresas | ⬜ | |
| Suíte inteira verde | ⬜ (hoje: 3 passam, 3 falham, 20 erram — `tests/conftest.py` monta o banco sem `empresa_id`) | |

**Backups pré-migração** (fora do git, `*.db` é ignorado):
`core/db/backup_pre_multitenant_20260728.db` e `domain/clube_tiro/db/backup_pre_multitenant_20260728.db`, mais os `backup_20260728_0104*.db` que o próprio `criar_banco --recriar` guardou na hora de recriar.

**Dois achados do refactor que valem registro:**

1. `motor_ia/identificador_cliente.py` era o ponto mais perigoso — é onde o poller entrega o e-mail de quem escreveu, e a busca por nome usa `LIKE`. Sem filtro por empresa, um remetente que fosse cliente de outro despachante seria identificado como cliente desta.
2. `core/configuracoes.py` tinha o caminho do banco hardcoded, ignorando `ERP_CORE_DB` — lia o banco real mesmo durante os testes. Corrigido junto.

### Dado real que não é fictício

`CLI-000001` é o próprio usuário, e as 7 linhas de `mensagem` + 117 de `log_ia` vieram de testes por e-mail de verdade. Não é dado de cliente de terceiro, mas é histórico real de uso — vale exportar antes de recriar o banco, se você quiser preservar.

**O que o banco recriado perdeu (2026-07-28):** ele nasceu só do que os scripts de dados sabem produzir, então o que tinha se acumulado pelo uso ficou para trás — 117 linhas de `log_ia`, 39 de `memoria_ia`, 17 de `historico`, 7 `portal_token`, 5 de `mensagem` (das 7, sobraram as 2 que a migração da planilha recria) e 9 casos criados pelo painel. Está tudo em `core/db/backup_20260728_010417.db`, de onde dá para reimportar se algum dia fizer falta. O `senha_hash` dos usuários também sumiu junto: quando o painel voltar a subir, rodar `webapp/definir_senha.py` de novo.

### Terceiro achado do refactor

Os scripts de dados usavam `INSERT INTO tabela VALUES (?,?,?…)` posicional, e isso já tinha quebrado em silêncio antes do multi-tenant: `usuario.senha_hash` e `documento.mensagem_id` entraram no schema depois e deixaram `migrate_dados_teste.py` desatualizado sem ninguém perceber (ele só quebraria no dia em que alguém recriasse o banco). Todos os INSERTs dos scripts agora listam as colunas pelo nome — acrescentar coluna ao schema deixa de ser um problema silencioso.

### A prova de que funciona

Antes de recriar o banco de verdade, a sequência inteira rodou contra um banco descartável com **duas** empresas — a Smith e uma concorrente fictícia. As três propriedades que interessam se confirmaram nos scripts reais, não em SQL de laboratório:

| O que se esperava | Resultado |
|---|---|
| Cada empresa vê só o dado dela pelas views | ✅ `VW_CLIENTE` devolveu 23 para uma e 20 para a outra, com 43 linhas cruas na tabela |
| O mesmo CPF pode ser cliente das duas | ✅ 20 CPFs repetidos entre empresas, nenhum erro de `UNIQUE` |
| Conexão sem empresa não vaza | ✅ `no such function: empresa_atual` |

---

## 9. O que este documento deliberadamente NÃO cobre

Fica para depois, e de propósito — são problemas diferentes que costumam ser confundidos com multi-tenancy:

- **Papéis e permissões** (`usuario.papel` hoje é texto livre e ninguém consulta). É a Fase 6 também, mas é outra decisão: separa *o que cada pessoa pode fazer* de *que dado a empresa dela enxerga*.
- **Billing / assinatura** — depende de `log_ia.empresa_id` existir primeiro
- **Deploy e hospedagem** — hoje `127.0.0.1` (ver `project_portal_hospedagem_decisao`)
- **Onboarding de nova empresa** (tela de cadastro, configuração inicial, serviços padrão)
