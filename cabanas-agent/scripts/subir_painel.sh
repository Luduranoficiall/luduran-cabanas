#!/usr/bin/env bash
#
# Sobe AGORA o que não depende da Meta: o painel, com URL de verdade.
#
#   bash scripts/subir_painel.sh
#
# O cliente entra com login e senha, marca reservas, informa valores, baixa o
# CSV — e tudo fica gravado no Firestore. É o sistema real, na internet.
#
# O que NÃO funciona até a Meta liberar: receber mensagem de WhatsApp. Nenhum
# contorno existe para isso — a mensagem passa pelo servidor da Meta.
#
# Depois, com as credenciais da Meta em mãos:
#   bash scripts/deploy.sh SEU_PHONE_NUMBER_ID

set -uo pipefail

PROJECT="${PROJECT:-serious-trainer-465716-j9}"
REGION="${REGION:-us-central1}"
SERVICO="${SERVICO:-cabanas-agent}"
TELEFONE="${WHATSAPP_PHONE_NUMBER:-+55 54 99910-3545}"
ESCALACAO="${ESCALATION_NUMBER:-5554984487198}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

verde()   { printf '\033[32m  ok  \033[0m %s\n' "$1"; }
amarelo() { printf '\033[33m aviso\033[0m %s\n' "$1"; }
etapa()   { printf '\n\033[1m── %s\033[0m\n' "$1"; }
parar()   { printf '\033[31m ERRO \033[0m %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; exit 1; }

etapa "1/4  Conferindo o que já existe"

gcloud config set project "$PROJECT" >/dev/null 2>&1
gcloud secrets versions access latest --secret=GEMINI_API_KEY >/dev/null 2>&1 \
  || parar "GEMINI_API_KEY está vazia." "Rode primeiro: bash scripts/gcp_setup.sh"
verde "GEMINI_API_KEY preenchida"

gcloud secrets versions access latest --secret=WHATSAPP_VERIFY_TOKEN >/dev/null 2>&1 \
  || parar "WHATSAPP_VERIFY_TOKEN está vazio." "Rode primeiro: bash scripts/gcp_setup.sh"
verde "WHATSAPP_VERIFY_TOKEN preenchido"

# O deploy exige que os quatro cofres tenham alguma versão. Os dois da Meta
# ainda não têm valor real, então entram com um marcador reconhecível — o
# WhatsApp não funciona com ele, e é exatamente isso que queremos deixar claro.
etapa "2/4  Marcadores temporários para os dois segredos da Meta"

for S in WHATSAPP_TOKEN WHATSAPP_APP_SECRET; do
  if gcloud secrets versions access latest --secret="$S" >/dev/null 2>&1; then
    verde "$S já tem valor"
  else
    printf 'AGUARDANDO-META' | gcloud secrets versions add "$S" --data-file=- >/dev/null 2>&1 \
      && amarelo "$S com marcador temporário (WhatsApp fica inativo)" \
      || parar "não consegui gravar $S."
  fi
done

etapa "3/4  Subindo (leva ~3 min)"

cd "$RAIZ" || parar "não achei $RAIZ"

gcloud run deploy "$SERVICO" \
  --source . \
  --project="$PROJECT" \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-env-vars="^|^GCP_PROJECT_ID=$PROJECT|FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION:-cabanas_leads}|NICHO=${NICHO:-cabanas}|NICHOS_PAINEL=${NICHOS_PAINEL:-cabanas}|COOKIE_SEGURO=1|COMISSAO_PERCENTUAL=${COMISSAO_PERCENTUAL:-10}|WHATSAPP_PHONE_NUMBER_ID=000000000000000|WHATSAPP_PHONE_NUMBER=$TELEFONE|ESCALATION_NUMBER=$ESCALACAO" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest" \
  || parar "o deploy falhou." "Veja o log: gcloud builds list --limit=1 --project=$PROJECT"

URL=$(gcloud run services describe "$SERVICO" --project="$PROJECT" --region="$REGION" \
      --format='value(status.url)' 2>/dev/null)
[ -n "$URL" ] || parar "subiu mas não consegui ler a URL."
verde "$URL"

etapa "4/4  Conferindo e criando os usuários"

SAUDE=$(curl -s --max-time 30 "$URL/health")
printf '%s' "$SAUDE" | grep -q '"status": *"ok"' \
  && verde "o serviço respondeu" \
  || parar "o /health não respondeu como esperado." "$SAUDE"

pip install -q -r requirements.txt 2>/dev/null

cat <<FIM

  ✅ NO AR: $URL/painel/

  Falta criar os usuários. Rode as três linhas abaixo — cada uma pede uma
  senha (a digitação fica invisível, é normal):

    python scripts/criar_usuario.py lucas@luduran.com   --papel admin
    python scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
    python scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas

  Aí mande $URL/painel/ para o Adriano com o login dele.
  O que ele marcar ali fica gravado de verdade.

  ─────────────────────────────────────────────────────────────

  ⚠️  O WhatsApp continua INATIVO. Os dois segredos da Meta estão com
     marcador. Quando as credenciais chegarem:

       printf 'TOKEN_PERMANENTE' | gcloud secrets versions add WHATSAPP_TOKEN --data-file=-
       printf 'APP_SECRET'       | gcloud secrets versions add WHATSAPP_APP_SECRET --data-file=-
       bash scripts/deploy.sh SEU_PHONE_NUMBER_ID

     Não aponte o webhook da Meta para esta URL antes disso: com o marcador
     no lugar do app secret, toda mensagem seria recusada por assinatura
     inválida.

FIM
