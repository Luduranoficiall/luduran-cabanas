# Painel de acompanhamento

Roda no mesmo Cloud Run do agente, sob `/painel`. Serve para dar transparência
ao fechamento mensal: quanto o sistema atendeu, quantos leads tinham intenção
real de reserva, e o CSV que a Camile cruza com a planilha dela.

## Telas

| Rota | O que mostra |
| --- | --- |
| `/painel/login` | Entrada. E-mail e senha. |
| `/painel/` | Visão do mês: pessoas atendidas, leads quentes, links enviados, tempo médio, escalações. |
| `/painel/fechamento` | Fechamento do mês: leads quentes, conferência e totalizador. |
| `/painel/fechamento.csv` | Mesma lista já conferida, em CSV (`;` e BOM, abre direto no Excel). |
| `/painel/escalacoes` | Quem pediu humano e ainda espera. |
| `/painel/auditoria` | Trilha de acesso e conferência (só admin). |
| `/painel/telefone/{telefone}` | Conversa completa daquele número. |

## Acessos

| Quem | Papel | Enxerga | Confere |
| --- | --- | --- | --- |
| Lucas | `admin` | todos os nichos | sim |
| Camily | `operador` | só `cabanas` | sim |
| Adriano | `leitor` | só `cabanas` | **não** |

O Adriano é `leitor` de propósito: ele audita o fechamento, e quem audita não
deve poder editar o que audita. A conferência alimenta o cálculo da comissão.

```bash
python cabanas-agent/scripts/criar_usuario.py lucas@luduran.com   --papel admin
python cabanas-agent/scripts/criar_usuario.py camily@exemplo.com  --papel operador --nichos cabanas
python cabanas-agent/scripts/criar_usuario.py adriano@exemplo.com --papel leitor   --nichos cabanas

# tirar acesso (desativa e derruba as sessões abertas na hora)
python cabanas-agent/scripts/criar_usuario.py alguem@exemplo.com --desativar
```

A senha é pedida no terminal, sem eco — não passa por variável de ambiente nem
fica no histórico do shell. Mínimo de 12 caracteres.

## Por que login de verdade, e não link secreto

O painel mostra telefone de cliente final. Isso é dado pessoal sob a LGPD, e
link secreto vaza pelo histórico do navegador, pelo print no grupo do WhatsApp
e pelo `Referer`. O que está implementado:

- **Senha** com scrypt e sal por usuário. Não é reversível, e duas pessoas com
  a mesma senha têm hashes diferentes.
- **Sessão no servidor**, para conseguir revogar. No banco fica o SHA-256 do
  token, não o token — vazamento da base não dá sessão a ninguém.
- **Cookie** `HttpOnly` (JavaScript não lê), `SameSite=Lax` (site de terceiro
  não reaproveita), `Secure` (só HTTPS), escopo `/painel`, 8 horas.
- **Nicho conferido no servidor** em toda rota. Trocar `?nicho=academia` na
  URL devolve 403, não dado de outro cliente. Tem teste para exatamente essa
  tentativa.
- **Mensagem única de erro** no login: dizer "usuário não existe" entregaria
  quem tem conta a quem estiver testando e-mails. O tempo de resposta também é
  igualado, com um hash-isca.
- **Trava de tentativas**: 5 falhas em 15 minutos bloqueiam aquele e-mail+IP.
- **Auditoria**: login, falha de login e exportação de CSV vão para
  `painel_auditoria` com quem, quando e IP.
- **`noindex`** nas páginas, para não cair em buscador.

### Limites que valem saber

- A trava de tentativas vive na memória da instância. Com várias instâncias no
  Cloud Run ela é atrito, não barreira. Barreira de verdade é Cloud Armor na
  frente do serviço.
- **Retenção de dado não está definida.** A LGPD pede um prazo. Hoje a
  conversa fica guardada indefinidamente. Precisa de decisão sua sobre por
  quanto tempo manter e o que fazer depois (apagar ou anonimizar o telefone).
- Não há tela de gestão de usuários — é pelo script, de propósito: menos
  superfície exposta na internet.

## Fechamento mensal

O que a Camily faz, e só isso: abre o mês, confere e exporta. A lista já vem
pronta — nenhuma planilha montada do zero.

Cada linha traz **telefone**, **data e hora do contato**, **o que a pessoa
perguntou** (a primeira mensagem que a marcou como lead) e **por que virou
lead** (os sinais). Ao lado, os campos que ela preenche:

| Campo | Para quê |
| --- | --- |
| ☑ Reserva? | virou reserva de fato no Airbnb |
| Valor da reserva | quanto foi, em reais — é a base dos 10% |
| Observação | anotação livre (ex.: "3 noites") |

Salva a tabela inteira de uma vez. O totalizador em cima mostra leads quentes,
confirmadas, valor confirmado e a comissão.

### Por que o valor é digitado

O sistema sabe quem demonstrou intenção, mas **não sabe quanto a reserva
valeu** — ela é fechada no Airbnb, fora daqui, e pode ser de uma ou de várias
noites, com desconto ou taxa. Calcular a comissão a partir da diária de R$150
daria um número que não bate com o extrato do Airbnb, e o Adriano confere caso
a caso.

Por isso: a marcação mínima é o checkbox, e o valor é opcional. Se uma reserva
for confirmada sem valor, o painel **não** finge que fechou — mostra o aviso
"comissão subestimada" na tela e no rodapé do CSV, com a contagem de quantas
faltam.

### Auditoria da conferência

Toda alteração vira registro em `painel_auditoria`, com o de-para:

```
camily@exemplo.com | cabanas 2026-03 5554999990001:
    sem conferência -> confirmada R$ 450,00
camily@exemplo.com | cabanas 2026-03 5554999990001:
    confirmada R$ 450,00 -> confirmada R$ 600,00
```

Salvar sem mudar nada não gera registro — a trilha fica limpa para o Adriano
ler. Valores ficam em **centavos, inteiro**: somar float acumula diferença de
centavo, e centavo em acerto de comissão vira discussão.

O CSV traz o rodapé com leads quentes, confirmadas, valor e comissão, com
vírgula decimal e sem "R$" — assim o Excel soma a coluna em vez de tratá-la
como texto.

## Escalações

O aviso vai para a secretária (+55 54 98448-7198), que segue no WhatsApp
normal. O sistema roda num chip próprio, então não há conflito de número.

> ⚠️ **Enquanto o template não for aprovado, o aviso não chega.** A Cloud API
> só entrega texto livre dentro de 24h da última mensagem que o destinatário
> mandou para o sistema, e a secretária nunca escreve para o número do sistema.
> Com `ESCALATION_TEMPLATE` configurado, entrega sempre — ver passo 6 do
> [DEPLOY.md](DEPLOY.md).
>
> Até lá, **esta tela é a fonte** de quem está esperando. Vale abrir todo dia.
> Quando o aviso falha, o log diz `Aviso de escalação NÃO entregue`.

## Auditoria

`/painel/auditoria`, só para admin — quem é auditado não enxerga a própria
trilha. Mostra login, falha de login, exportação de CSV e cada alteração de
conferência com o valor antes e depois. É o que sustenta o fechamento quando o
Adriano pedir para conferir caso a caso.

## Métricas

- **Pessoas atendidas** conta telefones distintos; o número de mensagens vem
  logo abaixo.
- **Leads quentes** também conta pessoa, não mensagem. Quem mandou cinco
  mensagens quentes é um lead, não cinco.
- **Links enviados** conta envio, não clique. O clique acontece no Airbnb,
  fora deste sistema — está escrito na própria tela para não gerar
  interpretação errada no fechamento.
- **Tempo médio** é `respondido_em - criado_em`, ou seja, o tempo que o sistema
  levou. Não inclui a viagem da mensagem até o aparelho da pessoa.
- **Mês** é contado no fuso de Brasília (UTC-3 fixo; o Brasil acabou com o
  horário de verão em 2019). Sem isso, março começaria às 21h de fevereiro.

## Rodar local

```bash
GCP_PROJECT_ID= COOKIE_SEGURO=0 uvicorn app.main:app --reload --port 8080
```

Com `GCP_PROJECT_ID` vazio, agente e painel sobem em memória — dá para navegar
sem tocar no Firestore. Nesse modo não há usuários cadastrados; crie um no
próprio processo ou aponte para o Firestore de verdade.

## Deploy

Nada muda no deploy do agente: é o mesmo serviço. Só acrescente as variáveis
`NICHOS_PAINEL` e `COOKIE_SEGURO=1`, e crie os índices do Firestore
(`firestore.indexes.json`) — o painel consulta por nicho e período.
