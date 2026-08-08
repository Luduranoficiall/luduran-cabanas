"""A demonstração que faltava: o atendente respondendo, e o que ele anota.

As regras vêm de regras.js, geradas do próprio app/intents.py — o navegador
decide escalação, intenção e lead quente com as mesmas expressões do servidor
(conferido frase a frase). O que muda em produção é só a redação da resposta,
que sai do Gemini.
"""

import base64, json, pathlib

AQUI = pathlib.Path(__file__).parent
FONTES = (AQUI / "fonts-inline.css").read_text()
FONTES_PAINEL = (AQUI / "fonts-inter.css").read_text()
REGRAS_JS = (AQUI / "regras.js").read_text()
TELAS_DIR = AQUI / "painel"

JS_DENTRO = (AQUI / "js_dentro.txt").read_text()


def tela_b64(nome: str) -> str:
    html = (TELAS_DIR / f"{nome}.html").read_text()
    html = html.replace("</head>", f"<style>{FONTES_PAINEL}</style></head>", 1)
    html = html.replace("</body>", JS_DENTRO + "</body>", 1)
    return base64.b64encode(html.encode()).decode()


TELAS = {n: tela_b64(n) for n in ("login", "painel", "fechamento", "escalacoes")}

LINKS = {str(n): f"https://airbnb.com.br/h/1992cabana{n}" for n in range(1, 6)}

SUGESTOES = [
    ("Quanto custa a diária?", "preço"),
    ("Tem vaga pro dia 12? Somos 4 pessoas", "disponibilidade"),
    ("Quero reservar pro fim de semana do dia 21", "reserva"),
    ("Quantas cabanas vocês têm?", "cabanas"),
    ("Faz por 100 a diária?", "escala p/ humano"),
]

chips = "\n".join(
    f'      <button type="button" class="chip-sug" data-texto="{t}">'
    f'{t}<span class="etq">{e}</span></button>'
    for t, e in SUGESTOES
)

HTML = f"""<title>Cabanas — o atendente funcionando</title>
<style>
{FONTES}

:root {{
  --paper:#FAF9F6; --surface:#FFFFFF; --ink:#15181D; --muted:#6E6862;
  --rule:#E4E0D8; --amber:#A9660A; --amber-fraco:#F5EBDC;
  --quente:#2C6B4A; --quente-fraco:#E6F0E9;
  --escala:#8C5410; --escala-fraco:#F7EEE0;
  --sombra:0 1px 2px rgba(21,24,29,.06), 0 8px 24px -12px rgba(21,24,29,.18);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper:#0F1217; --surface:#161A20; --ink:#E9E6E0; --muted:#9A948C;
    --rule:#252B33; --amber:#E8A94A; --amber-fraco:#2A2115;
    --quente:#6DBB90; --quente-fraco:#16241C;
    --escala:#DCA254; --escala-fraco:#261D11;
    --sombra:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
  }}
}}
:root[data-theme="dark"] {{
  --paper:#0F1217; --surface:#161A20; --ink:#E9E6E0; --muted:#9A948C;
  --rule:#252B33; --amber:#E8A94A; --amber-fraco:#2A2115;
  --quente:#6DBB90; --quente-fraco:#16241C;
  --escala:#DCA254; --escala-fraco:#261D11;
  --sombra:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
}}

*, *::before, *::after {{ box-sizing:border-box; }}
body {{ background:var(--paper); color:var(--ink); margin:0;
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:16.5px; line-height:1.62; -webkit-font-smoothing:antialiased; }}
.folha {{ max-width:1080px; margin:0 auto; padding:52px 24px 88px; }}
@media (max-width:640px) {{ .folha {{ padding:32px 16px 64px; }} }}

h1,h2 {{ font-family:'Space Grotesk',sans-serif; text-wrap:balance; margin:0; }}
h1 {{ font-size:clamp(28px,5vw,42px); font-weight:700; letter-spacing:-.022em; line-height:1.13; }}
h2 {{ font-size:clamp(20px,3vw,26px); font-weight:700; letter-spacing:-.014em; }}
p {{ margin:0; }} b {{ font-weight:600; }}
a {{ color:var(--amber); text-underline-offset:3px; }}
:focus-visible {{ outline:2px solid var(--amber); outline-offset:2px; border-radius:4px; }}

.rotulo {{ font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:600;
  letter-spacing:.13em; text-transform:uppercase; color:var(--muted); }}
.mono {{ font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums; }}

header.topo {{ display:flex; flex-direction:column; gap:15px;
  padding-bottom:28px; border-bottom:1px solid var(--rule); }}
.marca {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.marca .nome {{ font-family:'Space Grotesk',sans-serif; font-weight:700;
  letter-spacing:.04em; font-size:14px; }}
.marca .nome i {{ color:var(--amber); font-style:normal; }}
.linha-fina {{ color:var(--muted); font-size:17px; max-width:62ch; }}

section {{ margin-top:56px; display:flex; flex-direction:column; gap:18px; }}
.cabeca {{ display:flex; flex-direction:column; gap:7px; }}
.intro {{ color:var(--muted); max-width:66ch; }}

/* --- conversa --- */
.palco {{ display:grid; grid-template-columns:minmax(0,380px) minmax(0,1fr); gap:24px; align-items:start; }}
@media (max-width:820px) {{ .palco {{ grid-template-columns:1fr; }} }}

.fone {{ border:1px solid var(--rule); border-radius:16px; overflow:hidden;
  background:#0b141a; box-shadow:var(--sombra); display:flex; flex-direction:column; }}
.fone-topo {{ background:#1f2c33; padding:11px 15px; display:flex; align-items:center; gap:11px; }}
.fone-topo .bolha {{ width:32px; height:32px; border-radius:50%; background:#2f4a5a;
  display:grid; place-items:center; font-size:15px; }}
.fone-topo .quem {{ color:#e9edef; font-size:14px; font-weight:600; line-height:1.25; }}
.fone-topo .num {{ color:#8696a0; font-size:11.5px; font-family:'IBM Plex Mono',monospace; }}

.conversa {{ background:#0b141a; padding:16px 14px; display:flex; flex-direction:column;
  gap:9px; min-height:330px; max-height:460px; overflow-y:auto; }}
.msg {{ max-width:82%; padding:8px 11px; border-radius:8px; font-size:14.2px;
  line-height:1.48; white-space:pre-wrap; word-break:break-word; }}
.msg.deles {{ align-self:flex-end; background:#005c4b; color:#e9edef; border-bottom-right-radius:2px; }}
.msg.nossa {{ align-self:flex-start; background:#202c33; color:#e9edef; border-bottom-left-radius:2px; }}
.msg a {{ color:#8fd6ff; }}
.cartao-link {{ display:block; margin-top:8px; padding:10px 12px; border-radius:9px;
  background:#111c22; border:1px solid #2a3942; text-decoration:none; }}
.cartao-link:hover {{ border-color:#00a884; }}
.cartao-link .ct {{ display:block; color:#e9edef; font-weight:600; font-size:13.5px; }}
.cartao-link .cs {{ display:block; color:#8696a0; font-size:12px; margin-top:2px; }}
.cartao-link .cb {{ display:inline-block; margin-top:7px; color:#00d09c;
  font-size:12.5px; font-weight:600; }}
.hora {{ display:block; font-size:10.5px; color:#8696a0; text-align:right; margin-top:3px;
  font-family:'IBM Plex Mono',monospace; }}
.digitando {{ align-self:flex-start; background:#202c33; color:#8696a0;
  padding:8px 13px; border-radius:8px; font-size:13px; }}

.escrever {{ display:flex; gap:8px; padding:11px; background:#1f2c33; }}
.escrever input {{ flex:1; min-width:0; background:#2a3942; border:0; border-radius:20px;
  padding:9px 14px; color:#e9edef; font-size:14px; font-family:inherit; }}
.escrever input::placeholder {{ color:#8696a0; }}
.escrever button {{ background:#00a884; border:0; border-radius:50%; width:38px; height:38px;
  color:#0b141a; font-size:16px; cursor:pointer; flex:0 0 auto; }}

.chips {{ display:flex; flex-wrap:wrap; gap:7px; margin-top:13px; }}
.chip-sug {{ font-family:inherit; font-size:13.5px; text-align:left; cursor:pointer;
  background:var(--surface); color:var(--ink); border:1px solid var(--rule);
  border-radius:9px; padding:7px 11px; display:flex; align-items:center; gap:8px; }}
.chip-sug:hover {{ border-color:var(--amber); }}
.chip-sug .etq {{ font-family:'IBM Plex Mono',monospace; font-size:9.5px; font-weight:600;
  letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }}

/* --- fichas --- */
.fichas {{ display:flex; flex-direction:column; gap:11px; }}
.ficha {{ background:var(--surface); border:1px solid var(--rule); border-radius:11px;
  padding:14px 16px; box-shadow:var(--sombra); }}
.ficha .oq {{ font-size:14px; color:var(--muted); margin-bottom:9px; }}
.ficha .oq b {{ color:var(--ink); }}
.linhas {{ display:grid; grid-template-columns:auto 1fr; gap:6px 14px; font-size:13.5px; align-items:baseline; }}
.linhas dt {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; font-weight:600;
  letter-spacing:.09em; text-transform:uppercase; color:var(--muted); }}
.linhas dd {{ margin:0; }}
.tag {{ display:inline-block; font-family:'IBM Plex Mono',monospace; font-size:10.5px;
  font-weight:600; letter-spacing:.06em; padding:3px 8px; border-radius:999px; }}
.tag.quente {{ color:var(--quente); background:var(--quente-fraco); }}
.tag.escala {{ color:var(--escala); background:var(--escala-fraco); }}
.tag.neutra {{ color:var(--muted); background:var(--amber-fraco); }}
.vazio {{ color:var(--muted); font-size:14.5px; border:1px dashed var(--rule);
  border-radius:11px; padding:22px; text-align:center; }}

/* --- fechamento ao vivo --- */
.quadro {{ border:1px solid var(--rule); border-radius:13px; overflow:hidden;
  background:var(--surface); box-shadow:var(--sombra); }}
.cartoes {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:1px; background:var(--rule); }}
.cartoes > div {{ background:var(--surface); padding:15px 17px; }}
.cartoes .n {{ font-family:'Space Grotesk',sans-serif; font-size:27px; font-weight:700;
  line-height:1.1; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }}
.cartoes .comissao .n {{ color:var(--amber); }}
.rolagem {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
th {{ font-family:'IBM Plex Mono',monospace; font-size:10px; font-weight:600;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  text-align:left; padding:11px 14px; border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule); white-space:nowrap; }}
td {{ padding:11px 14px; border-bottom:1px solid var(--rule); vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
td input[type=text] {{ width:104px; background:var(--paper); color:var(--ink);
  border:1px solid var(--rule); border-radius:7px; padding:5px 9px;
  font-size:13px; text-align:right; font-family:'IBM Plex Mono',monospace; }}
td input[type=checkbox] {{ width:17px; height:17px; accent-color:var(--amber); }}
.acoes {{ display:flex; align-items:center; gap:13px; flex-wrap:wrap;
  padding:14px 17px; border-top:1px solid var(--rule); }}
.btn {{ font-family:inherit; font-size:14px; font-weight:600; cursor:pointer;
  background:var(--amber); color:#fff; border:0; border-radius:8px; padding:9px 17px; }}
.btn:hover {{ filter:brightness(1.08); }}
#aviso-valor {{ color:var(--escala); font-size:13px; }}

.nota {{ border-left:2px solid var(--amber); padding:2px 0 2px 18px;
  color:var(--muted); max-width:66ch; }}
.nota b {{ color:var(--ink); }}
ul.pontos {{ margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:11px; }}
ul.pontos li {{ display:grid; grid-template-columns:auto 1fr; gap:12px; align-items:baseline; }}
ul.pontos li::before {{ content:"—"; color:var(--amber); font-weight:600; }}

/* --- painel completo --- */
.abas {{ display:flex; gap:7px; flex-wrap:wrap; }}
.aba {{ font-family:inherit; font-size:14px; font-weight:600; padding:8px 15px;
  border-radius:999px; cursor:pointer; background:var(--surface); color:var(--muted);
  border:1px solid var(--rule); }}
.aba[aria-selected="true"] {{ color:var(--amber); border-color:var(--amber); background:var(--amber-fraco); }}
.moldura {{ border:1px solid var(--rule); border-radius:13px; overflow:hidden;
  background:#080b10; box-shadow:var(--sombra); }}
.barra {{ display:flex; align-items:center; gap:7px; padding:10px 14px;
  background:#151A21; border-bottom:1px solid #222932; }}
.barra i {{ width:9px; height:9px; border-radius:50%; background:#39424E; }}
.barra span {{ margin-left:8px; font-family:'IBM Plex Mono',monospace;
  font-size:11.5px; color:#6d7c8a; }}
iframe {{ display:block; width:100%; border:0; background:#080b10; min-height:400px; }}

footer {{ margin-top:60px; padding-top:24px; border-top:1px solid var(--rule);
  color:var(--muted); font-size:13.5px; }}
</style>

<div class="folha">

<header class="topo">
  <div class="marca"><span class="nome">LUDURAN <i>IA</i></span>
    <span class="rotulo">· demonstração ao vivo</span></div>
  <h1>O atendente das cabanas, funcionando</h1>
  <p class="linha-fina">Escreva como um hóspede escreveria. O atendente responde,
  e ao lado você vê o que ele entendeu e anotou. Depois, mais abaixo, a mesma
  conversa aparece no fechamento do mês — onde os 10% são calculados.</p>
</header>

<section>
  <div class="cabeca">
    <span class="rotulo">1 · No WhatsApp</span>
    <h2>Converse com ele</h2>
  </div>

  <div class="palco">
    <div>
      <div class="fone">
        <div class="fone-topo">
          <div class="bolha">🌲</div>
          <div>
            <div class="quem">Cabanas · atendimento</div>
            <div class="num">+55 54 99910-3545</div>
          </div>
        </div>
        <div class="conversa" id="conversa" aria-live="polite"></div>
        <form class="escrever" id="form-msg">
          <input id="entrada" placeholder="Escreva uma mensagem" autocomplete="off"
                 aria-label="Escreva como um hóspede">
          <button type="submit" aria-label="Enviar">➤</button>
        </form>
      </div>
      <div class="chips">
{chips}
      </div>
    </div>

    <div>
      <div class="rotulo" style="margin-bottom:10px;">O que o sistema entendeu</div>
      <div class="fichas" id="fichas">
        <div class="vazio">Mande uma mensagem — ou clique numa das sugestões —
        para ver a leitura que o sistema faz dela.</div>
      </div>
    </div>
  </div>

  <p class="nota"><b>As regras que você está vendo agir são as do sistema.</b>
  A detecção de escalação, a classificação de intenção e a marcação de lead
  quente rodam aqui com as mesmas expressões do servidor — conferidas frase a
  frase. O que muda em produção é só a redação da resposta, que sai do Gemini e
  varia; as regras acima dele não mudam.</p>
</section>

<section>
  <div class="cabeca">
    <span class="rotulo">2 · No fechamento</span>
    <h2>Quem demonstrou intenção de reservar</h2>
  </div>
  <p class="intro">Cada conversa acima com intenção real de reserva cai nesta
  lista. A Camily marca o que virou reserva no Airbnb, informa o valor, e o
  total e os 10% se calculam sozinhos.</p>

  <div class="quadro">
    <div class="cartoes">
      <div><div class="rotulo">Leads quentes</div><div class="n" id="c-leads">0</div></div>
      <div><div class="rotulo">Confirmadas</div><div class="n" id="c-conf">0</div></div>
      <div><div class="rotulo">Valor confirmado</div><div class="n" id="c-valor">R$ 0,00</div></div>
      <div class="comissao"><div class="rotulo">Comissão 10%</div><div class="n" id="c-com">R$ 0,00</div></div>
    </div>
    <div class="rolagem">
      <table>
        <thead><tr>
          <th>Reserva?</th><th>Telefone</th><th>Contato</th>
          <th>O que perguntou</th><th>Por que é lead</th><th>Valor da reserva</th>
        </tr></thead>
        <tbody id="linhas">
          <tr><td colspan="6" style="color:var(--muted);padding:22px;text-align:center;">
            Nenhum lead ainda. Pergunte por uma data ou diga que quer reservar, ali em cima.
          </td></tr>
        </tbody>
      </table>
    </div>
    <div class="acoes">
      <button class="btn" id="baixar">Baixar CSV</button>
      <span id="aviso-valor"></span>
    </div>
  </div>

  <p class="nota"><b>A marcação é rigorosa de propósito.</b> "Qual a política de
  reserva?" não conta como lead; "quero reservar pro dia 21" conta. É o número
  que sustenta a conversa dos 10% — inflá-lo cairia por terra na primeira
  conferência caso a caso.</p>
</section>

<section>
  <div class="cabeca">
    <span class="rotulo">3 · O painel completo</span>
    <h2>As telas que a Camily e o Adriano usam</h2>
  </div>
  <div class="abas" role="tablist">
    <button type="button" class="aba" data-tela="login">Entrar</button>
    <button type="button" class="aba" data-tela="painel">Visão do mês</button>
    <button type="button" class="aba" data-tela="fechamento">Fechamento</button>
    <button type="button" class="aba" data-tela="escalacoes">Escalações</button>
  </div>
  <div class="moldura">
    <div class="barra"><i></i><i></i><i></i><span id="rota">painel/login</span></div>
    <iframe id="quadro" title="Painel de demonstração"></iframe>
  </div>
  <p class="intro">Estas telas vêm do sistema rodando, com conversas de exemplo.
  Login de verdade, com três níveis: a Camily confere e marca as reservas; o
  Adriano vê tudo sem poder editar o que audita.</p>
</section>

<section>
  <div class="cabeca">
    <span class="rotulo">Para não haver dúvida</span>
    <h2>O que é real e o que é demonstração</h2>
  </div>
  <ul class="pontos">
    <li><span><b>Real:</b> as regras. Escalação, intenção, lead quente e o
      cálculo dos 10% rodam aqui com o mesmo código do servidor.</span></li>
    <li><span><b>Real:</b> o preço, os links do Airbnb e a recusa em confirmar
      data. O atendente nunca diz que uma data está livre — quem mostra isso é
      o Airbnb.</span></li>
    <li><span><b>Demonstração:</b> a redação das respostas. Em produção quem
      escreve é o Gemini, seguindo as mesmas regras, com variação natural.</span></li>
    <li><span><b>Demonstração:</b> nada aqui é gravado. No sistema, cada
      conversa vira registro e volta no fechamento do mês seguinte.</span></li>
  </ul>
  <p class="nota"><b>Falta só liberar o número na Meta.</b> O sistema está
  construído e testado; a partir daí estas mesmas telas passam a ler as
  conversas de verdade.</p>
</section>

<footer>Luduran IA · demonstração gerada a partir do sistema em execução · agosto de 2026</footer>
</div>

<script>
{REGRAS_JS}

/* ---- motor: as mesmas regras do servidor ---- */
function normalizar(t) {{
  return t.normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
}}
function motivoEscalacao(t) {{
  const n = normalizar(t);
  for (const [m, p] of REGRAS.escalacao) if (new RegExp(p).test(n)) return m;
  return null;
}}
function detectarIntencao(t) {{
  if (motivoEscalacao(t)) return 'escalacao';
  const n = normalizar(t);
  for (const [nome, p] of REGRAS.intencao) if (new RegExp(p).test(n)) return nome;
  return 'outro';
}}
function sinaisDeReserva(t) {{
  const n = normalizar(t), achados = [];
  for (const [s, ps] of REGRAS.sinais) if (ps.some(p => new RegExp(p).test(n))) achados.push(s);
  return achados;
}}

const LINKS = {json.dumps(LINKS)};
const DIARIA = 'R$ 150,00';
const ESCALACAO = 'Vou passar sua mensagem para nossa equipe, que já retorna para você por aqui.';

function link(n) {{
  return '<a class="cartao-link" href="' + LINKS[n] + '" target="_blank" rel="noopener">' +
    '<span class="ct">Cabana ' + n + ' · Airbnb</span>' +
    '<span class="cs">Fotos, datas livres e reserva · ' + DIARIA + ' a diária</span>' +
    '<span class="cb">Ver e reservar →</span></a>';
}}

function responder(texto, intencao) {{
  if (intencao === 'escalacao') return {{ txt: ESCALACAO, link: false }};
  if (intencao === 'preco') return {{ txt:
    'Oi! A diária das cabanas é ' + DIARIA + '.\\n\\n' +
    'É só abrir aqui:' + link('1'), link: true }};
  if (intencao === 'disponibilidade') return {{ txt:
    'Os dias de semana costumam ter mais disponibilidade que os fins de semana.\\n\\n' +
    'Não consigo confirmar uma data específica por aqui — a disponibilidade real ' +
    'aparece no anúncio, e é lá que você reserva:' + link('1'), link: true }};
  if (intencao === 'reserva') return {{ txt:
    'Que bom! A reserva é feita direto no Airbnb, pelo link da cabana.\\n\\n' +
    'É só escolher as datas por lá:' + link('1'), link: true }};
  if (intencao === 'cabanas') return {{ txt:
    'São 5 cabanas, todas a ' + DIARIA + ' a diária.\\n\\n' +
    'Cada uma tem fotos e detalhes no anúncio:\\n' +
    [1,2,3,4,5].map(n => link(String(n))).join(''), link: true }};
  return {{ txt:
    'Oi! 😊 Posso te ajudar com valores, disponibilidade e reserva das cabanas.\\n\\n' +
    'O que você gostaria de saber?', link: false }};
}}

/* ---- conversa ---- */
const conversa = document.getElementById('conversa');
const fichas = document.getElementById('fichas');
const TEL = '5554999912345';
const leads = new Map();

function agora() {{
  const d = new Date();
  return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}}
function bolha(texto, lado, comHtml) {{
  const d = document.createElement('div');
  d.className = 'msg ' + lado;
  if (comHtml) d.innerHTML = texto; else d.textContent = texto;
  const h = document.createElement('span');
  h.className = 'hora'; h.textContent = agora();
  d.appendChild(h);
  conversa.appendChild(d);
  conversa.scrollTop = conversa.scrollHeight;
  return d;
}}

const NOME_SINAL = {{ data_especifica:'falou de uma data', numero_pessoas:'disse quantas pessoas',
  pediu_reserva:'pediu para reservar' }};
const NOME_INT = {{ preco:'preço', disponibilidade:'disponibilidade', reserva:'reserva',
  cabanas:'cabanas', escalacao:'escalação', outro:'outro' }};
const NOME_MOTIVO = {{ desconto:'pedido de desconto', reclamacao:'reclamação',
  evento_grupo:'evento ou grupo', pediu_humano:'pediu para falar com uma pessoa' }};

function ficha(texto, intencao, motivo, sinais, mandouLink) {{
  if (fichas.querySelector('.vazio')) fichas.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'ficha';
  const quente = sinais.length > 0 && !motivo;
  el.innerHTML =
    '<div class="oq">Sobre: <b>' + texto.replace(/[<>&]/g, '') + '</b></div>' +
    '<dl class="linhas">' +
      '<dt>Intenção</dt><dd>' + (NOME_INT[intencao] || intencao) + '</dd>' +
      (motivo ? '<dt>Escalou</dt><dd><span class="tag escala">' + NOME_MOTIVO[motivo] +
                '</span> — o Gemini nem foi chamado</dd>' : '') +
      '<dt>Lead quente</dt><dd>' + (quente
        ? '<span class="tag quente">sim</span> ' +
          sinais.map(s => NOME_SINAL[s]).join(', ')
        : '<span class="tag neutra">não</span>') + '</dd>' +
      '<dt>Link enviado</dt><dd>' + (mandouLink ? 'sim' : 'não') + '</dd>' +
    '</dl>';
  fichas.prepend(el);
}}

function enviar(texto) {{
  texto = texto.trim();
  if (!texto) return;
  bolha(texto, 'deles', false);

  const motivo = motivoEscalacao(texto);
  const intencao = detectarIntencao(texto);
  const sinais = motivo ? [] : sinaisDeReserva(texto);
  const r = responder(texto, intencao);

  const esperando = document.createElement('div');
  esperando.className = 'digitando';
  esperando.textContent = 'digitando…';
  conversa.appendChild(esperando);
  conversa.scrollTop = conversa.scrollHeight;

  setTimeout(function () {{
    esperando.remove();
    bolha(r.txt, 'nossa', true);
    ficha(texto, intencao, motivo, sinais, r.link);
    if (sinais.length && !motivo) {{
      leads.set(texto, {{ texto: texto, sinais: sinais, quando: new Date(),
                         confirmado: false, valor: '' }});
      desenharLeads();
    }}
  }}, 620);
}}

document.getElementById('form-msg').addEventListener('submit', function (e) {{
  e.preventDefault();
  const i = document.getElementById('entrada');
  enviar(i.value); i.value = '';
}});
document.querySelectorAll('.chip-sug').forEach(function (b) {{
  b.addEventListener('click', function () {{ enviar(b.dataset.texto); }});
}});

/* ---- fechamento ao vivo ---- */
function emCentavos(txt) {{
  if (!txt) return 0;
  const limpo = String(txt).replace(/[^0-9,.-]/g,'').replace(/\\./g,'').replace(',','.');
  const n = parseFloat(limpo);
  return isNaN(n) ? 0 : Math.round(n * 100);
}}
function emReais(c) {{
  return 'R$ ' + Math.floor(c/100).toLocaleString('pt-BR') + ',' + String(c%100).padStart(2,'0');
}}
function dataBr(d) {{
  return String(d.getDate()).padStart(2,'0') + '/' + String(d.getMonth()+1).padStart(2,'0') +
    '/' + d.getFullYear() + ' ' + String(d.getHours()).padStart(2,'0') + ':' +
    String(d.getMinutes()).padStart(2,'0');
}}

function desenharLeads() {{
  const corpo = document.getElementById('linhas');
  if (!leads.size) return;
  corpo.innerHTML = '';
  let i = 0;
  leads.forEach(function (l, chave) {{
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td><input type="checkbox" aria-label="Reserva confirmada"' + (l.confirmado ? ' checked' : '') + '></td>' +
      '<td class="mono">+' + TEL + '</td>' +
      '<td class="mono">' + dataBr(l.quando) + '</td>' +
      '<td>' + l.texto.replace(/[<>&]/g,'') + '</td>' +
      '<td><span class="tag quente">' + l.sinais.map(s => NOME_SINAL[s]).join(', ') + '</span></td>' +
      '<td><input type="text" inputmode="decimal" placeholder="0,00" value="' + l.valor +
          '" aria-label="Valor da reserva"></td>';
    const cx = tr.querySelector('input[type=checkbox]');
    const vl = tr.querySelector('input[type=text]');
    cx.addEventListener('change', function () {{ l.confirmado = cx.checked; totais(); }});
    vl.addEventListener('input', function () {{ l.valor = vl.value; totais(); }});
    corpo.appendChild(tr); i++;
  }});
  totais();
}}

function totais() {{
  const todas = [...leads.values()];
  const conf = todas.filter(l => l.confirmado);
  const total = conf.reduce((s,l) => s + emCentavos(l.valor), 0);
  document.getElementById('c-leads').textContent = todas.length;
  document.getElementById('c-conf').textContent = conf.length;
  document.getElementById('c-valor').textContent = emReais(total);
  document.getElementById('c-com').textContent = emReais(Math.round(total * 10 / 100));
  const semValor = conf.filter(l => emCentavos(l.valor) === 0).length;
  document.getElementById('aviso-valor').textContent = semValor
    ? '⚠ ' + semValor + ' confirmada(s) sem valor — a comissão está sendo subestimada.' : '';
}}

document.getElementById('baixar').addEventListener('click', function () {{
  const todas = [...leads.values()];
  const l = [['telefone','contato','pergunta','sinais','reserva_confirmada','valor_reserva'].join(';')];
  todas.forEach(function (x) {{
    l.push([TEL, dataBr(x.quando), x.texto.replace(/;/g,','),
      x.sinais.map(s => NOME_SINAL[s]).join(', '), x.confirmado ? 'sim':'nao',
      x.confirmado && emCentavos(x.valor) ? (emCentavos(x.valor)/100).toFixed(2).replace('.',',') : ''
    ].join(';'));
  }});
  const conf = todas.filter(x => x.confirmado);
  const total = conf.reduce((s,x) => s + emCentavos(x.valor), 0);
  l.push('', 'leads_quentes;' + todas.length, 'reservas_confirmadas;' + conf.length,
    'valor_confirmado;' + (total/100).toFixed(2).replace('.',','),
    'comissao_10pct;' + (Math.round(total*10/100)/100).toFixed(2).replace('.',','));
  const b = new Blob(['\\ufeff' + l.join('\\r\\n')], {{type:'text/csv;charset=utf-8'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'fechamento-cabanas-demonstracao.csv';
  a.click();
}});

/* ---- painel ---- */
const TELAS = {json.dumps(TELAS)};
const quadro = document.getElementById('quadro');
const rota = document.getElementById('rota');
const CAMINHOS = {{login:'painel/login', painel:'painel/', fechamento:'painel/fechamento',
                  escalacoes:'painel/escalacoes'}};
function abrir(t) {{
  const bytes = Uint8Array.from(atob(TELAS[t]), c => c.charCodeAt(0));
  quadro.srcdoc = new TextDecoder('utf-8').decode(bytes);
  quadro.style.height = '';
  rota.textContent = CAMINHOS[t];
  document.querySelectorAll('.aba').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.tela === t)));
}}
document.querySelectorAll('.aba').forEach(b =>
  b.addEventListener('click', () => abrir(b.dataset.tela)));
addEventListener('message', e => {{
  const m = e.data || {{}};
  if (m.tipo === 'altura' && m.valor) quadro.style.height = (m.valor + 8) + 'px';
  if (m.tipo === 'ir' && TELAS[m.para]) abrir(m.para);
}});
abrir('login');

/* ---- abertura ---- */
bolha('Oi! 😊 Sou o atendimento das cabanas. Posso te ajudar com valores, ' +
      'disponibilidade e reserva.\\n\\nO que você gostaria de saber?', 'nossa', false);
</script>
"""

saida = AQUI / "demo-atendente.html"
saida.write_text(HTML)
print(f"{saida}  {saida.stat().st_size // 1024} KB")
