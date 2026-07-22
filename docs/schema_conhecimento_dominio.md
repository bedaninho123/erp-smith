# Schema Domínio — Conhecimento + separação física Core/Domínio

> Status: RASCUNHO — nada foi criado ainda.
> Fonte: `92_Matriz_Dependencias` (linha "Motor de Conhecimento"), `91_Padrao_IDs` (prefixo `KNW` já definido). Não existe aba própria na planilha — mesma situação de `usuario`/`historico`/`log_ia`.

## Como separar Core de Domínio no SQLite

SQLite não tem "schema" como o Postgres, mas tem o equivalente prático: **bancos separados, conectados com `ATTACH DATABASE`**. Proposta de estrutura:

```
ERP SMITH/
├── core/db/schema.sql              (já existe)
├── core/db/erp_smith.db            (já existe)
└── domain/
    └── clube_tiro/
        └── db/
            ├── schema.sql              (novo)
            └── dominio_clube_tiro.db   (novo)
```

Quando o código precisar consultar as duas coisas juntas (ex.: Motor de Conhecimento respondendo com base em `conhecimento` + dado de `caso`), ele faz `ATTACH DATABASE 'domain/clube_tiro/db/dominio_clube_tiro.db' AS dominio;` na mesma conexão e pode fazer `JOIN` entre os dois — mas são **arquivos diferentes**, então dá pra trocar/remover o pacote de Domínio sem tocar no Core (exatamente o teste que a Fase 5 do PROJETO_1.md pede). Uma consequência técnica: o SQLite não aplica `FOREIGN KEY` entre bancos anexados — então `conhecimento` não vai ter chave estrangeira de verdade apontando pro Core. Isso combina bem com o que `conhecimento` realmente é: material de referência institucional (perguntas/respostas gerais), não dado de um cliente ou caso específico.

## Tabela `conhecimento` (domain/clube_tiro/db/schema.sql)

| Campo | Tipo | Obrigatório | Chave | Observação |
|---|---|---|---|---|
| `conhecimento_id` | TEXT | Sim | PK | Formato `KNW-000001`. |
| `categoria` | TEXT | Sim | — | Ex.: CR, CRAF, Transferência, Habitualidade, Aquisição, Guias, Legislação — o vocabulário de Domínio do PROJETO_1.md. |
| `pergunta` | TEXT | Sim | — | |
| `resposta` | TEXT | Sim | — | |
| `aprovado` | TEXT | Sim | — | `Sim`/`Não`. Regra da planilha: "conhecimento aprovado tem prioridade" — sugere que entradas não aprovadas podem existir, mas o Consultor prefere as aprovadas. |
| `ativo` | TEXT | Sim | — | Default `Sim`. |
| `criado_em` | TEXT (ISO 8601) | Sim | — | |

Sem dado real para migrar (não existe fonte na planilha) — nasce vazia, populada depois manualmente ou pelo Motor de Conhecimento.

## Resumo das propostas

1. Criar `domain/clube_tiro/db/` com `schema.sql` e banco próprios, separados do Core.
2. `conhecimento` mora lá, sem FK cruzando pra tabelas do Core.
3. Junto com isso, aplico as propostas de `configuracoes` e `tarefas` (doc anterior) no Core.
