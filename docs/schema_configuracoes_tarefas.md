# Schema Core — Configurações e Tarefas (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: `20_Configuracoes`, `07_Tarefas`, `96_Relacionamentos_Casos`.

---

## Tabela `configuracoes`

Baseada em `20_Configuracoes` — a mais limpa das abas até agora: 28 linhas, todas com dado real e coerente. Só um problema pequeno.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `config_id` | TEXT | Sim | PK | Formato `CFG-000001`. |
| `chave` | TEXT | Sim | UNIQUE | Ex.: `nome_empresa`, `modelo_openai`. |
| `valor` | TEXT | Sim | — | Guardado como texto sempre, mesmo quando é número (ex.: `"0.2"`, `"1200"`) — quem lê decide como interpretar. |
| `categoria` | TEXT | Sim | — | Ex.: `empresa`, `ia`, `contato`, `atendimento`, `mensagens`, `sistema`. |
| `descricao` | TEXT | Não | — | |
| `ativo` | TEXT | Sim | — | Default `Sim`. |

### O problema encontrado
Duas chaves aparecem **duplicadas** com `config_id` diferente: `permitir_valores_referencia` (CFG-019 **e** CFG-023) e `permitir_prazos_referencia` (CFG-020 **e** CFG-024) — mesmo valor, mesma descrição, só repetido. Vou migrar cada chave **uma única vez** (a trava `UNIQUE` em `chave` vai barrar a segunda tentativa de qualquer forma).

---

## Tabela `tarefas`

Baseada em `07_Tarefas` + `96_Relacionamentos_Casos` ("toda tarefa de atendimento deve pertencer a um caso").

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `tarefa_id` | TEXT | Sim | PK | Formato `TAR-000001`. |
| `caso_id` | TEXT | Sim | FK → `caso.caso_id` | **Campo novo** — mesma situação de `processo.caso_id`: não existia na planilha, mas a regra de relacionamento exige. Nos 2 registros reais, dá pra descobrir o caso certo via o `processo_id` já preenchido. |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | |
| `processo_id` | TEXT | Não | FK → `processo.processo_id` | Opcional — pode existir tarefa do caso que não é de um processo específico. |
| `tipo` | TEXT | Sim | — | Ex.: `Cobrar documento`, `Consultar andamento`. |
| `descricao` | TEXT | Não | — | |
| `responsavel_id` | TEXT | Não | FK → `usuario.usuario_id` | Já nasce FK, como fizemos em `mensagem` — `usuario` já existe. |
| `prazo` | TEXT (ISO 8601) | Não | — | |
| `prioridade` | TEXT | Sim | — | Mesma lista de `caso.prioridade` (Baixa/Normal/Alta/Urgente). |
| `status` | TEXT | Sim | — | Ex.: `Pendente`, `Concluída`. |
| `data_conclusao` | TEXT (ISO 8601) | Não | — | |
| `observacoes` | TEXT | Não | — | |

*(Sem `versao`/`ativo` — segue o padrão mais enxuto de `processo`/`documento`, não o de `caso`.)*

## Resumo das propostas

1. `configuracoes`: migrar as 26 chaves únicas (28 linhas menos 2 duplicadas).
2. `tarefas.caso_id`: campo novo, preenchido por inferência via `processo_id` nos 2 registros reais (`TAR-001`→`CAS-000002`, `TAR-002`→`CAS-000001`).
3. IDs de cliente/processo nos 2 registros de tarefa convertidos de 3 para 6 dígitos, mesmo padrão de sempre.
