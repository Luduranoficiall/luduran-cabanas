# Roadmap de Evolução — Luduran IA · Operação Cabanas

> **Regra de ouro:** nada aqui pode quebrar o que já foi aprovado pelo cliente.
> A demo atual e os 45 testes do agente são a linha de base. Toda mudança
> entra em cima, nunca no lugar.

## Estado atual

Em `main`: agente, painel, fechamento com conferência, 5 cabanas ativas.
Na branch `claude/deploy-e-auditoria`, aguardando revisão: checklist de deploy,
telas de escalações e auditoria.

| Item | Estado |
| --- | --- |
| 1.1 Cabanas na página (opção A, build) | ✅ |
| 2.3 Captura de intenção (lead quente) | ✅ |
| 2.5 Fallback do Gemini | ✅ |
| 3.1 Painel base | ✅ |
| 3.2 Acesso com login e três papéis | ✅ (virou admin / operador / leitor) |
| 3.3 Campo `nicho` no Firestore | ✅ |
| 3.4 Fechamento mensal com conferência e CSV | ✅ |
| 2.1 Memória de conversa | 🟡 falta o corte de 10 msg / 30 min |
| 2.4 Anti-loop | ⬜ |
| 1.2–1.4, 2.2, 2.6 | ⬜ |

**Total: 173 testes.**

### 🔴 Bloqueia o lançamento

1. **O aviso de escalação por WhatsApp não funciona.** `ESCALATION_NUMBER` é o
   mesmo número do atendimento, e a Cloud API recusa mensagem de um número para
   ele mesmo. Ninguém é avisado na hora. A tela `/painel/escalacoes` cobre o
   buraco, mas exige alguém abrindo todo dia. Ver passo 6 do `DEPLOY.md`.
2. **Migrar o número tira a secretária do WhatsApp Business.** É difícil de
   desfazer e muda a rotina do clube. Confirmar com a Camily e o Adriano.
3. **Prazo de retenção das conversas não definido** (LGPD).

---

## Parte 1 — Demo visual

O cliente aprovou a página como está. Estas são adições, não redesenho.

### 1.1 As 5 cabanas na página — ✅ feito (opção A)
`site/index.template.html` é a fonte; `scripts/gerar_site.py` gera o
`index.html` lendo a mesma configuração do agente. Sem endpoint público novo, e
a página não depende do agente estar no ar.

```bash
python cabanas-agent/scripts/gerar_site.py
git add index.html && git commit
```

Cabana sem link cadastrado não aparece — mesma trava do agente. Enquanto as
fotos não chegam, o cartão usa um bloco neutro no lugar da imagem.

A demo aprovada ficou intacta: **105 inserções, 0 remoções**.

> ⚠️ **Achado que precisa da sua decisão:** a conversa de exemplo, aprovada como
> está, manda `airbnb.com.br/h/1992cabana3` — anúncio que ainda não existe.
> Quem clicar ali cai em página quebrada. Não mexi por conta própria porque é
> conteúdo aprovado. Opções: trocar a demo para a cabana 1, ou deixar como está
> até o anúncio da 3 sair.

### 1.2 Prova de velocidade com dado real
Trocar o "~4 segundos" fixo por um número lido do próprio sistema depois que ele
estiver rodando (tempo médio de resposta dos últimos 30 dias). Enquanto não houver
dado, mantém o valor atual.

### 1.3 Versão para compartilhamento
Meta tags Open Graph + imagem de preview, para quando o link for colado no WhatsApp
aparecer com card bonito em vez de URL crua. Detalhe pequeno, impacto grande na
percepção de profissionalismo.

### 1.4 Responsividade em telas pequenas
Testar em 320px de largura. O phone mockup tem largura fixa de 340px — em celular
antigo isso estoura. Ajustar para `min(340px, 92vw)`.

---

## Parte 2 — Agente de IA

### 2.1 Memória de conversa (contexto) — 🟡 parcial
As últimas `HISTORY_LIMIT` mensagens daquele telefone já são buscadas no
Firestore e passadas ao Gemini, filtradas por nicho.

**Falta:** o corte por tempo. Hoje o limite é só por quantidade — uma conversa
de três semanas atrás ainda entra como contexto. Implementar "10 mensagens ou
30 minutos, o que vier primeiro".

### 2.2 Horário de atendimento inteligente
O agente responde 24h (esse é o valor vendido). Mas fora do horário comercial, avisar
que a equipe humana retorna no próximo dia útil — evita a pessoa esperando resposta
humana às 2h da manhã.

Horário do clube: seg–sex, 8h–18h (mesmo padrão que Lucas já usa na Luduran).

### 2.3 Captura de intenção de reserva — ✅ feito
Três sinais, gravados em `lead_quente` e `sinais_lead`:

| Sinal | Dispara com |
| --- | --- |
| `data_especifica` | "dia 12", "12/03", dia da semana, mês, feriadão |
| `numero_pessoas` | "4 pessoas", "somos 6", casal, família, criança |
| `pediu_reserva` | "quero reservar", "como faço para reservar", "vou querer" |

A detecção é **deliberadamente conservadora**. Essa métrica é a que sustenta a
conversa dos 10% com o Adriano: marcar lead quente demais infla justamente o
número que justifica a nossa própria comissão, e cai por terra quando ele
conferir caso a caso no fechamento. "Qual a política de reserva?" não conta
como intenção; "quero reservar" conta.

Escalação e lead quente são independentes — quem pede desconto para 6 pessoas
é lead quente *e* vai para humano.

Guardamos os sinais, não só o booleano, para a Camile conseguir ver *por que*
cada lead foi marcado.

### 2.4 Anti-loop
Se a mesma pessoa mandar mais de 15 mensagens em 10 minutos, parar de responder e
escalar. Protege contra bot, teste malicioso, e contra queimar cota do Gemini à toa.

### 2.5 Fallback quando o Gemini cai — ✅ feito
Já existia desde a primeira entrega: falha do modelo cai numa resposta fixa com
diária + link, nunca em silêncio.

**Fechado agora:** não havia timeout. Uma chamada travada ficava pendurada para
sempre e a pessoa não recebia nem o fallback. Teto em `GEMINI_TIMEOUT_S`
(12s por padrão).

### 2.6 Métricas no /health
Expor: total de conversas hoje, leads quentes hoje, tempo médio de resposta, última
falha do Gemini. Facilita diagnóstico sem abrir log.

---

## Parte 3 — Painel / CRM

Isso é o que o Adriano pediu explicitamente. Hoje não existe.

### 3.1 O que o painel precisa responder — ✅ feito
O Adriano fechou assim: **a Camile organiza a planilha do que vier pelo link, e a
Luduran tem 10%.** O painel serve para dar transparência aos dois lados:

| Métrica | Para quê |
|---|---|
| Conversas atendidas (mês) | Volume que o sistema absorveu |
| Leads quentes | Quem demonstrou intenção real de reserva |
| Links enviados | Quantos foram direcionados ao Airbnb |
| Tempo médio de resposta | Prova do valor entregue |
| Escalações para humano | Quanto ainda precisa de gente |
| Histórico por telefone | Consulta caso a caso no fechamento |

> ⚠️ "Links enviados" mede link **enviado**, não **clicado** — o clique acontece
> no domínio do Airbnb. Medir clique exige servir link próprio com redirect. O
> campo `clicou_em` já está reservado no schema. Alinhar com o Adriano qual
> métrica vale para o fechamento **antes** de ligar o sistema.

### 3.2 Acesso — ✅ feito
- **Lucas:** acesso total, todos os nichos
- **Adriano:** acesso somente leitura, só cabanas (por enquanto)
- **Camile:** acesso somente leitura, só cabanas

**Importante:** o painel guarda telefone de cliente final. Precisa de login de verdade,
não link secreto. E na LGPD isso é dado pessoal — só quem tem razão de negócio acessa.

### 3.3 Multi-nicho desde o início — ✅ feito
Todo documento nasce com `nicho` (vem de `NICHO`, padrão `cabanas`). O histórico
da conversa filtra por nicho, então a mesma pessoa falando com cabanas e com a
academia não mistura contexto. Índices do Firestore já preveem consulta por
nicho, por período e por lead quente.

### 3.4 Fechamento mensal — ✅ feito
Uma tela que, dado um mês, mostra os leads quentes daquele período em formato
exportável (CSV). É o que a Camile cruza com a planilha dela no fechamento.

### 3.5 Stack sugerida — decidido: enxuto do zero
Não tenho acesso ao repositório do ZENITH nesta sessão, então não deu para
avaliar o reaproveitamento. Feito enxuto: FastAPI renderizando HTML no servidor
(Jinja2), no mesmo Cloud Run do agente. Sem build de front, sem npm, sem
bundle — o painel tem cinco telas e uma tabela.

Se o ZENITH for reaproveitado depois, as rotas viram JSON sem mexer na camada
de consulta (`repositorio.py`), que já é separada da apresentação.

---

## Parte 4 — Ordem de execução

| Prioridade | Item | Estado |
|---|---|---|
| 1 | 2.3 Captura de intenção | ✅ |
| 2 | 3.3 Campo `nicho` no Firestore | ✅ |
| 3 | 2.5 Fallback do Gemini | ✅ |
| 4 | 2.1 Memória de conversa | 🟡 falta corte por tempo |
| 5 | 2.4 Anti-loop | ⬜ |
| 6 | 3.1–3.2 Painel base | ✅ |
| 7 | 1.1 Demo com as cabanas | ✅ |
| 7 | 1.2–1.4 Demo (velocidade real, OG, 320px) | ⬜ |
| 8 | 2.2, 2.6 | ⬜ |
| 8 | 3.4 Fechamento CSV | ✅ |

---

## Pendências externas (não dependem de código)

- [ ] Link da cabana 3 — Camily vai enviar
- [ ] Fotos das cabanas — Camily vai enviar (`assets/cabanas/`)
- [ ] `WHATSAPP_PHONE_NUMBER_ID` — Meta → App → WhatsApp → API Setup
- [ ] `WHATSAPP_TOKEN` permanente — não o temporário de 24h
- [ ] `WHATSAPP_APP_SECRET` — Configurações do app → Básico
- [ ] `GEMINI_API_KEY` — Google AI Studio
- [ ] Confirmar se o número +55 54 98448-7198 pode migrar para a Cloud API
- [ ] **Definir com o Adriano quem paga os custos de infraestrutura**
- [ ] GitHub Pages: Settings → Pages → branch `main` / root
- [ ] **Definir prazo de retenção das conversas** — a LGPD pede um prazo, e hoje
      o dado fica guardado indefinidamente
- [ ] Decidir sobre o link da cabana 3 na conversa de exemplo (ver 1.1)
- [ ] Criar os usuários do painel (`scripts/criar_usuario.py`)
