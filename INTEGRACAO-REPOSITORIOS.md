# Triagem dos 11 repositórios

Li os onze. Este documento diz o que cada um é, o que vale trazer, e o que
**não** trazer — com o motivo.

**Nada do que já existe foi tocado.** As 8 branches estão publicadas, 226
testes passando, e a demo aprovada continua travada por hash.

## O quadro

| Repositório | O que é | Decisão |
| --- | --- | --- |
| **DeskcommCRM** | CRM multi-tenant Next.js + Supabase, WhatsApp via WAHA, RAG por tenant, LGPD by-design | 🟡 **decisão estratégica** — ver abaixo |
| **wacrm** | CRM template WhatsApp, Next.js + Supabase (fork de ArnasDon) | 🟡 sobrepõe o DeskcommCRM |
| **evolution-go** | API WhatsApp **não-oficial** em Go (95 MB) | 🔴 **conflita com o que foi construído** |
| **whatsapp-agentkit** | Guia para montar agente de WhatsApp com Claude Code | ⚪ conceitual; já fizemos |
| **MaxKB** | Plataforma RAG/agentes enterprise (95 MB) | ⚪ grande demais para 5 cabanas |
| **Chat2DB** | Cliente SQL com IA (66 MB) | ⚪ ferramenta de dev, não do produto |
| **free-llm-api-resources** | Lista de APIs LLM gratuitas | ⚪ referência |
| **skills** | Agent Skills do Google | ⚪ referência |
| **cel-python** | Common Expression Language para Python (48 MB) | ⚪ biblioteca genérica |
| **OmniCloud** | Agregador de cloud drives (Vue + Express) | ⚪ não relacionado |
| **FreeDomain** | Domínios gratuitos DigitalPlat | 🟢 **útil de graça** — domínio para o painel |

## ✅ O que trouxe agora

### Política de retenção LGPD (do DeskcommCRM)

Era a **única pendência que bloqueava o lançamento**. O DeskcommCRM já opera
uma regra madura, e o cliente já vive com ela:

> **Anonimização preferida sobre delete físico** · audit append-only ·
> D+7 para exportação, D+15 para anonimização

Trouxe essa regra. O detalhe que faz ela funcionar aqui:

- **Sai:** telefone e o texto das mensagens.
- **Fica:** nicho, intenção, lead quente, sinais, datas, conferência.
- O telefone vira um apelido derivado por hash com sal, **sempre o mesmo para
  o mesmo número** — então "pessoas atendidas" e "leads quentes" continuam
  contando gente, não linhas.

Ou seja: **o dado pessoal some e o número dos 10% continua de pé.** Tem teste
provando que as métricas do mês são idênticas antes e depois.

```bash
RETENCAO_DIAS=365 python cabanas-agent/scripts/anonimizar.py            # confere
RETENCAO_DIAS=365 python cabanas-agent/scripts/anonimizar.py --aplicar  # grava
```

Vem **desligado** (`RETENCAO_DIAS=0`). Prazo é decisão de negócio, e um padrão
errado apagaria dado de cliente sozinho.

> ⚠️ O prazo tem que ser **maior que o ciclo de fechamento**. O texto da
> conversa some, e é ele que responde "por que este lead foi marcado como
> quente?" quando o Adriano confere caso a caso. Os sinais ficam, o texto não
> volta. Sugestão: 12 meses.

### Domínio (FreeDomain)

O painel vai ficar numa URL `*.run.app`, que não passa confiança para o
Adriano e a Camily. Um domínio do DigitalPlat resolve de graça. Não é urgente
e não bloqueia nada.

## 🔴 O conflito que precisa de decisão sua

### evolution-go **ou** Meta Cloud API — não os dois

Todo o trabalho de deploy foi construído sobre a **Cloud API oficial da Meta**:
o chip novo, o `Phone number ID`, a assinatura do webhook, a janela de 24h, o
template de escalação, os 15 passos do `DEPLOY.md`.

O evolution-go é uma API **não-oficial** (baseada em biblioteca que emula o
WhatsApp Web). São mundos diferentes:

| | Cloud API (o que temos) | evolution-go |
| --- | --- | --- |
| Oficial | sim | não |
| Risco de banimento do número | nenhum | real |
| Janela de 24h / templates | sim | não se aplica |
| Custo | grátis até o volume atual | grátis, mas precisa de servidor 24/7 |
| O que já está pronto | tudo | nada |

Adotar o evolution-go **joga fora o `DEPLOY.md` inteiro** e coloca o número do
clube sob risco de banimento — o mesmo número que a operação vai usar todo dia.

**Minha recomendação:** ficar na Cloud API. O evolution-go faz sentido quando o
custo por conversa da Meta pesa, e esse não é o caso com 5 cabanas.

## 🟡 A decisão do CRM — antes de escrever integração

O DeskcommCRM **já faz** boa parte do que construímos:

| | Nosso painel | DeskcommCRM |
| --- | --- | --- |
| Atendimento por IA | Gemini + Cloud API | RAG por tenant + WAHA |
| Inbox humano | não | sim |
| Multi-nicho / multi-tenant | sim (`nicho`) | sim (tenant) |
| Fechamento com comissão | sim, com conferência e CSV | não |
| Pipeline / pós-venda | não | sim |
| Vocabulário | hospedagem | e-commerce |

Três caminhos, e o risco de escolher errado é concreto:

1. **Manter os dois separados** — o agente das cabanas continua como está, o
   CRM atende os outros nichos. Simples, mas duplica esforço.
2. **CRM como destino dos leads** — o agente empurra lead quente para o
   DeskcommCRM via API. O fechamento continua nosso.
3. **Migrar para o DeskcommCRM** — joga fora o painel. O vocabulário dele é de
   e-commerce ("Carrinho abandonado → Pago → Enviado"), não de hospedagem, e o
   fechamento com comissão de 10% teria que ser construído lá.

> ⚠️ **O risco que vale nomear:** se o painel e o CRM contarem lead quente cada
> um do seu jeito, o Adriano recebe **dois números diferentes** e nenhum se
> sustenta na conferência caso a caso. Decida quem é dono do número **antes**
> de escrever a primeira linha de integração.

**Minha recomendação:** caminho 2, e só depois do sistema estar no ar e rodando
as 24h de observação. Integrar antes de ter o primeiro lead real é otimizar no
escuro.

## ⚪ O que não trazer, e por quê

MaxKB, Chat2DB, cel-python, OmniCloud e evolution-go somam **~300 MB** de
código de terceiros sem relação com atendimento de cabanas. Copiar para cá:

- enterra um sistema que funciona, com 226 testes, sob código que ninguém
  daqui mantém;
- torna impossível responder "o que mudou?" numa revisão;
- traz licenças e dependências de segurança de projetos que não escolhemos.

Eles continuam onde estão, no GitHub, disponíveis quando fizerem falta. Trazer
para o repositório não os torna mais acessíveis — só mais difíceis de ignorar.

`free-llm-api-resources` e `skills` são listas de referência: valem consulta,
não cópia.

## Ordem sugerida

1. **Terminar o deploy** (`DEPLOY.md`) — o sistema no ar vale mais que qualquer
   integração no papel
2. **Definir o prazo de retenção** e ligar `RETENCAO_DIAS`
3. **24h de observação** com tráfego real
4. **Aí sim** decidir o caminho do CRM, com dado real na mesa
5. Domínio próprio, quando sobrar tempo
