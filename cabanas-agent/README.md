# Agente IA — Cabanas

Atendimento automático no WhatsApp para as cabanas do Adriano. Responde preço,
disponibilidade e manda o link do Airbnb; passa para a Camile o que precisa de
gente. Implementa a spec em [`agente-cabanas-spec.md`](../agente-cabanas-spec.md).

**Stack:** FastAPI + Gemini API + WhatsApp Cloud API + Firestore, rodando no Cloud Run.
**Projeto GCP:** `serious-trainer-465716-j9` · **Região:** `us-central1`

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

Cada mensagem passa por três etapas:

1. **Trava de escalação** (`app/intents.py`) — se a mensagem pede desconto, é
   reclamação, fala de evento/grupo ou pede atendimento humano, o Gemini nem é
   chamado. A resposta é fixa e a Camile recebe um aviso. É o que garante que
   "faz por 100?" nunca vira negociação.
2. **Gemini** (`app/gemini_client.py`) — responde o resto, com o system prompt
   da seção 2 da spec e as últimas mensagens da conversa como contexto.
3. **Firestore** (`app/storage.py`) — registra telefone, texto, resposta,
   intenção e timestamp. É a base do painel de fechamento mensal.

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

39 testes cobrindo os cinco fluxos da seção 3, os gatilhos de escalação da
seção 2, deduplicação de webhook, queda do Gemini e validação de assinatura.
Nenhum deles usa rede.

## Deploy no Cloud Run

Credenciais vão para o Secret Manager, nunca para a imagem:

```bash
PROJECT=serious-trainer-465716-j9
REGION=us-central1

for s in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  printf "valor-aqui" | gcloud secrets create $s --data-file=- --project=$PROJECT
done

gcloud run deploy cabanas-agent \
  --source . \
  --project=$PROJECT \
  --region=$REGION \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT,FIRESTORE_COLLECTION=cabanas_leads,WHATSAPP_PHONE_NUMBER_ID=...,ESCALATION_NUMBER=...,CABANAS=1,2,3,4,5" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest"
```

`--allow-unauthenticated` é necessário: quem chama é a Meta, que não faz login
no GCP. Quem protege o endpoint é a assinatura `X-Hub-Signature-256`, por isso
`WHATSAPP_APP_SECRET` é obrigatório em produção.

Índice do Firestore (a consulta de histórico não funciona sem ele):

```bash
gcloud firestore indexes create --project=$PROJECT # ou:
firebase deploy --only firestore:indexes          # usa firestore.indexes.json
```

## Configurar o webhook na Meta

1. App → WhatsApp → Configuration → Webhook
2. **Callback URL:** `https://SEU-SERVICO.run.app/webhook`
3. **Verify token:** o mesmo valor de `WHATSAPP_VERIFY_TOKEN`
4. Assinar o campo **`messages`**

A Meta faz um `GET /webhook` na hora de salvar. Se der erro, confira se o
serviço está no ar e se o token bate.

## Ligar/desligar cabanas sem mexer no código

`CABANAS=1,2,4,5` tira a cabana 3 do prompt e dos links. Serve enquanto a
pendência com a Camile não se resolve (ver checklist da spec).

## O que este agente não faz

- **Não confirma datas.** Ele não tem acesso ao calendário do Airbnb. Sempre
  manda a pessoa conferir no link, onde a disponibilidade real aparece.
- **Não confirma reservas.** Quem reserva é o cliente, no Airbnb.
- **Não mede clique no link.** Ele registra que o link *foi enviado*
  (`link_enviado`), mas o clique acontece no domínio do Airbnb, fora do nosso
  alcance. Para medir clique de verdade seria preciso servir um link próprio
  que redireciona — o schema já reserva o campo `clicou_em` para isso.
