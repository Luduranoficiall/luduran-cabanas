"""Classificação de intenção e detecção de escalação (seções 2 e 3 da spec).

A detecção aqui é determinística, por palavra-chave. Ela não substitui o
julgamento do modelo — trabalha junto com ele:

- Para ESCALAÇÃO ela funciona como trava de segurança. Se qualquer gatilho da
  seção 2 aparecer, a conversa é escalada e o Gemini nem chega a ser chamado.
  Isso garante que "faz por 100?" nunca vira uma negociação, mesmo que o modelo
  resolva improvisar.
- Para INTENÇÃO ela serve de rótulo no Firestore, alimentando o painel do
  Adriano. A resposta em si continua vindo do modelo.

Limite conhecido: o gatilho "qualquer assunto fora de hospedagem" é aberto
demais para palavra-chave. Esse caso fica com o modelo, que recebe a regra no
system prompt. Os outros quatro gatilhos são pegos aqui.
"""

import re
import unicodedata

INTENCAO_PRECO = "preco"
INTENCAO_DISPONIBILIDADE = "disponibilidade"
INTENCAO_RESERVA = "reserva"
INTENCAO_CABANAS = "cabanas"
INTENCAO_ESCALACAO = "escalacao"
INTENCAO_OUTRO = "outro"


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento — para os padrões casarem com "voce" e "você"."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def _padrao(*termos: str) -> re.Pattern[str]:
    """Compila termos como alternativas com fronteira de palavra.

    A fronteira evita que "vaga" case dentro de "vagabundo" ou que "evento"
    dispare escalação por causa de "eventualmente".
    """
    return re.compile(r"\b(?:" + "|".join(termos) + r")\b")


# --- Gatilhos de escalação (seção 2) -------------------------------------

_DESCONTO = _padrao(
    "desconto", "descontinho", "abatimento", "promocao", "promocional",
    "mais barato", "melhor preco", "faz por", "fazer por", "ultimo preco",
    "negociar", "negociavel", "parcelar", "parcelamento", "condicao especial",
)

_RECLAMACAO = _padrao(
    "reclamacao", "reclamar", "reclamando", "problema", "reembolso",
    "estorno", "cancelar", "cancelamento", "cancelei", "nao gostei",
    "pessimo", "horrivel", "processar", "procon",
)

_EVENTO_GRUPO = _padrao(
    "evento", "eventos", "festa", "casamento", "aniversario", "confraternizacao",
    "retiro", "excursao", "grupo grande", "grupao", "empresa", "corporativo",
    "comercial", "filmagem", "ensaio fotografico", "workshop",
)

_PEDIU_HUMANO = _padrao(
    "falar com atendente", "falar com humano", "falar com uma pessoa",
    "falar com alguem", "falar com o dono", "falar com a camile",
    "falar com adriano", "atendente humano", "pessoa de verdade",
    "quero falar com", "me liga", "ligar para mim", "numero do responsavel",
)

_GATILHOS_ESCALACAO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("desconto", _DESCONTO),
    ("reclamacao", _RECLAMACAO),
    ("evento_grupo", _EVENTO_GRUPO),
    ("pediu_humano", _PEDIU_HUMANO),
)


def motivo_escalacao(texto: str) -> str | None:
    """Retorna o motivo da escalação, ou None se a conversa segue com a IA."""
    normalizado = normalizar(texto)
    for motivo, padrao in _GATILHOS_ESCALACAO:
        if padrao.search(normalizado):
            return motivo
    return None


def precisa_escalar(texto: str) -> bool:
    return motivo_escalacao(texto) is not None


# --- Classificação de intenção (seção 3) ---------------------------------

_PRECO = _padrao(
    "preco", "precos", "valor", "valores", "quanto custa", "quanto e",
    "quanto fica", "quanto sai", "diaria", "diarias", "custa", "tarifa",
)

_DISPONIBILIDADE = _padrao(
    "disponivel", "disponibilidade", "vaga", "vagas", "livre", "livres",
    "tem para", "tem pra", "esta livre", "ocupado", "lotado", "agenda",
    "calendario", "data", "datas", "feriado", "fim de semana", "final de semana",
)

_RESERVA = _padrao(
    "reservar", "reserva", "reservas", "agendar", "alugar", "quero fechar",
    "como faco", "como funciona", "quero garantir", "booking", "hospedar",
)

_CABANAS = _padrao(
    "cabana", "cabanas", "quantas", "diferenca", "diferencas", "fotos",
    "foto", "tamanho", "quantas pessoas", "capacidade", "acomoda",
)

# Ordem importa: a primeira que casar vence. Reserva vem antes de preço porque
# "quero reservar, quanto custa?" é, na prática, uma intenção de reserva.
_ORDEM_INTENCOES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (INTENCAO_RESERVA, _RESERVA),
    (INTENCAO_PRECO, _PRECO),
    (INTENCAO_DISPONIBILIDADE, _DISPONIBILIDADE),
    (INTENCAO_CABANAS, _CABANAS),
)


def detectar_intencao(texto: str) -> str:
    """Rotula a mensagem com uma das intenções da seção 3."""
    if precisa_escalar(texto):
        return INTENCAO_ESCALACAO

    normalizado = normalizar(texto)
    for intencao, padrao in _ORDEM_INTENCOES:
        if padrao.search(normalizado):
            return intencao
    return INTENCAO_OUTRO


# --- Lead quente (item 2.3 do roadmap) -----------------------------------
#
# Marca quem demonstrou intenção real de reserva. É a métrica que separa
# "20 pessoas conversaram" de "7 queriam mesmo reservar", e é ela que sustenta
# a conversa dos 10% com o Adriano.
#
# Por isso a detecção aqui é DELIBERADAMENTE conservadora. Contar lead quente
# demais infla o número que justifica a nossa própria comissão — o erro que
# custa caro não é deixar passar um lead, é apresentar ao cliente um número que
# não se sustenta quando ele for conferir caso a caso no fechamento.
# Na dúvida, não marca.

SINAL_DATA = "data_especifica"
SINAL_PESSOAS = "numero_pessoas"
SINAL_RESERVA = "pediu_reserva"

# "dia 12", "12/03", "12 de março"
_DATA_NUMERICA = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\b")
_DIA_DO_MES = re.compile(r"\bdia\s+\d{1,2}\b")
_MESES = _padrao(
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
)
_DIAS_SEMANA = _padrao(
    "segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo",
)
_FERIADOS = _padrao("natal", "ano novo", "carnaval", "pascoa", "feriadao")

# "4 pessoas", "somos 6", "um casal"
_QTD_PESSOAS = re.compile(r"\b\d+\s+pessoas?\b")
_SOMOS = re.compile(r"\bsomos\s+\d+\b")
_COMPOSICAO = _padrao("casal", "familia", "crianca", "criancas", "bebe")

# Só verbo de reserva com marcador de intenção. "reserva" solto aparece em
# "qual a política de reserva?", que é dúvida, não intenção.
_RESERVA_EXPLICITA = _padrao(
    "quero reservar", "vou reservar", "posso reservar", "gostaria de reservar",
    "pretendo reservar", "quero fazer uma reserva", "fazer uma reserva",
    "como reservo", "como faco a reserva", "como faco para reservar",
    "quero fechar", "quero garantir", "vou querer",
)

_SINAIS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (SINAL_DATA, (_DATA_NUMERICA, _DIA_DO_MES, _MESES, _DIAS_SEMANA, _FERIADOS)),
    (SINAL_PESSOAS, (_QTD_PESSOAS, _SOMOS, _COMPOSICAO)),
    (SINAL_RESERVA, (_RESERVA_EXPLICITA,)),
)


def sinais_de_reserva(texto: str) -> list[str]:
    """Quais sinais de intenção real de reserva aparecem na mensagem.

    Guardar os sinais, e não só o booleano, é o que permite à Camile conferir
    no fechamento *por que* um lead foi marcado como quente.
    """
    normalizado = normalizar(texto)
    encontrados = []
    for sinal, padroes in _SINAIS:
        if any(padrao.search(normalizado) for padrao in padroes):
            encontrados.append(sinal)
    return encontrados


def eh_lead_quente(texto: str) -> bool:
    return bool(sinais_de_reserva(texto))
