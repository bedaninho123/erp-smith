# Schema Core — Cliente e Caso (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda. Este documento existe só para revisarmos campo a campo antes de eu criar qualquer tabela.
> Fonte: planilha `Banco de Dados - Clube de Tiro.xlsx`, abas `02_Clientes`, `90_Dicionario_Dados`, `91_Padrao_IDs`, `94_Contrato_Casos`, `95_Regras_Casos`, `96_Relacionamentos_Casos`.
> Decisões já confirmadas: ID com 6 dígitos (`CLI-000001`), datas em texto ISO 8601 (`2026-07-17T22:15:29Z`).

## Como ler este documento

- **PK** (chave primária) = o campo que identifica o registro de forma única. Não se repete, não muda.
- **FK** (chave estrangeira) = um campo que aponta para o ID de outra tabela (ex.: `cliente_id` dentro de Caso aponta para a tabela Cliente).
- **NOT NULL** = campo obrigatório, não pode ficar vazio.
- Tipo `TEXT`, `INTEGER`, `REAL` são os tipos que o SQLite entende. Datas guardamos como `TEXT` no formato ISO 8601 (decisão já tomada).

---

## Tabela `cliente`

Baseada na aba `02_Clientes` + entradas de `Clientes` em `90_Dicionario_Dados`.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `cliente_id` | TEXT | Sim | PK | Formato `CLI-000001`. Gerado pelo sistema, nunca reutilizado nem alterado (regra do dicionário). |
| `nome` | TEXT | Sim | — | Nome completo, fonte oficial do cadastro. |
| `cpf` | TEXT | Sim | UNIQUE | **Decidido**: uma única coluna, só os 11 dígitos, sem pontuação. Formatação (`123.456.789-00`) é feita na hora de exibir, nunca guardada. |
| `email` | TEXT | Não | — | Usado para identificar cliente em e-mails recebidos e para respostas. |
| `telefone` | TEXT | Não | — | Formato livre hoje (`5514999990001`). Sugiro manter só dígitos com DDI. |
| `cidade` | TEXT | Não | — | |
| `status` | TEXT | Sim | — | Ex.: `Ativo`, `Inativo`. **Decidido: texto livre por enquanto**, sem trava. Podemos adicionar uma lista controlada depois sem quebrar nada. |
| `atendimento_ia` | TEXT | Sim | — | `Sim`/`Não` — se esse cliente pode ser atendido pela IA ou exige humano sempre. Texto livre por enquanto, mesma decisão acima. |
| `data_cadastro` | TEXT (ISO 8601) | Sim | — | Preenchido na criação, imutável. |
| `ultima_interacao` | TEXT (ISO 8601) | Não | — | Atualizado a cada nova conversa. |
| `observacoes` | TEXT | Não | — | Texto livre administrativo. |

### Decisões tomadas (Cliente) — 2026-07-22
1. **CPF**: uma coluna só, 11 dígitos sem pontuação. ✅
2. **`status` / `atendimento_ia`**: texto livre por enquanto, sem `CHECK` nem tabela de lista. Podemos travar mais tarde. ✅

---

## Tabela `caso`

Baseada inteiramente em `94_Contrato_Casos` (25 campos, já com regra de negócio definida) + `95_Regras_Casos` + `96_Relacionamentos_Casos`.

| # | Campo | Tipo | Obrigatório | Chave | Regra de negócio (fonte: planilha) |
|---|---|---|---|---|---|
| 1 | `caso_id` | TEXT | Sim | PK | Formato `CAS-000001`; nunca reutilizar (RCA-002: imutável após criação). |
| 2 | `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | Cliente deve existir antes do caso (RCA-001, bloqueia gravação se não existir). |
| 3 | `titulo` | TEXT | Sim | — | Deve resumir **um único objetivo** (RCA-010: demandas independentes viram casos separados). |
| 4 | `descricao` | TEXT | Não | — | Não substitui histórico nem observações de processo. |
| 5 | `categoria` | TEXT | Sim | — | Lista padronizada — **proposta inicial abaixo**, ainda não existia na planilha. |
| 6 | `tipo_caso` | TEXT | Sim | — | Lista controlada: `Solicitação`, `Dúvida`, `Regularização`, `Acompanhamento`, `Incidente`, `Reclamação`. |
| 7 | `origem` | TEXT | Sim | — | Lista controlada: `Atendimento`, `Indicação`, `Campanha`, `Importação`, `Portal`, `Integração`. |
| 8 | `canal_origem` | TEXT | Sim | — | Canal onde o caso nasceu; **não muda** mesmo se o cliente trocar de canal depois. |
| 9 | `status` | TEXT | Sim | — | Ciclo de vida oficial (`Listas_Casos`): Aberto, Em triagem, Em andamento, Aguardando cliente, Aguardando terceiro, Suspenso, Encerrado, Cancelado. Só pode ser um desses (RCA-003). |
| 10 | `fase` | TEXT | Não | — | Triagem, Diagnóstico, Documentação, Execução, Acompanhamento, Conclusão. |
| 11 | `prioridade` | TEXT | Sim | — | Baixa, Normal, Alta, Urgente. `Urgente` exige justificativa registrada (RCA-006). |
| 12 | `responsavel_id` | TEXT | Não | FK → `usuario.usuario_id` | Toda troca de responsável gera histórico (RCA-007). *(tabela `usuario` ainda não desenhada — Fase 1 mais à frente)* |
| 13 | `equipe_responsavel` | TEXT | Não | — | Lista padronizada de equipes. |
| 14 | `sessao_principal_id` | TEXT | Não | FK → `sessao.sessao_id` | Pode mudar conforme o atendimento evolui. |
| 15 | `memoria_id` | TEXT | Não | FK → `memoria_ia.memoria_id` | Pertence ao cliente, mas referenciada pelo caso. |
| 16 | `criado_em` | TEXT (ISO 8601) | Sim | — | Preenchimento automático, imutável. |
| 17 | `atualizado_em` | TEXT (ISO 8601) | Sim | — | Atualiza em qualquer mudança de estado relevante. |
| 18 | `prazo_previsto` | TEXT (ISO 8601, só data) | Não | — | Prazo geral do caso (não confundir com prazo de um processo específico). |
| 19 | `encerrado_em` | TEXT (ISO 8601) | Não | — | Só preenche se status for Encerrado/Cancelado (RCA-004). |
| 20 | `criado_por` | TEXT | Sim | — | Valores padronizados: `Sistema`, `Make`, `Atendimento`, `Importação`. |
| 21 | `alterado_por` | TEXT | Sim | — | Atualiza junto com `atualizado_em`. |
| 22 | `versao` | INTEGER | Sim | — | Incrementa a cada alteração relevante (RCA-008). |
| 23 | `ativo` | TEXT (`Sim`/`Não`) | Sim | — | Nunca excluir fisicamente um caso em uso; inativar (RCA-005). |
| 24 | `motivo_encerramento` | TEXT | Não | — | Obrigatório quando status = Encerrado/Cancelado (RCA-004). |
| 25 | `observacoes` | TEXT | Não | — | Administrativo geral. |

### Regra importante que vem do `95_Regras_Casos`
**RCA-009 — a IA nunca encerra, cancela ou muda prioridade de um caso diretamente.** Isso confirma o princípio do PROJETO_1.md ("IA nunca contém regra de negócio") e vai virar uma trava no código do Core, não um comentário — o Motor IA só pode *sugerir* essas mudanças, quem executa é o Core.

### Decisões e proposta (Caso) — 2026-07-22

1. **`categoria` — proposta inicial**, baseada nos domínios de negócio já citados no PROJETO_1.md (CR, CRAF, Transferência, Habitualidade, Aquisição, Guias) e nas categorias que aparecem em `01_Servicos`:
   - `Regularização documental` (renovação/emissão de CR, apostilamento)
   - `Aquisição` (compra de arma/equipamento, guias de aquisição)
   - `Transferência` (transferência de propriedade de arma)
   - `Habitualidade` (comprovação de prática/habitualidade)
   - `CRAF` (cadastro/registro de arma de fogo)
   - `Consulta` (dúvida geral, sem processo formal aberto)
   - `Reclamação` (insatisfação do cliente)
   - `Outros` (o que não se encaixar — válvula de escape controlada)

   Isso é uma lista inicial e curta de propósito — dá pra crescer depois sem migração dolorosa, porque vamos implementar como lista simples (texto livre por enquanto, igual `status` do cliente), não como tabela travada. Se quiser ajustar algum nome ou adicionar/remover categoria, é só falar.

2. **`responsavel_id` / `equipe_responsavel`**: **fica pendente**, como combinado. No SQLite eles entram como colunas `TEXT` simples, sem `FOREIGN KEY` de verdade — funcionam para guardar o valor, mas o banco não vai validar se o usuário existe (isso é adicionado quando desenhar mos a tabela `usuario`, sem precisar alterar dados já gravados).
3. **IDs de teste com 3 dígitos → 6 dígitos**: confirmado, serão convertidos na migração (ex.: `CLI-001` → `CLI-000001`). Como você mesmo confirmou que são só dados fictícios de teste, não há dado real de cliente em risco.
