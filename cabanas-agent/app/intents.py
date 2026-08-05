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
