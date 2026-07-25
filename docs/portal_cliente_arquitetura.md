# Portal do Cliente — Rascunho de Arquitetura

> Documento de rascunho para revisão. `PROJETO_1.md` (seção 3) só menciona "Portal" como um dos canais futuros do ATENDIMENTO (junto de WhatsApp, app, API) — não existe spec detalhada, então este documento propõe uma do zero, a ser aprovada/ajustada antes de qualquer código.

## O que é diferente de tudo que já construímos

Até hoje, tudo que existe (painel admin, webhook, poller) roda em `localhost`, atrás de um login que só a Ana e o Felipe usam, tratando o sistema inteiro como confiável por padrão. O Portal do Cliente é a primeira coisa que:

1. Precisa ficar acessível de fora do computador de vocês (os clientes reais do clube vão acessar de casa).
2. Precisa de um jeito de autenticar **pessoas que não são funcionário** — hoje só existe login de `usuario` (staff).
3. Precisa isolar o dado de cada cliente do dos outros — um bug aqui vaza documento de identidade/arma de um cliente pra outro, o que é grave neste domínio regulado.

Por isso, antes de desenhar telas, este rascunho foca em 5 decisões estruturais.

---

## 1. Escopo do MVP (o que entra na primeira versão)

Proposta: começar **só leitura + upload**, sem chat com a IA.

**Entra no MVP:**
- Cliente vê os próprios casos (título, status, categoria, próxima ação) — nunca os de outro cliente.
- Cliente vê o checklist de documentos do(s) processo(s) dele (reaproveita `VW_CHECKLIST_SERVICO` + `documento_checklist`, já existem) — o que já enviou vs. o que falta.
- Cliente consegue enviar um documento direto pelo Portal (reaproveita `core/motor_documentos.py::salvar_documento()`, já existe e é agnóstico de canal — só precisa de uma rota nova que autentica como cliente em vez de staff).

**Fica de fora do MVP, de propósito** (adicionar depois, incremental):
- Chat/pergunta livre pro Motor IA pelo Portal (isso viraria um novo "canal" de verdade no `atendimento/`, reaproveitando `motor_ia/orquestrador.py::atender_mensagem()` — arquitetura já suporta, mas é escopo maior: precisa decidir sessão, rate limit de custo de IA por cliente anônimo-pra-nós-até-logar, etc.)
- Cliente editar o próprio cadastro (nome/telefone/endereço) — por ora, mudança de cadastro continua sendo o funcionário quem faz.
- Notificação push/e-mail automática pro cliente quando o status muda (fica pra quando o Portal já estiver validado).

**Por quê**: o problema real que o Portal resolve primeiro é "cliente liga/manda e-mail perguntando cadê meu documento" — isso só precisa de status + checklist, não de conversa. Reduz a primeira entrega a algo pequeno e testável, no mesmo espírito de como o resto do projeto foi construído (Core mínimo → Motor IA → Atendimento, incremental).

---

## 2. Autenticação do cliente

Cliente **não é staff** — não faz sentido reaproveitar `usuario.senha_hash`/`werkzeug.security` como está hoje (isso presume que alguém já cadastrou uma senha pra essa pessoa, e clientes de despachante em geral não são usuários tecnicamente sofisticados).

**Proposta: login sem senha, por link mágico via e-mail** (mesmo padrão usado por vários portais de atendimento):
1. Cliente digita CPF (ou e-mail) numa tela pública.
2. Sistema confere se existe em `cliente` (reaproveita `motor_ia/identificador_cliente.py`, já faz exatamente essa busca).
3. Se existir e tiver e-mail cadastrado, manda um link de acesso de uso único (token com expiração curta, ex. 15 min) pro e-mail cadastrado — reaproveita `integracoes/gmail.py::enviar_email`, já existe e já está autorizado.
4. Clicar no link cria uma sessão de cliente (cookie separado da sessão de staff), válida por um tempo (ex. 12h) ou até logout.

**Vantagens**: zero senha pra gerenciar/recuperar (grande redução de superfície de suporte e de risco — nada de "esqueci minha senha" nem senha fraca reaproveitada); usa infraestrutura de e-mail que já existe e já foi testada; nunca expõe se um CPF existe ou não de forma que dê pra enumerar clientes (mensagem de resposta é sempre genérica tipo "se esse CPF estiver cadastrado, enviamos um link").

**Gap real encontrado ao desenhar isso**: `cliente.email` é **opcional** hoje (nullable no schema) — vários clientes de teste não têm e-mail. Pra login por link funcionar, precisa de e-mail. Duas opções a decidir com você: (a) só libera Portal pra quem já tem e-mail cadastrado, pedir pro funcionário completar cadastro dos outros; (b) segunda via de autenticação por SMS/WhatsApp (mais infraestrutura nova, não recomendo pro MVP).

---

## 3. Isolamento de dado (o ponto mais crítico de segurança)

Proposta: rotas do Portal ficam num **blueprint/prefixo totalmente separado** (`/portal/*` ou app Flask própria, tipo o padrão já usado de `webapp/` porta 5000 vs `atendimento/webhook.py` porta 5001), nunca reaproveitando `@login_required` do staff nem misturando sessão.

Toda rota do Portal:
- Lê `cliente_id` **só** da sessão do cliente autenticado (nunca de parâmetro de URL/JSON vindo do navegador — isso evitaria um cliente trocar o ID na requisição e ver dado de outro).
- Toda query já nasce filtrada por esse `cliente_id` (mesmo padrão que `core/motor_casos.py` etc. já usam, só que agora com o filtro vindo da sessão em vez de vir livre).

**Como testar isso antes de ir pro ar**: criar 2 clientes de teste, logar como um, tentar adivinhar/forçar acesso ao caso do outro (via URL direta, id trocado no request) — se vazar, é bug crítico, não sobe.

---

## 4. Onde isso vai rodar (hospedagem)

Hoje **tudo roda em `localhost`** com o servidor de desenvolvimento do Flask — isso não é seguro nem acessível de fora, mesmo com HTTPS na frente. Expor o Portal pra clientes reais exige, pela primeira vez neste projeto, decisões de produção de verdade:

- Servidor WSGI de produção (ex. `waitress`, já roda bem em Windows sem mudar de SO; ou `gunicorn` se algum dia mudar pra Linux) em vez do `app.run()` de dev.
- Domínio próprio + certificado HTTPS (ex. Let's Encrypt, ou HTTPS gerenciado se hospedar em nuvem).
- Onde hospedar: manter no computador de vocês com port-forward (mais barato, mas o PC precisa ficar ligado e sua rede exposta — não recomendo pra dado sensível de arma de fogo) vs. um provedor pequeno (Railway, Fly.io, um VPS barato) — isso é decisão de custo/operacional, não técnica, preciso da sua opinião aqui.

**Isso também é o gatilho natural pra migração SQLite → PostgreSQL/Supabase** que o `PROJETO_1.md` já previa (Fase 6) — SQLite é um arquivo local, não foi pensado pra um servidor web público com múltiplos clientes acessando ao mesmo tempo. Não precisa ser feito antes do MVP do Portal (dá pra rodar hospedado com SQLite por um tempo, com cuidado), mas é uma bomba-relógio que vale planejar cedo.

---

## 5. O que muda no código existente

- **Nada muda** no painel admin, motor_ia, ou nos canais de atendimento hoje existentes — Portal é aditivo.
- Reaproveita sem modificar: `core/motor_documentos.py`, `core/checklist` (`core/motor_checklist.py`), `VW_CHECKLIST_SERVICO`, `motor_ia/identificador_cliente.py`, `integracoes/gmail.py::enviar_email`.
- Novo: `atendimento/portal/` (ou nome parecido) com suas próprias rotas Flask, template(s), e uma tabela nova pra token de login (`portal_token`: token, cliente_id, criado_em, expira_em, usado_em) -- schema pequeno, mesmo padrão dos outros.

---

## Decisões confirmadas (2026-07-25)

1. **Escopo do MVP**: só status do caso + checklist de documentos + upload. Chat com a IA pelo Portal fica pra uma rodada futura.
2. **Login**: link mágico por e-mail (token de uso único, ~15 min de validade). Sem senha.
3. **Clientes sem e-mail cadastrado**: ficam sem acesso ao Portal por enquanto — funcionário completa o cadastro manualmente quando for preciso. Não bloqueia o MVP.
4. **Hospedagem**: decisão adiada de propósito — construir e testar em `localhost` primeiro (mesmo padrão de todo o resto do projeto), decidir domínio/provedor só quando o MVP estiver pronto pra ir ao ar com o primeiro cliente real.
