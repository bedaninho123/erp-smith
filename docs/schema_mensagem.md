# Schema Core — Mensagem (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: `06_Mensagens`. Última tabela do Core mínimo — depois dela partimos para a Fase 2 (Motor IA).

---

## Tabela `mensagem`

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `mensagem_id` | TEXT | Sim | PK | Formato `MSG-000001`. *(Mais uma entidade ausente em `91_Padrao_IDs` — mesma observação de Sessão/Memória.)* |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | |
| `caso_id` | TEXT | Não | FK → `caso.caso_id` | |
| `conversa_id` | TEXT | Não | FK → `conversa.conversa_id` | Opcional — pode chegar antes de a conversa ser identificada. |
| `processo_id` | TEXT | Não | FK → `processo.processo_id` | |
| `canal` | TEXT | Sim | — | |
| `data_hora` | TEXT (ISO 8601) | Sim | — | |
| `origem` | TEXT | Sim | — | `Cliente` ou `Sistema`. |
| `email_remetente` | TEXT | Não | — | |
| `assunto` | TEXT | Não | — | |
| `mensagem` | TEXT | Não | — | **Corpo da mensagem — ver nota abaixo sobre por que ficou opcional.** |
| `intent` | TEXT | Não | — | Intenção classificada (ex.: `consulta_processo`). |
| `resumo_ia` | TEXT | Não | — | |
| `precisa_humano` | TEXT | Não | — | `Sim`/`Não`, texto livre. |
| `status_processamento` | TEXT | Sim | — | Ex.: `Recebido`, `Respondido`, `Enviado`. |
| `id_externo` | TEXT | Não | — | ID da mensagem no Gmail — útil pra nunca processar a mesma mensagem duas vezes. |
| `resposta_ia` | TEXT | Não | — | |
| `responsavel_id` | TEXT | Não | FK → `usuario.usuario_id` | Diferente das rodadas anteriores, já nasce como FK — `usuario` já existe, não precisa passar por "texto livre" primeiro. |
| `tempo_processamento_ms` | INTEGER | Não | — | Renomeado de `tempo_processamento`, mesmo padrão de `log_ia`. |
| `modelo_ia` | TEXT | Não | — | Ex.: `gpt-5-mini`. |
| `observacoes_ia` | TEXT | Não | — | |

### O que eu tirei
Removi `protocolo` — é uma cópia do `processo.protocolo`, já acessível via `processo_id`. Mesma lógica do `tipo_servico` que tiramos de `processo` na 2ª rodada.

---

## Os dados reais desta aba são mais bagunçados que os anteriores

`06_Mensagens` tem só 3 linhas com conteúdo, e duas delas têm problema:

1. **Linha "Teste Update Row"** — o campo `mensagem` (corpo da mensagem do cliente) contém literalmente o texto `System.Xml.XmlElement`. Isso é um bug de integração do Make (um objeto XML que não foi convertido pra texto antes de salvar) — não é o que o cliente escreveu. Só que essa linha também tem um `resumo_ia` e um `resposta_ia` completos e úteis (uma resposta formatada citando o processo PRO-001). Proposta: manter a linha (é um bom exemplo de resposta da IA), mas deixar `mensagem = NULL` em vez de guardar o texto quebrado, com uma nota em `observacoes_ia` explicando o que aconteceu. Por isso deixei `mensagem` como campo opcional na tabela — não faz sentido forçar texto num campo cujo dado de origem está corrompido.
2. **Linha "TEMP"** — mesmo problema de `mensagem`, e além disso `cliente_id` está vazio. Sem cliente, não dá nem para migrar (viola a trava do banco). Proposta: **excluir**, mesmo padrão das 47 linhas `TEMP-000001` de Casos.
3. A linha "MSG-002" (pedido de comprovante de residência) está limpa, sem problema.

### Ligações que a planilha não preencheu, mas dá para inferir com segurança

- Na linha 1, `processo_id` já apontava para `PRO-001` (→ `PRO-000001`); vou preencher `caso_id` e `conversa_id` também, porque só existe um Caso e uma Conversa no banco pra esse cliente (`CAS-000001`, `CON-000001`) — não é chute, é a única opção consistente.
- Na linha "MSG-002", `processo_id`/`caso_id` vieram vazios, mas o assunto ("Documento pendente", pedindo comprovante de residência) bate exatamente com `PRO-000002` (cujo `proxima_acao` é "Receber comprovante de residência") e `DOC-000002` (pendente, mesmo documento). Vou linkar em `PRO-000002`/`CAS-000002`.

## Resumo das propostas desta rodada

1. Tabela `mensagem` com `responsavel_id` já nascendo FK, `protocolo` removido (redundante).
2. `mensagem` (corpo do texto) fica opcional, porque um dos 2 registros reais tem esse campo corrompido na origem.
3. Excluir a linha "TEMP" (sem cliente, conteúdo corrompido).
4. Preencher `caso_id`/`conversa_id`/`processo_id` das 2 linhas reais por inferência lógica (explicada acima), já que a planilha não preencheu.
