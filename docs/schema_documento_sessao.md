# Schema Core — Documento e Sessão (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: planilha `Banco de Dados - Clube de Tiro.xlsx`, abas `05_Documentos`, `08_Sessoes`, `40_Listas_Auxiliares`, `96_Relacionamentos_Casos`.

---

## Tabela `documento`

Baseada em `05_Documentos` + `96_Relacionamentos_Casos`.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `documento_id` | TEXT | Sim | PK | Formato `DOC-000001`. |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | Mesmo padrão de `processo`: guardado aqui também pra facilitar consulta direta. |
| `caso_id` | TEXT | Não | FK → `caso.caso_id` | **Campo novo** — não existia na aba original. `96_Relacionamentos_Casos` já previa essa ligação ("documento pode ser do caso ou de um processo do caso"). |
| `processo_id` | TEXT | Não | FK → `processo.processo_id` | Preenchido só quando o documento pertence a um processo específico (não ao caso como um todo). |
| `tipo_documento` | TEXT | Sim | — | Ex.: RG, CPF, Comprovante de residência. |
| `nome_arquivo` | TEXT | Não | — | |
| `link_arquivo` | TEXT | Não | — | |
| `status` | TEXT | Sim | — | Ex.: Pendente, Aprovado. Texto livre por enquanto. |
| `data_envio` | TEXT (ISO 8601) | Não | — | |
| `data_validade` | TEXT (ISO 8601) | Não | — | |
| `revisado_por` | TEXT | Não | — | Texto livre por enquanto (mesma decisão pendente de `responsavel`). |
| `observacoes` | TEXT | Não | — | |

**Regra que vou colocar como trava no próprio banco** (não só como comentário): todo documento precisa estar ligado a pelo menos um `caso_id` **ou** `processo_id` — nunca solto sem contexto nenhum. Se tentar inserir um documento sem os dois, o banco recusa sozinho, igual fizemos com as chaves estrangeiras.

---

## Tabela `sessao`

Baseada em `08_Sessoes` + `40_Listas_Auxiliares` (listas de canal/status) + `96_Relacionamentos_Casos`.

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `sessao_id` | TEXT | Sim | PK | Formato `SES-000001`. *(Nota: essa entidade não apareceu em `91_Padrao_IDs`, mas os dados de exemplo já seguem o padrão de 6 dígitos — vale adicionar lá depois.)* |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | |
| `caso_id` | TEXT | Não | FK → `caso.caso_id` | **Campo novo.** Regra da planilha: "uma sessão pode iniciar sem caso e ser vinculada após classificação" — por isso é opcional, não obrigatório como em Processo. |
| `canal` | TEXT | Sim | — | Lista: Email, WhatsApp, Portal, Aplicativo, API. |
| `identificador_canal` | TEXT | Não | — | E-mail ou telefone, dependendo do canal. |
| `assunto_atual` | TEXT | Não | — | O que a IA está entendendo como assunto da conversa agora. |
| `ultima_intencao` | TEXT | Não | — | Última intenção classificada (ex.: `consulta_documentos`). |
| `ultimo_servico_id` | TEXT | Não | FK → `servico.service_id` | |
| `ultimo_processo_id` | TEXT | Não | FK → `processo.processo_id` | |
| `ultima_mensagem_cliente` | TEXT | Não | — | |
| `ultima_resposta_ia` | TEXT | Não | — | |
| `resumo_sessao` | TEXT | Não | — | |
| `status_sessao` | TEXT | Sim | — | Lista: Aberta, Aguardando cliente, Aguardando humano, Encerrada, Expirada. |
| `iniciada_em` | TEXT (ISO 8601) | Sim | — | |
| `ultima_interacao_em` | TEXT (ISO 8601) | Sim | — | |
| `expira_em` | TEXT (ISO 8601) | Não | — | Usado pelo futuro Motor de Sessões pra expirar sessão automaticamente. |
| `encaminhada_humano` | TEXT | Não | — | `Sim`/`Não`, texto livre. |
| `responsavel` | TEXT | Não | — | Texto livre por enquanto. |
| `conversa_id_origem` | TEXT | Não | — | Referência solta por enquanto — a tabela `conversa` ainda não foi desenhada. |
| `ativo` | TEXT | Sim | — | Default `Sim`. |
| `observacoes` | TEXT | Não | — | |

---

## Resumo das propostas desta rodada

1. `documento.caso_id` é campo novo (opcional).
2. `documento`: trava no banco exigindo `caso_id` OU `processo_id` preenchido (nunca os dois vazios).
3. `sessao.caso_id` é campo novo (opcional, por causa da regra "sessão pode começar sem caso").
4. `sessao.conversa_id_origem` fica solto por enquanto (sem FK), até desenharmos `conversa`.
5. `documento.revisado_por` e `sessao.responsavel` ficam texto livre, mesma linha do resto do projeto.
