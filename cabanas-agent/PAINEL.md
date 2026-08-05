# Painel de acompanhamento

Roda no mesmo Cloud Run do agente, sob `/painel`. Serve para dar transparência
ao fechamento mensal: quanto o sistema atendeu, quantos leads tinham intenção
real de reserva, e o CSV que a Camile cruza com a planilha dela.

## Telas

| Rota | O que mostra |
| --- | --- |
| `/painel/login` | Entrada. E-mail e senha. |
| `/painel/` | Visão do mês: pessoas atendidas, leads quentes, links enviados, tempo médio, escalações. |
| `/painel/fechamento` | Lista de leads quentes do mês, com os sinais que marcaram cada um. |
| `/painel/fechamento.csv` | Mesma lista em CSV (`;` e BOM, abre direto no Excel em português). |
| `/painel/telefone/{telefone}` | Conversa completa daquele número. |

## Acessos

| Quem | Papel | Enxerga |
| --- | --- | --- |
| Lucas | `admin` | todos os nichos |
| Adriano | `leitor` | só `cabanas` |
| Camile | `leitor` | só `cabanas` |

```bash
python cabanas-agent/scripts/criar_usuario.py lucas@luduran.com   --papel admin
python cabanas-agent/scripts/criar_usuario.py adriano@exemplo.com --nichos cabanas
python cabanas-agent/scripts/criar_usuario.py camile@exemplo.com  --nichos cabanas

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
