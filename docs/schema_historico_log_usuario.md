# Schema Core — Histórico, Log_IA e Usuário (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: **diferente das rodadas anteriores** — essas 3 entidades não têm aba própria na planilha (não existe `Historico`, `Log` ou `Usuarios` entre as 25 abas). Elas são citadas em `91_Padrao_IDs` (prefixo e descrição), `92_Matriz_Dependencias` (linha "Auditoria IA"), `95_Regras_Casos` (RCA-007) e `96_Relacionamentos_Casos`, mas os **campos** são uma proposta minha a partir dessas pistas, não uma cópia direta de planilha. Merece sua atenção redobrada nessa rodada.

---

## Tabela `usuario`

Fonte: `91_Padrao_IDs` ("Usuário interno do ERP") + uso em `caso.responsavel_id` e `caso.equipe_responsavel`.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `usuario_id` | TEXT | Sim | PK | Formato `USR-000001`. |
| `nome` | TEXT | Sim | — | |
| `email` | TEXT | Sim | UNIQUE | Usado para login futuramente (Fase 6). |
| `papel` | TEXT | Sim | — | Texto livre por enquanto (ex.: Despachante, Atendimento, Gestor, Administrador). |
| `equipe` | TEXT | Não | — | Ex.: "Despachante" — o mesmo valor que já víamos em `caso.equipe_responsavel`. |
| `ativo` | TEXT | Sim | — | Default `Sim`. Regra da planilha: "reatribuir antes de inativar usuário" (`96_Relacionamentos_Casos`) — ou seja, nunca excluir usuário com casos em aberto. |
| `criado_em` | TEXT (ISO 8601) | Sim | — | |

Fica bem mínimo de propósito — login, senha e permissões de verdade são Fase 6 (Produto) no PROJETO_1.md, não agora.

---

## Tabela `historico`

Fonte: `95_Regras_Casos` (RCA-007: "toda troca de responsável gera registro no histórico") + `96_Relacionamentos_Casos` ("todo evento do caso deve apontar para o caso"; "nunca excluir") + `91_Padrao_IDs` ("evento imutável do processo").

É um **log de eventos append-only**: só se insere linha nova, nunca se atualiza ou apaga uma já existente — é o registro de auditoria de tudo que aconteceu com um Caso.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `historico_id` | TEXT | Sim | PK | Formato `HIS-000001`. |
| `caso_id` | TEXT | Sim | FK → `caso.caso_id` | Todo evento aponta para um caso (regra da planilha). |
| `tipo_evento` | TEXT | Sim | — | Ex.: `criacao`, `mudanca_status`, `troca_responsavel`, `encerramento`. |
| `descricao` | TEXT | Não | — | Frase legível do que aconteceu. |
| `valor_anterior` | TEXT | Não | — | Ex.: status antigo. |
| `valor_novo` | TEXT | Não | — | Ex.: status novo. |
| `criado_em` | TEXT (ISO 8601) | Sim | — | |
| `criado_por` | TEXT | Sim | — | Texto livre (Sistema/Make/Atendimento), mesmo padrão de `caso.criado_por`. |

---

## Tabela `log_ia`

Fonte: `92_Matriz_Dependencias`, linha "Auditoria IA": consome de `Logs_IA` os campos **prompt; modelo; tokens; resultado; erro**, com a observação "cada execução relevante gera log".

Esse log é técnico — cada vez que o Motor IA chama a OpenAI, gera uma linha aqui. Diferente do `historico` (eventos de negócio do caso).

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `log_id` | TEXT | Sim | PK | Formato `LOG-000001`. |
| `caso_id` | TEXT | Não | FK → `caso.caso_id` | Opcional — o Classificador pode rodar antes de existir caso. |
| `sessao_id` | TEXT | Não | FK → `sessao.sessao_id` | |
| `prompt_key` | TEXT | Sim | — | Qual prompt rodou (ex.: `CLASSIFICADOR`) — mesma chave de `21_Prompts.prompt_key`. |
| `modelo` | TEXT | Sim | — | Ex.: `gpt-5-mini`. |
| `tokens_entrada` | INTEGER | Não | — | |
| `tokens_saida` | INTEGER | Não | — | |
| `tempo_processamento_ms` | INTEGER | Não | — | |
| `resultado` | TEXT | Sim | — | `Sucesso` / `Erro`. |
| `erro` | TEXT | Não | — | Mensagem de erro, se houver. |
| `criado_em` | TEXT (ISO 8601) | Sim | — | |

---

## Fechando 4 pendências antigas

Em rodadas anteriores, deixei `caso.responsavel_id`, `processo.responsavel`, `documento.revisado_por` e `sessao.responsavel` como texto livre, prometendo virar chave estrangeira de verdade "quando desenhássemos `usuario`". Chegou a hora. Proposta:

| Tabela | Campo hoje | Vira |
|---|---|---|
| `caso` | `responsavel_id` (texto livre) | FK → `usuario.usuario_id` |
| `processo` | `responsavel` (texto livre) | renomeado para `responsavel_id`, FK → `usuario.usuario_id` |
| `documento` | `revisado_por` (texto livre) | renomeado para `revisado_por_id`, FK → `usuario.usuario_id` |
| `sessao` | `responsavel` (texto livre) | renomeado para `responsavel_id`, FK → `usuario.usuario_id` |

**Atenção**: isso muda o significado do campo — antes aceitava qualquer nome digitado (`"Felipe"`), agora vai exigir o `usuario_id` cadastrado (`USR-000001`). Como ainda não migramos dado real nenhum, não tem perda — mas quero sua confirmação porque é uma mudança de comportamento, não só uma adição.

Se preferir, podemos deixar esses 4 campos como estão (texto livre) por mais um tempo e só travar quando a tabela `usuario` tiver uso de verdade (ex.: quando o login existir). Me diga qual dos dois caminhos prefere.

---

## Decisões finais (você pediu para eu ajustar como achasse melhor)

1. As 3 tabelas (usuario, historico, log_ia) ficam como descritas acima.
2. Os 4 campos "responsável" viram chave estrangeira de verdade para `usuario` agora (conforme confirmado).
3. **Dois ajustes extras que fiz, por consistência com o resto do banco** (mesma lógica das travas que já colocamos em `documento` e `memoria_ia` — sempre que o valor é gerado pelo sistema, não digitado por uma pessoa, vale travar):
   - `log_ia.resultado` ganha `CHECK` limitando a `'Sucesso'` ou `'Erro'` — é a IA que grava esse valor, não uma pessoa, então não faz sentido aceitar qualquer texto.
   - `historico.tipo_evento` ganha `CHECK` limitando a uma lista curta (`criacao`, `mudanca_status`, `troca_responsavel`, `encerramento`, `outro`) — mesma lógica, e `outro` funciona como válvula de escape.
   - `papel` do usuário e `equipe` continuam texto livre — esses sim são digitados por gente, então mantive a mesma linha do resto do projeto (`status` do cliente, `categoria` do caso).
