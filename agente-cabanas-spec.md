# Agente IA — Cabanas

**Cliente:** Adriano · **Operação:** Camile
**Stack:** Gemini API (Google) + WhatsApp Cloud API (Meta) + Cloud Run
**Projeto GCP:** `serious-trainer-465716-j9` · **Região:** `us-central1`

Implementação em [`cabanas-agent/`](cabanas-agent/).

## 1. Dados confirmados do negócio

| Item | Valor |
| --- | --- |
| Diária | R$150,00 |
| Total de cabanas | 5 |
| Alta disponibilidade | Dias de semana (seg–qui) |
| Baixa disponibilidade | Fins de semana |
| Canal de reserva | Airbnb (link direto por cabana) |
| Responsável operacional | Camile |
| Proprietário | Adriano |

Links das cabanas:

- cabana1 → https://airbnb.com.br/h/1992cabana1
- cabana2 → https://airbnb.com.br/h/1992cabana2
- cabana3 → https://airbnb.com.br/h/1992cabana3
- cabana4 → https://airbnb.com.br/h/1992cabana4
- cabana5 → https://airbnb.com.br/h/1992cabana5

> ✅ **Resolvido:** a cabana 3 existe e vai entrar. O anúncio dela ainda não foi
> criado no Airbnb, então o link acima é o esperado, mas ainda não vale.
>
> **No ar hoje:** `CABANAS=1,2,4,5` — quatro cabanas.
>
> **Quando o link chegar**, ativar por configuração, sem deploy de código:
>
> ```bash
> CABANAS=1,2,3,4,5
> CABANA_URLS=3=https://airbnb.com.br/h/o-link-que-vier
> ```
>
> Cabana listada em `CABANAS` sem link cadastrado fica fora do ar de propósito,
> com erro no log e no `/health`. O agente não deriva URL por padrão de nome:
> link chutado vira link quebrado na mão do cliente.

**Contato oficial:** +55 54 98448-7198 (secretária do clube). É o número que o
agente atende e também o que recebe as escalações.

## 2. System prompt (Gemini)

Fonte de verdade: [`cabanas-agent/app/prompts.py`](cabanas-agent/app/prompts.py).
A lista de cabanas é montada a partir da configuração, então prompt e links
nunca saem de sincronia.

```
Você é o atendente virtual das cabanas. Seu papel é responder rápido,
com clareza e simpatia, quem chega pelo WhatsApp interessado em hospedagem.

## SUAS INFORMAÇÕES
- Diária: R$150,00
- São 5 cabanas disponíveis
- Dias de semana costumam ter mais disponibilidade que finais de semana
- Toda reserva é feita diretamente pelo Airbnb, através dos links abaixo:
  - Cabana 1: https://airbnb.com.br/h/1992cabana1
  - Cabana 2: https://airbnb.com.br/h/1992cabana2
  - Cabana 3: https://airbnb.com.br/h/1992cabana3
  - Cabana 4: https://airbnb.com.br/h/1992cabana4
  - Cabana 5: https://airbnb.com.br/h/1992cabana5

## COMO RESPONDER
- Português brasileiro, tom acolhedor e profissional. Sem gírias, sem erros.
- Mensagens curtas, separadas em parágrafos de uma ideia cada.
- Máximo de 3 parágrafos por resposta.
- Use no máximo 1 emoji por mensagem, e só quando fizer sentido.
- Nunca invente informação que não esteja aqui.

## FLUXO PADRÃO
1. Cumprimente e responda diretamente o que a pessoa perguntou.
2. Informe a diária (R$150,00) quando o assunto for preço.
3. Se perguntarem sobre disponibilidade, explique que dias de semana
   costumam ter mais vaga, e envie o link para a pessoa consultar as
   datas exatas e reservar.
4. Sempre envie o link do Airbnb quando houver intenção de reserva.

## REGRAS CRÍTICAS
- Você NÃO confirma reservas. A reserva é sempre feita pelo cliente,
  direto no Airbnb, pelo link.
- Você NÃO tem acesso ao calendário em tempo real. Nunca afirme que
  uma data específica está livre ou ocupada. Direcione para o link,
  onde a disponibilidade real aparece.
- Você NÃO negocia preço, desconto ou condição especial.
- Você NÃO fornece endereço exato, dados bancários, nem informações
  sobre outros negócios do proprietário.

## QUANDO ESCALAR PARA HUMANO
Encaminhe para atendimento humano (e avise a pessoa que alguém vai
responder em breve) nos casos:
- Pedido de desconto ou condição especial
- Reclamação, problema com reserva existente, ou pedido de reembolso
- Pergunta sobre evento, grupo grande, ou uso comercial do espaço
- Qualquer assunto fora de hospedagem nas cabanas
- A pessoa pedir explicitamente para falar com uma pessoa

Nesses casos responda algo como: "Vou passar sua mensagem para nossa
equipe, que já retorna para você por aqui."
```

**Reforço em código:** os quatro primeiros gatilhos de escalação também são
detectados por palavra-chave em `app/intents.py`, *antes* de chamar o modelo.
Se a mensagem casar com um gatilho, a resposta é fixa e o Gemini não é
consultado — o modelo não tem chance de improvisar uma negociação. O quinto
gatilho ("qualquer assunto fora de hospedagem") é aberto demais para regra e
fica a cargo do modelo.

## 3. Fluxo de conversa (mapeado)

| Intenção | Exemplos | Resposta |
| --- | --- | --- |
| preço | "Quanto custa?" / "Qual o valor da diária?" | diária R$150,00 → oferece o link |
| disponibilidade | "Tem vaga pra sexta?" / "Está livre dia 12?" | dias de semana têm mais vaga → não confirma data → envia link |
| reserva | "Quero reservar" / "Como faço?" | reserva é feita pelo Airbnb → envia link |
| qual cabana / diferenças | "Quantas cabanas tem?" / "Qual a diferença?" | são 5 cabanas → envia os links |
| fora do escopo | desconto, evento, reclamação | escala para humano |

Cada linha tem teste em [`cabanas-agent/tests/test_flows.py`](cabanas-agent/tests/test_flows.py).

## 4. Arquitetura

```
WhatsApp (Meta Cloud API)
        │
        ▼  webhook POST
┌──────────────────────┐
│  Cloud Run (FastAPI) │
│  ─────────────────── │
│  /webhook   → recebe │
│  /health    → check  │
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
 Gemini API   Firestore
 (resposta)   (histórico +
              contador de
              leads p/ CRM)
```

**Por que Firestore:** o Adriano pediu um painel de acompanhamento para o
fechamento mensal dos 10%. Registrar cada conversa (timestamp, telefone, se o
link foi enviado) desde o dia 1 é o que vai alimentar esse painel depois — sem
isso, não tem como comprovar o que veio pelo sistema.

**Duas decisões de implementação que valem registro:**

- O webhook responde `200` imediatamente e processa em background. A Meta
  reenvia a notificação se não receber resposta rápido; chamar Gemini e
  Firestore antes de responder faria o agente responder duas vezes.
- O ID do documento no Firestore é o `message_id` da Meta. Como a criação falha
  se o documento já existe, reentrega da mesma mensagem é descartada de forma
  atômica.

## 5. Estrutura de pastas

```
cabanas-agent/
├── app/
│   ├── main.py              # FastAPI + rotas
│   ├── webhook.py           # verificação + recebimento Meta
│   ├── gemini_client.py     # chamada ao Gemini
│   ├── prompts.py           # system prompt (seção 2)
│   ├── intents.py           # intenções (seção 3) + trava de escalação
│   ├── whatsapp_client.py   # envio de mensagem
│   ├── storage.py           # Firestore: log de conversas
│   └── config.py            # env vars
├── tests/
│   └── test_flows.py        # casos da seção 3
├── firestore.indexes.json   # índice composto do histórico
├── Dockerfile
├── requirements.txt
└── .env.example
```

`intents.py` é o único acréscimo à estrutura original: a classificação de
intenção e a trava de escalação precisavam de um lugar testável, separado do
transporte HTTP.

## 6. Variáveis de ambiente

```bash
GEMINI_API_KEY=
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=              # ID da Meta, NÃO o telefone (ver abaixo)
WHATSAPP_PHONE_NUMBER=+55 54 98448-7198  # só conferência, não vai em API
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=                   # valida a assinatura do webhook
GCP_PROJECT_ID=serious-trainer-465716-j9
FIRESTORE_COLLECTION=cabanas_leads
ESCALATION_NUMBER=5554984487198        # +55 54 98448-7198, só dígitos
CABANAS=1,2,4,5                        # cabanas no ar
CABANA_URLS=                           # links avulsos, ex.: 3=https://...
```

Em produção: usar Secret Manager, não `.env` no container.

> ⚠️ **`WHATSAPP_PHONE_NUMBER_ID` não é o telefone.** É um ID numérico de ~15
> dígitos que a Meta gera para o número dentro da WhatsApp Business Account, e
> não tem relação com o DDD. Pegar em **App → WhatsApp → API Setup**, campo
> *Phone number ID*. Preencher com `5554984487198` faz toda chamada de envio
> falhar com erro 400. O telefone em si ficou em `WHATSAPP_PHONE_NUMBER`, que
> serve só para conferência e aparece no `/health`.

`ESCALATION_NUMBER` vai sem `+` e sem pontuação — é o formato que a Cloud API
aceita no campo `to`.

`WHATSAPP_APP_SECRET`, `WHATSAPP_PHONE_NUMBER`, `ESCALATION_NUMBER` e
`CABANA_URLS` não estavam na spec original. Os dois primeiros por segurança e
clareza; os dois últimos porque sem eles a escalação não chega a ninguém e
ligar uma cabana nova exigiria mexer em código.

## 7. Checklist antes de ativar

- [x] Confirmar com a Camile se cabana3 existe — existe; falta o link do Airbnb
- [ ] Receber o link da cabana 3 e ativar via `CABANAS` + `CABANA_URLS`
- [ ] Pedir fotos das cabanas — pasta `assets/cabanas/` criada, aguardando
- [x] Testar os 5 fluxos da seção 3 em ambiente de teste — 45 testes, `pytest`
- [ ] Validar que o agente nunca confirma data específica — exige teste com o
      modelo real; a regra está no prompt, mas só staging comprova
- [x] Validar que o agente escala corretamente pedido de desconto — coberto por
      teste, e a trava roda antes do modelo
- [x] Confirmar número oficial do WhatsApp — +55 54 98448-7198
- [x] Definir para qual número vai a escalação humana — mesmo número
- [ ] Pegar o *Phone number ID* na Meta e preencher `WHATSAPP_PHONE_NUMBER_ID`
      (não é o telefone — ver seção 6)
- [ ] Deploy no Cloud Run + configurar webhook na Meta
- [ ] Criar o índice do Firestore (`firestore.indexes.json`)
- [ ] Rodar 24h em observação antes de anunciar como "no ar"

## 8. Limitação conhecida do painel dos 10%

O agente registra que o link do Airbnb **foi enviado**. Ele não consegue saber
se a pessoa **clicou**, porque o clique acontece no domínio do Airbnb.

Para medir clique de verdade, o caminho é servir um link próprio
(`cabanas.exemplo/c/3`) que registra o acesso e redireciona para o Airbnb. O
schema do Firestore já reserva o campo `clicou_em` para quando isso for feito.
Vale alinhar com o Adriano qual métrica vai valer para o fechamento mensal
antes de ligar o sistema.
