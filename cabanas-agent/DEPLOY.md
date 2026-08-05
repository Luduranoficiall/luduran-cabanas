# Checklist de deploy — Agente Cabanas

Ordem exata, de cima para baixo. Projeto `serious-trainer-465716-j9`, região
`us-central1`.

## A dependência circular não existe (e por quê)

A dúvida é justa: o webhook precisa da URL do Cloud Run, que só existe depois
do deploy. Mas o `verify_token` **é escolhido por nós**, não pela Meta — é uma
senha qualquer que a gente inventa e configura dos dois lados. Então a ordem
resolve sozinha:

```
credenciais → deploy (nasce a URL) → webhook na Meta
```

O que **não** pode inverter:

- `WHATSAPP_APP_SECRET` tem que estar no serviço **antes** de configurar o
  webhook. Assim que a Meta é apontada para a URL, ela começa a mandar POST; se
  o segredo não estiver lá, o agente aceita requisição de qualquer origem.
- O Firestore precisa existir **antes** da primeira mensagem real, senão a
  gravação falha e o lead se perde.

---

## ⚠️ Antes de começar: o número muda de dono

`+55 54 98448-7198` é o número da secretária do clube. Migrar para a Cloud API
**tira o número do aplicativo WhatsApp Business**. A secretária deixa de
atender por ele no celular — dali em diante quem responde é o agente, e o
histórico de conversas do aplicativo não vem junto.

Isso é difícil de desfazer e afeta a operação do clube todo dia. Confirme com a
Camily e com o Adriano **antes** do passo 5. Se a ideia era manter a secretária
atendendo em paralelo, o caminho é outro número.

---

## 1. Ligar as APIs do GCP

```bash
PROJECT=serious-trainer-465716-j9
REGION=us-central1

gcloud config set project $PROJECT
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

## 2. Criar o Firestore

```bash
gcloud firestore databases create --location=$REGION --type=firestore-native
```

> ⚠️ **A região do Firestore é permanente.** Não dá para mudar depois sem
> recriar o banco e migrar o dado. `us-central1`, igual ao Cloud Run.

Os índices ficam para o passo 9 — dá para criá-los antes, mas eles levam alguns
minutos e não bloqueiam o deploy.

## 3. `GEMINI_API_KEY`

1. https://aistudio.google.com/apikey
2. **Create API key** → escolher o projeto `serious-trainer-465716-j9`
3. Copiar. A chave só aparece uma vez.

## 4. `WHATSAPP_VERIFY_TOKEN` (inventado por nós)

Não vem de lugar nenhum — é a senha do handshake. Gere uma:

```bash
openssl rand -hex 24
```

Guarde: o mesmo valor vai no Secret Manager (passo 7) e no formulário da Meta
(passo 10).

## 5. Meta: app, número e credenciais

Em https://developers.facebook.com → seu app → **WhatsApp**.

**5a. `WHATSAPP_PHONE_NUMBER_ID`**
→ WhatsApp → **API Setup** → campo *Phone number ID*.
São ~15 dígitos. **Não é o telefone** — preencher com `5554984487198` faz todo
envio falhar com 400.

**5b. `WHATSAPP_APP_SECRET`**
→ Configurações do app → **Básico** → *Chave secreta do app* → **Mostrar**.

**5c. `WHATSAPP_TOKEN` permanente**
O token da tela de API Setup **expira em 24 horas** e não serve. O permanente
sai de um usuário do sistema:

1. https://business.facebook.com → **Configurações do negócio**
2. **Usuários → Usuários do sistema** → *Adicionar* (função: Administrador)
3. **Adicionar ativos** → o app do WhatsApp, com controle total
4. **Gerar novo token** → escolher o app → marcar as permissões
   `whatsapp_business_messaging` e `whatsapp_business_management`
5. Validade: **Nunca**. Copiar — só aparece uma vez.

**5d. Migrar o número** (ver o aviso lá em cima antes de fazer)
→ WhatsApp → **API Setup** → *Add phone number*, e seguir a verificação.

## 6. Decidir o número de escalação

> ⚠️ **Hoje `ESCALATION_NUMBER` é o mesmo número do atendimento, e isso não
> funciona.** A Cloud API recusa mensagem de um número para ele mesmo, então o
> aviso "esta conversa precisa de humano" nunca chega.
>
> O agente detecta isso e nem tenta enviar — a escalação fica registrada e
> aparece em `/painel/escalacoes`. Nada se perde, mas **ninguém é avisado na
> hora**.
>
> Para o aviso funcionar, `ESCALATION_NUMBER` precisa ser **outro** número (o
> celular pessoal da Camily, por exemplo). E ainda assim há um segundo limite:
> a Cloud API só entrega mensagem livre dentro de 24h da última mensagem que
> aquele número mandou para o negócio. Fora dessa janela é preciso um
> *template* aprovado pela Meta (leva alguns dias). Enquanto não houver
> template, a Camily precisa mandar um "oi" para o número do agente de vez em
> quando para manter a janela aberta — ou usar a tela de escalações como fonte.

Decida antes do passo 7; é uma variável de ambiente.

## 7. Guardar os segredos

```bash
for s in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  gcloud secrets create $s --replication-policy=automatic
done

# um a um, para o valor não ficar no histórico do shell:
printf 'valor-aqui' | gcloud secrets versions add GEMINI_API_KEY --data-file=-
printf 'valor-aqui' | gcloud secrets versions add WHATSAPP_TOKEN --data-file=-
printf 'valor-aqui' | gcloud secrets versions add WHATSAPP_VERIFY_TOKEN --data-file=-
printf 'valor-aqui' | gcloud secrets versions add WHATSAPP_APP_SECRET --data-file=-
```

## 8. Permissões da conta de serviço

Sem isto o serviço sobe e quebra na primeira mensagem.

```bash
NUMERO=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
SA="$NUMERO-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
```

## 9. Índices do Firestore

```bash
firebase deploy --only firestore:indexes   # usa firestore.indexes.json
```

Sem eles, o histórico da conversa e as telas do painel falham na consulta.
Levam alguns minutos para ficar prontos.

## 10. Deploy

```bash
cd cabanas-agent

gcloud run deploy cabanas-agent \
  --source . \
  --region=$REGION \
  --allow-unauthenticated \
  --set-env-vars="^|^GCP_PROJECT_ID=$PROJECT|FIRESTORE_COLLECTION=cabanas_leads|NICHO=cabanas|NICHOS_PAINEL=cabanas|COOKIE_SEGURO=1|COMISSAO_PERCENTUAL=10|CABANAS=1,2,3,4,5|WHATSAPP_PHONE_NUMBER_ID=COLE_AQUI|WHATSAPP_PHONE_NUMBER=+55 54 98448-7198|ESCALATION_NUMBER=DECIDIDO_NO_PASSO_6" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest"
```

> ⚠️ O `^|^` no começo do `--set-env-vars` **não é enfeite**. Por padrão o
> `gcloud` separa as variáveis por vírgula, e `CABANAS=1,2,3,4,5` viraria cinco
> variáveis quebradas. O prefixo troca o separador para `|`, e aí a vírgula
> dentro do valor sobrevive.
>
> Se preferir não lidar com isso: tire `CABANAS` do comando. O padrão no código
> já é `1,2,3,4,5`.

`--allow-unauthenticated` é obrigatório: quem chama é a Meta, que não faz login
no GCP. Quem protege o endpoint é a assinatura `X-Hub-Signature-256`.

Guarde a URL que sai no fim: `https://cabanas-agent-XXXX.run.app`.

## 11. Conferir antes de apontar a Meta

```bash
curl -s https://SEU-SERVICO.run.app/health | python3 -m json.tool
```

Precisa vir:

- `"config_faltando": []`
- `"cabanas_sem_link": []`
- `"cabanas": ["1","2","3","4","5"]`

Se `config_faltando` não estiver vazio, **pare aqui** — o webhook vai falhar.

## 12. Webhook na Meta

Agora a URL existe.

1. App → **WhatsApp → Configuração → Webhook** → *Editar*
2. **URL de callback:** `https://SEU-SERVICO.run.app/webhook`
3. **Token de verificação:** o valor do passo 4
4. **Verificar e salvar** — a Meta faz um `GET` na hora; se der erro, confira se
   o serviço responde e se o token bate
5. **Gerenciar** → assinar o campo **`messages`**

Sem o passo 5 a URL fica salva e nenhuma mensagem chega — é o esquecimento mais
comum.

## 13. Usuários do painel

```bash
python cabanas-agent/scripts/criar_usuario.py lucas@luduran.com   --papel admin
python cabanas-agent/scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
python cabanas-agent/scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas
```

Roda da máquina local, autenticado com `gcloud auth application-default login`.

## 14. Teste de ponta a ponta

De um celular que **não** seja o do agente:

| Mensagem | Esperado |
| --- | --- |
| "Quanto custa a diária?" | responde R$150,00 e manda link |
| "Tem vaga dia 12? Somos 4" | responde + vira **lead quente** no painel |
| "Faz desconto?" | resposta de escalação, aparece em `/painel/escalacoes` |
| áudio | pede para escrever em texto |

Depois: `/painel/` mostra as conversas, e `/painel/fechamento` lista os leads.

## 15. Observar 24h antes de anunciar

Acompanhe:

```bash
gcloud run services logs read cabanas-agent --region=$REGION --limit=50
```

Procure por: erro de envio da Meta (token errado), `GeminiIndisponivel`
(timeout ou cota), e `Assinatura inválida` (app secret errado).

---

## Depois de estar no ar

- [ ] Subir as fotos em `assets/cabanas/` e rodar `scripts/gerar_site.py`
- [ ] GitHub Pages: Settings → Pages → branch `main` / root
- [ ] **Definir o prazo de retenção das conversas** (LGPD)
- [ ] Resolver o número de escalação (passo 6)
- [ ] Definir com o Adriano quem paga a infraestrutura

## Custo esperado

Volume desta operação (dezenas de conversas por dia): Cloud Run e Firestore
ficam dentro da cota gratuita, e o Gemini Flash sai por centavos no mês. O que
pode surpreender é o Cloud Build a cada deploy e, se o volume crescer muito, a
leitura do Firestore no painel. Vale colocar um **orçamento com alerta** no
projeto antes de ligar.
