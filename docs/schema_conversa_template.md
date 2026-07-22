# Schema Core — Conversa e Template (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: `07_Conversas` (para `conversa`) e os 7 campos que tiramos de `01_Servicos` na 2ª rodada (para `template`) + `91_Padrao_IDs`.

---

## Tabela `conversa`

Baseada em `07_Conversas`. É o "envelope" de um atendimento (uma conversa pode ter várias mensagens — a aba `06_Mensagens`, que fica para uma próxima rodada).

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `conversa_id` | TEXT | Sim | PK | Formato `CON-000001`. |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | |
| `caso_id` | TEXT | Não | FK → `caso.caso_id` | Opcional — regra da planilha: "vincular quando o assunto do atendimento for identificado". |
| `sessao_id` | TEXT | Não | FK → `sessao.sessao_id` | |
| `canal` | TEXT | Sim | — | Texto livre (a planilha usa até `Webhook`, além da lista de canal já conhecida). |
| `origem` | TEXT | Sim | — | Ex.: `Cliente`, `Sistema`. |
| `status` | TEXT | Sim | — | Ex.: `Aberta`, `Encerrada`. |
| `assunto_principal` | TEXT | Não | — | |
| `iniciada_em` | TEXT (ISO 8601) | Sim | — | |
| `ultima_mensagem_em` | TEXT (ISO 8601) | Sim | — | |
| `encerrada_em` | TEXT (ISO 8601) | Não | — | |
| `responsavel_id` | TEXT | Não | FK → `usuario.usuario_id` | Mesmo padrão dos outros "responsável" do banco. |
| `precisa_humano` | TEXT | Não | — | `Sim`/`Não`, texto livre. |
| `total_mensagens` | INTEGER | Sim | — | Default `0`; o Motor de Sessões incrementa a cada mensagem nova. |
| `criado_por` | TEXT | Sim | — | |
| `atualizado_por` | TEXT | Sim | — | |
| `versao` | INTEGER | Sim | — | Default `1`. |
| `ativo` | TEXT | Sim | — | Default `Sim`. |
| `observacoes` | TEXT | Não | — | |

### Fechando outra pendência antiga
`sessao.conversa_id_origem` estava solto ("sem FK ainda; tabela conversa pendente"). Agora vira FK de verdade → `conversa.conversa_id`.

---

## Tabela `template`

Aqui recuperamos os 7 campos que tiramos de `servico` na 2ª rodada — mas como uma tabela própria, não repetidos em cada linha de serviço.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `template_id` | TEXT | Sim | PK | Formato `TPL-000001`. |
| `template_key` | TEXT | Sim | UNIQUE | Chave técnica que o Redator usa para buscar o texto certo. |
| `nome` | TEXT | Sim | — | |
| `categoria` | TEXT | Não | — | Ex.: `processo`, `servico`. |
| `conteudo` | TEXT | Sim | — | O texto em si. Pode ter marcadores tipo `{nome_servico}` que o Redator substitui pelo dado real. |
| `canal` | TEXT | Não | — | `Email`, `WhatsApp`, ou vazio (serve para qualquer canal). |
| `ativo` | TEXT | Sim | — | Default `Sim`. |
| `observacoes` | TEXT | Não | — | |

### Como os 7 campos viram templates

Os 4 campos de resposta (`resposta_sem_processo`, `resposta_em_analise`, `resposta_documento_pendente`, `resposta_concluido`) eram **idênticos em todas as linhas de serviço** — viram 4 templates fixos, sem marcador nenhum.

Os outros 3 (`mensagem_padrao`, `prazo_texto`, `valor_texto`) tinham o nome do serviço ou um número dentro do texto (ex.: "Prazo médio de 45 dias.") — viram templates **com marcador**, que o Redator preenche combinando com o dado real de `servico.prazo_estimado_dias` etc.:

| `template_key` | `conteudo` |
|---|---|
| `resposta_sem_processo` | Não localizei processo vinculado. |
| `resposta_em_analise` | Processo em análise. |
| `resposta_documento_pendente` | Documentação pendente. |
| `resposta_concluido` | Processo concluído. |
| `mensagem_padrao_servico` | Localizei o serviço de {nome_servico}. |
| `prazo_texto_servico` | Prazo médio de {prazo_estimado_dias} dias. |
| `valor_texto_servico` | Valor de referência: R$ {valor_referencia}. |

Isso é só a estrutura — o código que efetivamente substitui `{nome_servico}` pelo valor real é do Motor IA (Fase 2 do PROJETO_1.md), não faz parte do banco.

**Nota**: isso é diferente da aba `21_Prompts`, que guarda os *prompts de instrução* que vão para a OpenAI (`CLASSIFICADOR`, `REDATOR_EMAIL` etc.) — prompt é instrução para a IA pensar; template é o texto pronto que a IA usa para responder. Vou deixar `21_Prompts` para quando começarmos o Motor IA (Fase 2), não modelar agora.

---

## Resumo das propostas desta rodada

1. `conversa` criada com `caso_id`/`sessao_id`/`responsavel_id` opcionais, seguindo o mesmo padrão de `sessao`.
2. `sessao.conversa_id_origem` vira FK de verdade agora que `conversa` existe.
3. `template` recupera os 7 campos tirados de `servico`, virando 7 linhas (4 fixas + 3 com marcador).
4. `21_Prompts` fica de fora por enquanto — é conceito diferente (instrução para IA, não texto de resposta), fica para a Fase 2.
