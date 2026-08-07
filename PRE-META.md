# Antes da Meta — tudo que dá para adiantar hoje

Cada etapa tem um **comando de verificação**. Só siga para a próxima quando a
verificação passar — assim nenhum erro aparece só lá no final.

Nada aqui depende da Meta. Quando você tiver as credenciais dela, faltam
apenas dois comandos (etapa 7).

> **Com pressa?** As etapas 1 a 7 estão empacotadas em
> `bash cabanas-agent/scripts/gcp_setup.sh` — ele faz e confere cada uma, e
> para no primeiro erro dizendo o que fazer. O passo a passo abaixo continua
> valendo para entender o que ele fez, ou para consertar algo no meio.

```bash
export PROJECT=serious-trainer-465716-j9
export REGION=us-central1
gcloud config set project $PROJECT
```

**Verificação:**
```bash
gcloud config get-value project    # tem que imprimir serious-trainer-465716-j9
```

---

## 1. Ligar as APIs

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

**Verificação** — tem que listar as cinco:
```bash
gcloud services list --enabled \
  --filter="config.name:(run OR firestore OR secretmanager OR cloudbuild OR artifactregistry)" \
  --format="value(config.name)"
```

Demora ~1 min para propagar. Se vier menos de cinco, espere e rode de novo.

---

## 2. Criar o Firestore

```bash
gcloud firestore databases create --location=$REGION --type=firestore-native
```

**Verificação** — `locationId` tem que ser `us-central1`:
```bash
gcloud firestore databases list --format="value(name,locationId,type)"
```

> ⚠️ A região é **permanente**. Se sair errada, o conserto é apagar o banco e
> recriar. Confira antes de seguir.

---

## 3. Permissões da conta de serviço

Sem isto o serviço sobe e quebra na primeira mensagem — e o erro só aparece no
log do Cloud Run.

```bash
export NUMERO=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
export SA="$NUMERO-compute@developer.gserviceaccount.com"
echo "conta de serviço: $SA"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/datastore.user" --quiet
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --quiet
```

**Verificação** — tem que listar os dois papéis:
```bash
gcloud projects get-iam-policy $PROJECT \
  --flatten="bindings[].members" \
  --filter="bindings.members:$SA AND bindings.role:(datastore.user OR secretmanager.secretAccessor)" \
  --format="value(bindings.role)"
```

---

## 4. Índices do Firestore

Sem eles, o histórico da conversa e as telas do painel falham na consulta.

```bash
cd ~/luduran-cabanas/cabanas-agent   # onde estiver o repositório
firebase deploy --only firestore:indexes
```

Se não tiver o `firebase` CLI, dá para criar um a um:

```bash
gcloud firestore indexes composite create --collection-group=cabanas_leads \
  --field-config=field-path=nicho,order=ascending \
  --field-config=field-path=telefone,order=ascending \
  --field-config=field-path=criado_em,order=descending

gcloud firestore indexes composite create --collection-group=cabanas_leads \
  --field-config=field-path=nicho,order=ascending \
  --field-config=field-path=criado_em,order=descending

gcloud firestore indexes composite create --collection-group=cabanas_leads \
  --field-config=field-path=nicho,order=ascending \
  --field-config=field-path=lead_quente,order=ascending \
  --field-config=field-path=criado_em,order=descending
```

**Verificação** — os três com estado `READY` (leva alguns minutos):
```bash
gcloud firestore indexes composite list --format="value(name,state)"
```

Pode seguir enquanto ficam `CREATING`; só precisam estar prontos antes do
primeiro cliente real.

---

## 5. Chave do Gemini — dá para pegar agora

1. https://aistudio.google.com/apikey
2. **Create API key** → projeto `serious-trainer-465716-j9`
3. Copiar (só aparece uma vez)

**Verificação** — troque a chave e rode; tem que listar modelos:
```bash
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=COLE_A_CHAVE" \
  | head -c 200
```

Se vier `API_KEY_INVALID`, a chave está errada ou o projeto não bate.

---

## 6. Verify token — você inventa

Não vem de lugar nenhum: é a senha do handshake com a Meta, e o mesmo valor
vai nos dois lados.

```bash
openssl rand -hex 24
```

**Guarde num lugar seguro** — você vai precisar dele de novo no formulário da
Meta (etapa 12 do `DEPLOY.md`).

---

## 7. Secret Manager

Crie os quatro cofres **agora**, mesmo sem ter os valores da Meta. Depois é só
acrescentar a versão.

```bash
for s in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  gcloud secrets create $s --replication-policy=automatic 2>/dev/null \
    && echo "criado: $s" || echo "já existia: $s"
done
```

**Já dá para preencher dois:**

```bash
printf 'COLE_A_CHAVE_DO_GEMINI' | gcloud secrets versions add GEMINI_API_KEY --data-file=-
printf 'COLE_O_VERIFY_TOKEN'    | gcloud secrets versions add WHATSAPP_VERIFY_TOKEN --data-file=-
```

**Quando tiver a Meta, faltam só estes dois:**

```bash
printf 'COLE_O_TOKEN_PERMANENTE' | gcloud secrets versions add WHATSAPP_TOKEN --data-file=-
printf 'COLE_O_APP_SECRET'       | gcloud secrets versions add WHATSAPP_APP_SECRET --data-file=-
```

> Use `printf`, não `echo`: o `echo` acrescenta uma quebra de linha ao valor, e
> um token com `\n` no fim é recusado pela Meta com um erro que não explica
> nada.

**Verificação** — os quatro com pelo menos uma versão:
```bash
for s in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  printf "%-24s %s\n" "$s" "$(gcloud secrets versions list $s --format='value(name)' 2>/dev/null | head -1 || echo 'SEM VERSÃO')"
done
```

---

## Onde vai cada credencial

| Variável | Onde | Por quê |
| --- | --- | --- |
| `GEMINI_API_KEY` | **Secret Manager** | é segredo |
| `WHATSAPP_TOKEN` | **Secret Manager** | é segredo |
| `WHATSAPP_VERIFY_TOKEN` | **Secret Manager** | é segredo |
| `WHATSAPP_APP_SECRET` | **Secret Manager** | é segredo |
| `WHATSAPP_PHONE_NUMBER_ID` | env var no deploy | é identificador público |
| `WHATSAPP_PHONE_NUMBER` | env var no deploy | só conferência |
| `ESCALATION_NUMBER` | env var no deploy | telefone da equipe |
| `GCP_PROJECT_ID`, `NICHO`, `CABANAS`… | env var no deploy | configuração |

Segredo em `--set-env-vars` fica **visível** para qualquer pessoa com acesso de
leitura ao Cloud Run, e aparece no histórico do shell. Por isso os quatro de
cima vão por `--set-secrets`.

---

## 8. Conferir tudo antes do deploy

```bash
cd cabanas-agent
cp .env.example .env    # preencha com o que já tem
set -a && source .env && set +a
python scripts/pre_deploy.py
```

Antes da Meta ele vai acusar `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_NUMBER_ID` —
esperado. O que precisa estar verde já: **Gemini**, **Firestore** e **Cabanas**.

---

## 9. Deploy — com os valores reais

Depois que os quatro segredos estiverem preenchidos:

```bash
cd cabanas-agent

gcloud run deploy cabanas-agent \
  --source . \
  --region=$REGION \
  --allow-unauthenticated \
  --set-env-vars="^|^GCP_PROJECT_ID=$PROJECT|FIRESTORE_COLLECTION=cabanas_leads|NICHO=cabanas|NICHOS_PAINEL=cabanas|COOKIE_SEGURO=1|COMISSAO_PERCENTUAL=10|WHATSAPP_PHONE_NUMBER_ID=COLE_O_ID_DA_META|WHATSAPP_PHONE_NUMBER=+55 54 99910-3545|ESCALATION_NUMBER=5554984487198" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest"
```

O `^|^` no início do `--set-env-vars` troca o separador de vírgula para `|`.
Sem ele o `gcloud` corta os valores na vírgula.

**Verificação:**
```bash
export URL=$(gcloud run services describe cabanas-agent --region=$REGION --format='value(status.url)')
echo $URL
curl -s $URL/health | python3 -m json.tool
```

Tem que vir:

```json
{
  "config_faltando": [],
  "cabanas_sem_link": [],
  "cabanas": ["1","2","3","4","5"],
  "numero_atendimento": "+55 54 99910-3545",
  "aviso_escalacao_por_whatsapp": "ok"
}
```

Se `config_faltando` não estiver vazio, **pare** — o webhook vai falhar.

---

## 10. Webhook na Meta

Só agora a URL existe.

App → WhatsApp → Configuração → Webhook → Editar:

- **URL:** `$URL/webhook` (o valor que saiu acima, com `/webhook` no fim)
- **Token:** o verify token da etapa 6
- Salvar → **Gerenciar** → assinar o campo **`messages`**

**Verificação** — simule o handshake que a Meta faz:
```bash
curl -s "$URL/webhook?hub.mode=subscribe&hub.verify_token=COLE_O_VERIFY_TOKEN&hub.challenge=12345"
```

Tem que responder exatamente `12345`. Se responder `forbidden`, o token no
Secret Manager e o do formulário não batem.

> Esquecer de assinar **`messages`** é o erro mais comum: a URL fica salva,
> a verificação passa, e nenhuma mensagem chega.

---

## 11. Usuários do painel

```bash
gcloud auth application-default login    # uma vez, na sua máquina
cd cabanas-agent
python scripts/criar_usuario.py lucas@luduran.com   --papel admin
python scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
python scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas
```

**Verificação:**
```bash
gcloud firestore documents list --collection-ids=painel_usuarios --format="value(name)" 2>/dev/null \
  || echo "confira abrindo $URL/painel/login e entrando com o seu usuário"
```

---

## 12. Teste de ponta a ponta

De um celular que **não** seja o do sistema:

| Mensagem | Esperado |
| --- | --- |
| "Quanto custa a diária?" | R$150,00 + link do Airbnb |
| "Tem vaga dia 12? Somos 4" | responde e vira **lead quente** |
| "Faz desconto?" | resposta de escalação, aparece em `/painel/escalacoes` |
| áudio | pede para escrever em texto |

**Verificação:**
```bash
gcloud run services logs read cabanas-agent --region=$REGION --limit=30
```

Procure `Lead quente:` no log da segunda mensagem, e abra `$URL/painel/` para
ver as conversas.

---

## Resumo do que dá para fazer HOJE

- [ ] Etapas 1 a 4 — GCP inteiro
- [ ] Etapa 5 — chave do Gemini
- [ ] Etapa 6 — verify token
- [ ] Etapa 7 — criar os quatro cofres e preencher dois
- [ ] Etapa 8 — `pre_deploy.py` com Gemini, Firestore e Cabanas verdes

Amanhã, com a Meta na mão: dois `versions add`, o deploy, o webhook e o teste.
**Menos de 30 minutos**, se as etapas de hoje estiverem verdes.
