# Schema Core — Processo e Serviço (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: planilha `Banco de Dados - Clube de Tiro.xlsx`, abas `01_Servicos`, `04_Processos`, `90_Dicionario_Dados`, `96_Relacionamentos_Casos`.

---

## Tabela `servico`

Baseada em `01_Servicos`. Essa aba tem **19 colunas**, mas boa parte é texto repetido — dei uma limpada e explico o porquê abaixo.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `service_id` | TEXT | Sim | PK | Formato `SER-000001` (padrão de 6 dígitos, geração controlada — não é automática, conforme `91_Padrao_IDs`). |
| `service_key` | TEXT | Sim | UNIQUE | Chave técnica em minúsculas (ex.: `renovacao_cr`), usada pelo código e pela IA. |
| `nome_servico` | TEXT | Sim | — | Nome curto (ex.: "Renovação do CR"). |
| `descricao` | TEXT | Não | — | Frase explicativa (ex.: "Renovação do Certificado de Registro."). |
| `categoria` | TEXT | Sim | — | **Proposta: reaproveitar a mesma lista de categoria do Caso** (Regularização documental, Aquisição, Transferência, Habitualidade, CRAF, Consulta, Reclamação, Outros), em vez de inventar uma lista nova. Faz sentido: um Serviço pertence à mesma família de assunto que um Caso. |
| `prazo_estimado_dias` | INTEGER | Não | — | Número puro (ex.: `45`), não texto. |
| `valor_referencia` | REAL | Não | — | **Proposta: número puro** (ex.: `850.00`), não texto `"R$ 850,00"`. O Redator (IA) formata na hora de responder; guardar como número evita erro de cálculo e duplicação. |
| `documentos_obrigatorios` | TEXT | Sim | — | Lista de documentos separados por `;`. A planilha tinha duas colunas quase iguais (`documentos_necessarios` e `documentos_obrigatorios`) — **proposta: manter só uma**, igual fizemos com o CPF do cliente. |
| `ativo` | TEXT | Sim | — | `Sim`/`Não`, texto livre por enquanto (mesmo padrão do resto do projeto). |
| `observacoes` | TEXT | Não | — | Texto livre administrativo. |

### O que eu tirei da tabela (e por quê)

A aba original também tinha: `mensagem_padrao`, `prazo_texto`, `valor_texto`, `resposta_sem_processo`, `resposta_em_analise`, `resposta_documento_pendente`, `resposta_concluido`.

Reparei que **esses textos são idênticos nas 3 linhas de exemplo** (ex.: "Documentação pendente." aparece igual no serviço 1, 2 e 3). Isso é um sinal de que eles não variam por serviço — são frases genéricas de resposta, não dados do serviço em si. Se guardarmos duplicado em cada linha de serviço, e um dia precisar mudar o texto padrão, você teria que editar linha por linha — e é fácil esquecer uma e ficar inconsistente.

**Proposta**: deixar esses 7 campos de fora da tabela `servico` por enquanto. Eles pertencem ao conceito de **Templates** que o próprio PROJETO_1.md já prevê no Core, e que a planilha já começou a versionar em `21_Prompts`. Quando chegarmos nessa tabela, o Redator monta a frase combinando `prazo_estimado_dias`/`valor_referencia` (dados) com um template genérico (texto) — sem repetir texto em cada serviço.

Se algum desses textos varia de verdade por serviço (não é genérico), me avisa que eu volto atrás.

---

## Tabela `processo`

Baseada em `04_Processos` + `96_Relacionamentos_Casos`.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `processo_id` | TEXT | Sim | PK | Formato `PRO-000001`. |
| `caso_id` | TEXT | Sim | FK → `caso.caso_id` | **Campo novo — não existe na aba `04_Processos` atual.** Sua própria planilha (`96_Relacionamentos_Casos`, linha `Processos.caso_id → Casos.caso_id`) já define que "todo processo operacional deve pertencer a um caso". A aba de Processos foi criada antes de Casos existir, então ficou pra trás. Vou adicionar esse campo agora. |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | Mantido também aqui (não só via caso) para facilitar consultas diretas — mas deve **sempre ser o mesmo cliente do caso vinculado**. |
| `servico_id` | TEXT | Sim | FK → `servico.service_id` | |
| `protocolo` | TEXT | Não | — | Número externo/interno; só preenchido quando existir de verdade. |
| `status` | TEXT | Sim | — | A IA nunca altera este campo (regra confirmada em `92_Matriz_Dependencias`). |
| `data_abertura` | TEXT (ISO 8601) | Sim | — | |
| `prazo_estimado` | TEXT (ISO 8601) | Não | — | Data prevista de conclusão deste processo específico. |
| `proxima_acao` | TEXT | Não | — | A IA só informa o que já está cadastrado aqui, nunca inventa. |
| `responsavel` | TEXT | Não | — | Texto livre por enquanto (mesma decisão pendente do `responsavel_id` do Caso — vira FK de verdade quando desenharmos `usuario`). |
| `ultima_atualizacao` | TEXT (ISO 8601) | Sim | — | |
| `observacoes` | TEXT | Não | — | |

### O que eu tirei da tabela (e por quê)

Removi `tipo_servico` (ex.: "Renovação do CR"). Esse valor é **igual ao `nome_servico`** do serviço vinculado — se eu preciso saber o tipo, busco em `servico` pelo `servico_id`. Guardar os dois seria repetir a mesma informação em dois lugares, e se o nome do serviço mudar um dia, o processo antigo ficaria com o nome desatualizado.

---

## Resumo das propostas desta rodada

1. `servico.categoria` reaproveita a lista de `caso.categoria`.
2. `servico.valor_referencia` vira número (`850.00`), não texto formatado.
3. `servico.documentos_obrigatorios`/`documentos_necessarios` viram um campo só.
4. Os 7 campos de resposta/template pronta saem de `servico` — ficam para uma futura tabela `template`.
5. `processo.caso_id` é adicionado como campo novo obrigatório (não existia na planilha).
6. `processo.tipo_servico` é removido (redundante com `servico.nome_servico`).
7. `processo.responsavel` fica texto livre por enquanto, mesma lógica do `caso.responsavel_id`.
