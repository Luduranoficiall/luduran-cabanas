#!/usr/bin/env bash
#
# Prepara o Google Cloud inteiro — tudo que NÃO depende da Meta.
#
# Cada etapa é conferida antes da seguinte. Se uma falhar, o script para ali e
# diz o que fazer: descobrir um erro de permissão só no deploy custa o dia.
# Rodar de novo é seguro — tudo aqui é idempotente.
#
#   bash scripts/gcp_setup.sh
#
# Ao final, faltam apenas as duas credenciais da Meta (WHATSAPP_TOKEN e
# WHATSAPP_APP_SECRET) e o Phone number ID.

set -uo pipefail

PROJECT="${PROJECT:-serious-trainer-465716-j9}"
REGION="${REGION:-us-central1}"
COLECAO="${FIRESTORE_COLLECTION:-cabanas_leads}"
ARQUIVO_TOKEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.verify-token.txt"

verde()   { printf '\033[32m  ok  \033[0m %s\n' "$1"; }
amarelo() { printf '\033[33m aviso\033[0m %s\n' "$1"; }
vermelho(){ printf '\033[31m ERRO \033[0m %s\n' "$1"; }

etapa() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

parar() {
  vermelho "$1"
  [ $# -gt 1 ] && printf '        %s\n' "$2"
  printf '\nParei aqui de propósito. Conserte e rode de novo — o que já passou não refaz.\n'
  exit 1
}

# --- 0. Pré-requisitos ------------------------------------------------------

etapa "0/8  Pré-requisitos"

command -v gcloud >/dev/null || parar "gcloud não encontrado." \
  "Instale: https://cloud.google.com/sdk/docs/install"

CONTA=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
[ -n "$CONTA" ] || parar "Nenhuma conta logada no gcloud." "Rode: gcloud auth login"
verde "logado como $CONTA"

gcloud config set project "$PROJECT" >/dev/null 2>&1
ATUAL=$(gcloud config get-value project 2>/dev/null)
[ "$ATUAL" = "$PROJECT" ] || parar "projeto ficou '$ATUAL', esperado '$PROJECT'."
verde "projeto $PROJECT"

# --- 1. APIs ----------------------------------------------------------------

etapa "1/8  Ligando as APIs"

gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com 2>&1 | grep -v '^$' || true

# A ativação leva alguns segundos para propagar; conferir uma vez só dá falso
# negativo e faz a gente reiniciar um passo que já deu certo.
for tentativa in 1 2 3 4 5 6; do
  LIGADAS=$(gcloud services list --enabled \
    --filter="config.name:(run.googleapis.com OR firestore.googleapis.com OR secretmanager.googleapis.com OR cloudbuild.googleapis.com OR artifactregistry.googleapis.com)" \
    --format="value(config.name)" 2>/dev/null | wc -l | tr -d ' ')
  [ "$LIGADAS" -ge 5 ] && break
  printf '        propagando… (%s/5 ligadas, tentativa %s)\n' "$LIGADAS" "$tentativa"
  sleep 10
done
[ "$LIGADAS" -ge 5 ] || parar "só $LIGADAS de 5 APIs ligaram." \
  "Confira o faturamento do projeto — sem billing ativo, Run e Build não ligam."
verde "5 APIs ligadas"

# --- 2. Firestore -----------------------------------------------------------

etapa "2/8  Firestore"

if gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  LOCAL=$(gcloud firestore databases describe --database='(default)' --format='value(locationId)')
  if [ "$LOCAL" != "$REGION" ]; then
    parar "o banco já existe em '$LOCAL', mas o serviço vai para '$REGION'." \
      "A região é PERMANENTE. Ou apague e recrie o banco, ou rode com REGION=$LOCAL."
  fi
  verde "banco já existe em $LOCAL"
else
  gcloud firestore databases create --location="$REGION" --type=firestore-native \
    >/dev/null 2>&1 || parar "não consegui criar o banco." \
    "Rode à mão para ver o erro: gcloud firestore databases create --location=$REGION --type=firestore-native"
  verde "banco criado em $REGION (região permanente)"
fi

# --- 3. Permissões ----------------------------------------------------------

etapa "3/8  Permissões da conta de serviço"

NUMERO=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null)
[ -n "$NUMERO" ] || parar "não consegui ler o número do projeto."
SA="$NUMERO-compute@developer.gserviceaccount.com"

for PAPEL in roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role="$PAPEL" --quiet >/dev/null 2>&1
done

TEM=$(gcloud projects get-iam-policy "$PROJECT" \
  --flatten="bindings[].members" \
  --filter="bindings.members:$SA AND bindings.role:(roles/datastore.user OR roles/secretmanager.secretAccessor)" \
  --format="value(bindings.role)" 2>/dev/null | sort -u | wc -l | tr -d ' ')

# Sem isto o serviço sobe e quebra na primeira mensagem, e o erro só aparece no
# log do Cloud Run — meia hora procurando no lugar errado.
[ "$TEM" -ge 2 ] || parar "a conta $SA ficou com $TEM de 2 papéis." \
  "Você precisa ser Owner/IAM Admin do projeto para conceder."
verde "$SA com datastore.user e secretmanager.secretAccessor"

# --- 4. Índices -------------------------------------------------------------

etapa "4/8  Índices do Firestore"

criar_indice() {
  local saida
  saida=$(gcloud firestore indexes composite create --collection-group="$COLECAO" "$@" 2>&1)
  case "$saida" in
    *ALREADY_EXISTS*|*already\ exists*) return 0 ;;
    *) [ $? -eq 0 ] && return 0 || { printf '        %s\n' "$saida" | head -3; return 1; } ;;
  esac
}

criar_indice --field-config=field-path=nicho,order=ascending \
             --field-config=field-path=telefone,order=ascending \
             --field-config=field-path=criado_em,order=descending
criar_indice --field-config=field-path=nicho,order=ascending \
             --field-config=field-path=criado_em,order=descending
criar_indice --field-config=field-path=nicho,order=ascending \
             --field-config=field-path=lead_quente,order=ascending \
             --field-config=field-path=criado_em,order=descending

QTD=$(gcloud firestore indexes composite list --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')
if [ "$QTD" -ge 3 ]; then
  verde "$QTD índices ($(gcloud firestore indexes composite list --format='value(state)' 2>/dev/null | sort -u | tr '\n' ' '))"
  amarelo "CREATING é normal — ficam prontos em alguns minutos, não bloqueia o deploy"
else
  amarelo "só $QTD índices apareceram; confira depois com:"
  printf '        gcloud firestore indexes composite list --format="value(name,state)"\n'
fi

# --- 5. Verify token --------------------------------------------------------

etapa "5/8  Verify token do webhook"

if [ -s "$ARQUIVO_TOKEN" ]; then
  VERIFY_TOKEN=$(cat "$ARQUIVO_TOKEN")
  verde "reaproveitando o de $ARQUIVO_TOKEN"
else
  VERIFY_TOKEN=$(openssl rand -hex 24)
  umask 077 && printf '%s' "$VERIFY_TOKEN" > "$ARQUIVO_TOKEN"
  verde "gerado e salvo em $ARQUIVO_TOKEN"
fi
printf '        \033[1m%s\033[0m\n' "$VERIFY_TOKEN"
amarelo "esse MESMO valor vai no formulário de webhook da Meta"

# --- 6. Secret Manager ------------------------------------------------------

etapa "6/8  Secret Manager"

for S in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  gcloud secrets create "$S" --replication-policy=automatic >/dev/null 2>&1
done

# printf, nunca echo: o \n do echo vai junto no valor, e a Meta recusa o token
# com um erro que não menciona espaço em branco nenhum.
guardar() {
  printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null 2>&1 \
    && verde "$1 preenchido" || parar "não consegui gravar $1."
}

ATUAL_VT=$(gcloud secrets versions access latest --secret=WHATSAPP_VERIFY_TOKEN 2>/dev/null)
[ "$ATUAL_VT" = "$VERIFY_TOKEN" ] && verde "WHATSAPP_VERIFY_TOKEN já em dia" \
  || guardar WHATSAPP_VERIFY_TOKEN "$VERIFY_TOKEN"

if gcloud secrets versions access latest --secret=GEMINI_API_KEY >/dev/null 2>&1; then
  verde "GEMINI_API_KEY já preenchida"
else
  printf '\n  Chave do Gemini — https://aistudio.google.com/apikey (projeto %s)\n' "$PROJECT"
  printf '  Cole aqui (ou Enter para preencher depois): '
  read -rs CHAVE; echo
  if [ -n "$CHAVE" ]; then
    CODIGO=$(curl -s -o /dev/null -w '%{http_code}' \
      "https://generativelanguage.googleapis.com/v1beta/models?key=$CHAVE" 2>/dev/null)
    [ "$CODIGO" = "200" ] || parar "a Google recusou essa chave (HTTP $CODIGO)." \
      "Confira se ela foi criada no projeto $PROJECT."
    verde "chave validada na Google"
    guardar GEMINI_API_KEY "$CHAVE"
  else
    amarelo "GEMINI_API_KEY em branco — o deploy vai falhar sem ela"
  fi
fi

# --- 7. Situação dos segredos ----------------------------------------------

etapa "7/8  Situação dos quatro segredos"

FALTAM=()
for S in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  if gcloud secrets versions access latest --secret="$S" >/dev/null 2>&1; then
    verde "$S"
  else
    amarelo "$S — cofre criado, sem valor"
    FALTAM+=("$S")
  fi
done

# --- 8. Fim -----------------------------------------------------------------

etapa "8/8  Pronto"

if [ ${#FALTAM[@]} -eq 0 ]; then
  printf '\nGoogle Cloud completo. Falta só o Phone number ID da Meta:\n\n'
  printf '  bash scripts/deploy.sh SEU_PHONE_NUMBER_ID\n\n'
else
  printf '\nGoogle Cloud pronto. Quando a Meta liberar, preencha:\n\n'
  for S in "${FALTAM[@]}"; do
    printf "  printf 'COLE_AQUI' | gcloud secrets versions add %s --data-file=-\n" "$S"
  done
  printf '\n  (printf, não echo — o echo acrescenta \\n e a Meta recusa)\n'
  printf '\nDepois:  bash scripts/deploy.sh SEU_PHONE_NUMBER_ID\n\n'
fi
