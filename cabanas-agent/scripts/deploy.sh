#!/usr/bin/env bash
#
# Sobe o serviço no Cloud Run e confere que ele respondeu certo.
#
#   bash scripts/deploy.sh 123456789012345
#                          └─ Phone number ID da Meta (~15 dígitos, NÃO o telefone)
#
# Confere os segredos antes de gastar um build de 3 minutos, faz o deploy e
# valida o /health. No fim, imprime exatamente o que colar no formulário de
# webhook da Meta.

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

ID="${1:-}"
[ -n "$ID" ] || parar "falta o Phone number ID." "Uso: bash scripts/deploy.sh 123456789012345"

# --- 1. Conferir antes de gastar um build ----------------------------------

etapa "1/4  Conferindo antes do build"

case "$ID" in
  *[!0-9]*) parar "'$ID' não é numérico." "O Phone number ID só tem dígitos. Ver EXECUTAR-AGORA.md, bloco B3." ;;
esac

SO_DIGITOS=$(printf '%s' "$TELEFONE" | tr -cd '0-9')
[ "$ID" != "$SO_DIGITOS" ] || parar "você colou o TELEFONE no lugar do ID." \
  "O Phone number ID é outro número, que só aparece depois de cadastrar o chip na Meta."
verde "Phone number ID $ID"

for S in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  gcloud secrets versions access latest --secret="$S" >/dev/null 2>&1 \
    || parar "o segredo $S está vazio." \
       "printf 'COLE_AQUI' | gcloud secrets versions add $S --data-file=-"
done
verde "quatro segredos preenchidos"

# --- 2. Deploy --------------------------------------------------------------

etapa "2/4  Deploy (leva ~3 min)"

cd "$RAIZ" || parar "não achei $RAIZ"

# O ^|^ troca o separador de vírgula por barra: WHATSAPP_PHONE_NUMBER tem
# vírgula nenhuma, mas tem espaço, e o telefone com formatação passa direto.
gcloud run deploy "$SERVICO" \
  --source . \
  --project="$PROJECT" \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-env-vars="^|^GCP_PROJECT_ID=$PROJECT|FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION:-cabanas_leads}|NICHO=${NICHO:-cabanas}|NICHOS_PAINEL=${NICHOS_PAINEL:-cabanas}|COOKIE_SEGURO=1|COMISSAO_PERCENTUAL=${COMISSAO_PERCENTUAL:-10}|WHATSAPP_PHONE_NUMBER_ID=$ID|WHATSAPP_PHONE_NUMBER=$TELEFONE|ESCALATION_NUMBER=$ESCALACAO" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,WHATSAPP_VERIFY_TOKEN=WHATSAPP_VERIFY_TOKEN:latest,WHATSAPP_APP_SECRET=WHATSAPP_APP_SECRET:latest" \
  || parar "o deploy falhou." "Veja o log do build: gcloud builds list --limit=1 --project=$PROJECT"

URL=$(gcloud run services describe "$SERVICO" --project="$PROJECT" --region="$REGION" \
      --format='value(status.url)' 2>/dev/null)
[ -n "$URL" ] || parar "o deploy passou mas não consegui ler a URL."
verde "$URL"

# --- 3. Conferir o que subiu ------------------------------------------------

etapa "3/4  Conferindo o serviço"

SAUDE=$(curl -s --max-time 30 "$URL/health")
printf '%s\n' "$SAUDE" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$SAUDE"

confere() { printf '%s' "$SAUDE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1'))" 2>/dev/null; }

[ "$(confere config_faltando)" = "[]" ] || parar "config_faltando não está vazio." \
  "O webhook vai falhar. Confira as variáveis do deploy."
verde "config_faltando vazio"

[ "$(confere cabanas_sem_link)" = "[]" ] || amarelo "há cabana sem link — ela fica fora do ar de propósito"
verde "cabanas com link: $(confere cabanas)"

VT=$(gcloud secrets versions access latest --secret=WHATSAPP_VERIFY_TOKEN 2>/dev/null)
RESP=$(curl -s --max-time 20 "$URL/webhook?hub.mode=subscribe&hub.verify_token=$VT&hub.challenge=42")
[ "$RESP" = "42" ] || parar "o handshake do webhook respondeu '$RESP', esperado '42'." \
  "O WHATSAPP_VERIFY_TOKEN do Secret Manager não bate com o que o serviço leu."
verde "handshake do webhook responde certo"

# --- 4. O que falta, na Meta ------------------------------------------------

etapa "4/4  Falta só a Meta"

cat <<FIM

  App → WhatsApp → Configuração → Webhook → Editar

    URL:    $URL/webhook
    Token:  $VT

  Salvar → Gerenciar → assinar o campo  messages

  Esquecer de assinar 'messages' é o erro mais comum: a URL fica salva, a
  verificação passa, e nenhuma mensagem chega.

  Depois, crie os usuários do painel (a primeira linha só na primeira vez):

    pip install -q -r requirements.txt
    python scripts/criar_usuario.py lucas@luduran.com   --papel admin
    python scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
    python scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas

  E teste de um celular que NÃO seja o do sistema:

    "Quanto custa a diária?"      → R\$150,00 + link do Airbnb
    "Tem vaga dia 12? Somos 4"    → responde e vira lead quente
    "Faz desconto?"               → escalação, aparece em $URL/painel/escalacoes

  Painel: $URL/painel/

FIM
