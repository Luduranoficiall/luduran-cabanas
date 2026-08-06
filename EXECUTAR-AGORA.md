# Executar agora — do zero ao ar

Folha única para colocar no ar hoje. O detalhe de cada passo está em
[`cabanas-agent/DEPLOY.md`](cabanas-agent/DEPLOY.md); aqui é a sequência.

**Estado:** código pronto e consolidado na `main`, 238 testes passando. O que
falta são credenciais — nenhuma delas eu consigo gerar por você.

---

## Bloco A — GCP (faça agora, não depende de ninguém) · ~15 min

```bash
PROJECT=serious-trainer-465716-j9
REGION=us-central1
gcloud config set project $PROJECT

# 1. APIs
gcloud services enable run.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# 2. Firestore — a região é PERMANENTE
gcloud firestore databases create --location=$REGION --type=firestore-native

# 3. Permissões da conta de serviço
NUMERO=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
SA="$NUMERO-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"

# 4. Índices
firebase deploy --only firestore:indexes
```

**Chave do Gemini:** https://aistudio.google.com/apikey → Create API key →
projeto `serious-trainer-465716-j9`.

**Verify token** (você inventa): `openssl rand -hex 24`

---

## Bloco B — Meta · ~30 min, na ordem

1. **Criar o app** — developers.facebook.com → Criar app → tipo **Empresa** →
   Adicionar produto → **WhatsApp**
2. **Cadastrar o chip** `+55 54 99910-3545` — Configuração da API → Adicionar
   número. Código chega por SMS **ou chamada**; o chip precisa estar num
   aparelho ligado nesse momento. Chip pré-pago novo às vezes bloqueia SMS
   curto → use **chamada de voz**.
3. **Copiar o `Phone number ID`** — só existe agora. ~15 dígitos, **não é o
   telefone**.
4. **`App secret`** — Configurações do app → Básico → Mostrar
5. **Token permanente** — business.facebook.com → Usuários do sistema → criar
   `agente-cabanas` (Administrador) → Adicionar ativos → o app, controle total
   → Gerar token, validade **Nunca**, com `whatsapp_business_messaging` e
   `whatsapp_business_management`.
   ⚠️ O token da tela de API Setup **expira em 24h** e não serve.
6. **Mudar o app para `Ativo`** (topo do painel). Em Desenvolvimento, cliente
   nenhum recebe resposta — e não aparece erro nenhum.

> ⚠️ **Nunca instale WhatsApp nesse chip.** Derruba o número da Cloud API.

---

## Bloco C — Conferir ANTES de gastar um deploy · 10 segundos

```bash
cd cabanas-agent
cp .env.example .env      # cole as credenciais aqui
set -a && source .env && set +a
python scripts/pre_deploy.py
```

Ele bate no Gemini, na Meta e no Firestore de verdade e diz qual credencial
está errada. Pega o engano mais comum — telefone colado no lugar do
`Phone number ID` — que só apareceria como um 400 genérico depois do deploy.

Só siga quando sair **"Tudo pronto"**.

---

## Bloco D — Deploy · ~5 min

```bash
gcloud run deploy cabanas-agent \
  --source . --region=$REGION --allow-unauthenticated \
  --set-env-vars="^|^GCP_PROJECT_ID=$PROJECT|FIRESTORE_COLLECTION=cabanas_leads|NICHO=cabanas|NICHOS_PAINEL=cabanas|COOKIE_SEGURO=1|COMISSAO_PERCENTUAL=10|WHATSAPP_PHONE_NUMBER_ID=COLE_AQUI|WHATSAPP_PHONE_NUMBER=+55 54 99910-3545|ESCALATION_NUMBER=5554984487198" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest"
```

O `^|^` no início não é enfeite: sem ele o `gcloud` corta as variáveis na
vírgula.

Guarde a URL. Depois:

```bash
curl -s https://SEU-SERVICO.run.app/health | python3 -m json.tool
```

Precisa vir `"config_faltando": []` e `"cabanas_sem_link": []`.

---

## Bloco E — Webhook · ~2 min

Só agora a URL existe.

App → WhatsApp → Configuração → Webhook → Editar:

- **URL:** `https://SEU-SERVICO.run.app/webhook`
- **Token:** o verify token do Bloco A
- Salvar → **Gerenciar** → assinar o campo **`messages`**

Esquecer de assinar `messages` é o erro mais comum: a URL fica salva e nenhuma
mensagem chega.

---

## Bloco F — Usuários e teste real · ~10 min

```bash
python scripts/criar_usuario.py lucas@luduran.com   --papel admin
python scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
python scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas
```

De um celular que **não** seja o do sistema:

| Mensagem | Esperado |
| --- | --- |
| "Quanto custa a diária?" | R$150,00 + link |
| "Tem vaga dia 12? Somos 4" | responde e vira **lead quente** |
| "Faz desconto?" | resposta de escalação, aparece em `/painel/escalacoes` |
| áudio | pede para escrever em texto |

Depois abra `/painel/` e confira que as conversas apareceram.

---

## Fica para depois (não bloqueia o lançamento)

| O quê | Por quê pode esperar |
| --- | --- |
| Template `escalacao_cabanas` | sistema funciona; a Camily acompanha por `/painel/escalacoes` |
| `RETENCAO_DIAS` | mecanismo pronto; falta você definir o prazo |
| Fotos das cabanas | cartão mostra "foto em breve" |
| GitHub Pages | a demo já roda local |
| Decisão do CRM | melhor com dado real na mesa |

## Se algo falhar

```bash
gcloud run services logs read cabanas-agent --region=$REGION --limit=50
```

| No log | O que é |
| --- | --- |
| `janela de 24h está fechada` | falta o template — normal por enquanto |
| `Aviso de escalação NÃO entregue` | ninguém foi avisado; veja `/painel/escalacoes` |
| `Assinatura inválida` | `WHATSAPP_APP_SECRET` errado |
| `Meta recusou envio` código 190 | token expirado — usou o de 24h? |
| `GeminiIndisponivel` | cota ou timeout; o cliente recebeu o fallback |
