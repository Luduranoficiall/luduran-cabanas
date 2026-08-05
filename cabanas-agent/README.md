# Agente IA — Cabanas

Atendimento automático no WhatsApp para as cabanas do Adriano. Responde preço,
disponibilidade e manda o link do Airbnb; passa para a Camile o que precisa de
gente. Implementa a spec em [`agente-cabanas-spec.md`](../agente-cabanas-spec.md).

**Stack:** FastAPI + Gemini API + WhatsApp Cloud API + Firestore, rodando no Cloud Run.
**Projeto GCP:** `serious-trainer-465716-j9` · **Região:** `us-central1`
**Número de atendimento:** +55 54 98448-7198 (secretária do clube) — mesmo
número que recebe as escalações.

## Como funciona

```
WhatsApp (Meta Cloud API)
        │  webhook POST
        ▼
┌──────────────────────┐
│  Cloud Run (FastAPI) │   responde 200 na hora,
│  /webhook  /health   │   processa em background
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
 Gemini API   Firestore
```

Cada mensagem passa por quatro etapas:

0. **Anti-loop** (`app/webhook.py`) — acima de 15 mensagens do mesmo número em
   10 minutos, o agente para de responder e escala. Avisa uma vez só e não
   gasta mais chamada de modelo.
1. **Trava de escalação** (`app/intents.py`) — se a mensagem pede desconto, é
   reclamação, fala de evento/grupo ou pede atendimento humano, o Gemini nem é
   chamado. A resposta é fixa e a Camile recebe um aviso. É o que garante que
   "faz por 100?" nunca vira negociação.
2. **Gemini** (`app/gemini_client.py`) — responde o resto, com o system prompt
   da seção 2 da spec e as últimas trocas como contexto: 10 trocas ou 30
   minutos, o que vier primeiro. Conversa de ontem não é contexto, é ruído.
3. **Firestore** (`app/storage.py`) — registra nicho, telefone, texto, resposta,
   intenção, se é lead quente e timestamp. É a base do painel de fechamento
   mensal.

### Lead quente

Marca quem demonstrou intenção real de reserva — a métrica que separa "20
pessoas conversaram" de "7 queriam mesmo reservar". Três sinais:

| Sinal | Dispara com |
| --- | --- |
| `data_especifica` | "dia 12", "12/03", dia da semana, mês, feriadão |
| `numero_pessoas` | "4 pessoas", "somos 6", casal, família, criança |
| `pediu_reserva` | "quero reservar", "como faço para reservar" |

A detecção é conservadora de propósito: essa métrica sustenta a conversa dos
10%, e um número inflado cai por terra quando o cliente conferir caso a caso.
"Qual a política de reserva?" não conta; "quero reservar" conta.

### Multi-nicho

Todo documento nasce com `nicho` (`NICHO`, padrão `cabanas`), e o histórico da
conversa filtra por ele. Quando academia e alojamento entrarem, a mesma pessoa
falando com duas operações não mistura contexto — e não vai ser preciso migrar
dado que já está em produção.

## Painel

Roda no mesmo serviço, sob `/painel`: visão do mês e fechamento mensal com a
lista de leads quentes pronta para conferência — a Camily marca o que virou
reserva, informa o valor, e o painel calcula os 10% e exporta o CSV. Login de
verdade, três papéis (admin / operador / leitor) e filtro por nicho.
Ver [PAINEL.md](PAINEL.md).

## Página de demonstração

A página em `index.html` é **gerada**, não editada à mão:

```bash
python cabanas-agent/scripts/gerar_site.py
git add index.html && git commit
```

A seção das cabanas sai da mesma configuração do agente (`CABANAS` /
`CABANA_URLS`), então site e atendimento não divergem — e cabana sem link
cadastrado não aparece, igual ao agente. Editar `site/index.template.html` sem
rodar o gerador faz o teste `test_index_commitado_esta_atualizado` falhar.

## Rodar local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # preencha as credenciais
uvicorn app.main:app --reload --port 8080
```

`GET /health` mostra o que ainda falta configurar.

## Testes

```bash
pytest
```

191 testes: os cinco fluxos da seção 3, os gatilhos de escalação da seção 2,
deduplicação de webhook, queda do Gemini, validação de assinatura, troca de
configuração das cabanas, geração da página e o painel (autenticação,
isolamento por nicho, métricas, conferência do fechamento, cálculo da comissão,
CSV, escalações e auditoria), além da memória com corte por tempo e do
anti-loop. Nenhum deles usa rede.

## Deploy no Cloud Run

**Checklist completo, na ordem exata: [DEPLOY.md](DEPLOY.md).**

Resumido: ligar as APIs → criar o Firestore → pegar as credenciais (Gemini e
Meta) → guardar no Secret Manager → permissões da conta de serviço → índices →
deploy → conferir `/health` → só então apontar o webhook na Meta.

A URL do Cloud Run só existe depois do deploy, e é por isso que o webhook é o
penúltimo passo. O `verify_token` não trava a ordem: quem escolhe o valor
somos nós.

## Ligar/desligar cabanas sem mexer no código

Duas variáveis controlam tudo:

| Variável | Para quê |
| --- | --- |
| `CABANAS` | quais cabanas estão no ar (ex.: `1,2,4,5`) |
| `CABANA_URLS` | link de uma cabana nova ou correção de um existente (ex.: `3=https://...`) |

**Hoje:** as cinco cabanas no ar. Os links ficam em `config.py`
(`LINKS_CONFIRMADOS`); `CABANAS` só escolhe quais estão ativas.

Para tirar uma de operação, basta removê-la de `CABANAS`. Para cadastrar uma
cabana nova sem esperar deploy, use `CABANA_URLS=6=https://...`.

Prompt e respostas acompanham sozinhos — `prompts.py` monta a lista de cabanas
a partir da configuração, e `gemini_client.py` não conhece link nenhum. Tem
teste travando isso (`test_links_de_cabana_so_existem_no_config`).

**Trava de segurança:** cabana listada em `CABANAS` sem link cadastrado fica
**fora do ar** de propósito, com erro no log e no `/health`. O agente não
inventa URL por padrão de nome — link chutado vira link quebrado na mão do
cliente.

## O que este agente não faz

- **Não confirma datas.** Ele não tem acesso ao calendário do Airbnb. Sempre
  manda a pessoa conferir no link, onde a disponibilidade real aparece.
- **Não confirma reservas.** Quem reserva é o cliente, no Airbnb.
- **Não mede clique no link.** Ele registra que o link *foi enviado*
  (`link_enviado`), mas o clique acontece no domínio do Airbnb, fora do nosso
  alcance. Para medir clique de verdade seria preciso servir um link próprio
  que redireciona — o schema já reserva o campo `clicou_em` para isso.
