# Schema Core — Memória_IA (rascunho para revisão)

> Status: RASCUNHO — nada foi criado no banco ainda.
> Fonte: planilha `Banco de Dados - Clube de Tiro.xlsx`, aba `09_Memoria_IA`, e `96_Relacionamentos_Casos`.

Essa é a última tabela do "corredor principal" Cliente → Caso → ... → Sessão → Memória que o PROJETO_1.md descreve. Depois dela, seguimos para Histórico, Log e Usuário.

---

## Tabela `memoria_ia`

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `memoria_id` | TEXT | Sim | PK | Formato `MEM-000001`. *(Mesma observação de Sessão: não está em `91_Padrao_IDs`, mas os dados já seguem o padrão de 6 dígitos.)* |
| `cliente_id` | TEXT | Sim | FK → `cliente.cliente_id` | |
| `resumo_cliente` | TEXT | Não | — | Resumo em linguagem natural do relacionamento com o cliente. |
| `assuntos_recentes` | TEXT | Não | — | Lista em texto (ex.: "Renovação do CR; consulta de documentos"). |
| `servicos_recentes` | TEXT | Não | — | Texto livre por design — ver nota abaixo. |
| `processos_recentes` | TEXT | Não | — | Texto livre por design — ver nota abaixo. |
| `ultima_intencao` | TEXT | Não | — | |
| `preferencia_canal` | TEXT | Não | — | |
| `tom_recomendado` | TEXT | Não | — | Ex.: "Profissional, claro e objetivo." |
| `informacoes_importantes` | TEXT | Não | — | Coisas que a IA deve sempre lembrar de confirmar. |
| `restricoes_atendimento` | TEXT | Não | — | Coisas que a IA nunca deve fazer com esse cliente. |
| `ultima_sessao_id` | TEXT | Não | FK → `sessao.sessao_id` | |
| `atualizada_em` | TEXT (ISO 8601) | Sim | — | |
| `atualizada_por` | TEXT | Sim | — | Texto livre (Sistema/Make/Atendimento), mesmo padrão de `caso.criado_por`. |
| `versao` | INTEGER | Sim | — | Incrementa a cada atualização, mesmo padrão de `caso.versao`. |
| `ativo` | TEXT | Sim | — | Default `Sim`. |
| `observacoes` | TEXT | Não | — | |

### Por que `servicos_recentes` e `processos_recentes` continuam texto livre

Na planilha, esses campos guardam algo como `"SER-001 - Renovação do CR"` — ID e nome juntos, texto pronto para a IA ler. Eu **não** vou transformar isso numa tabela relacional separada (tipo "memória tem muitos serviços"), porque a Memória_IA não é um registro transacional — é um resumo em linguagem natural que o próprio Motor de Memória reescreve com o tempo (o PROJETO_1.md chama isso de "resumo inteligente permanente"). Forçar estrutura rígida aqui atrapalharia mais do que ajudaria.

### Proposta: só uma memória ativa por cliente

O PROJETO_1.md descreve Memória_IA como "resumo permanente do relacionamento com o cliente" — no singular. Para isso ser garantido pelo banco (e não só por boa vontade de quem grava), proponho uma trava: **não pode haver duas linhas com `ativo = 'Sim'` para o mesmo `cliente_id`.** Quando a memória precisar mudar de forma relevante, a linha antiga vira `ativo = 'Não'` e uma nova é criada — preservando histórico, igual já fazemos com `caso.ativo`.

Se você prefere manter mais simples (sem essa trava, permitir múltiplas memórias ativas por cliente por enquanto), me avisa que eu tiro.

---

## Arrumando duas pendências antigas

Quando desenhei `caso` (primeira rodada), deixei `sessao_principal_id` e `memoria_id` como colunas soltas, sem ligação de verdade, porque as tabelas `sessao` e `memoria_ia` ainda não existiam. **Agora que as duas existem**, vou transformar essas duas colunas em chaves estrangeiras de verdade — fechando esse ciclo. Isso não muda nenhum dado, só reforça a trava no banco.
