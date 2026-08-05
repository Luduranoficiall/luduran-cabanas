"""Configuração via variáveis de ambiente.

Em produção as credenciais vêm do Secret Manager, montadas como env vars
pelo Cloud Run. Nada de .env dentro da imagem.
"""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Links confirmados pelo cliente. As cinco cabanas estão no ar.
#
# A cabana 3 entrou aqui, e não em CABANA_URLS, porque o link agora é
# permanente: deixá-lo só na variável de ambiente faria cada deploy depender de
# alguém lembrar de passá-la, e esquecer derrubaria a cabana em silêncio (com
# aviso no log, mas fora do ar mesmo assim). CABANA_URLS continua valendo para
# link novo ou correção emergencial sem deploy.
LINKS_CONFIRMADOS: dict[str, str] = {
    "1": "https://airbnb.com.br/h/1992cabana1",
    "2": "https://airbnb.com.br/h/1992cabana2",
    "3": "https://airbnb.com.br/h/1992cabana3",
    "4": "https://airbnb.com.br/h/1992cabana4",
    "5": "https://airbnb.com.br/h/1992cabana5",
}


def _urls_extras() -> dict[str, str]:
    """Lê CABANA_URLS no formato "3=https://...,5=https://outro".

    Serve para cadastrar um link novo ou corrigir um existente sem deploy de
    código. O que vier aqui tem precedência sobre LINKS_CONFIRMADOS.
    """
    extras: dict[str, str] = {}
    for par in _env("CABANA_URLS").split(","):
        par = par.strip()
        if not par:
            continue
        numero, _, url = par.partition("=")
        numero, url = numero.strip(), url.strip()
        if numero and url:
            extras[numero] = url
    return extras


def _cabanas_from_env() -> dict[str, str]:
    """Monta o mapa das cabanas ativas: número → link do Airbnb.

    CABANAS diz quais estão no ar. Uma cabana só entra se tiver link conhecido:
    inventar a URL por padrão de nome faria o agente mandar link quebrado para
    cliente. Cabana ativa sem link é descartada aqui e denunciada em
    Settings.cabanas_sem_link, que aparece no log e no /health.
    """
    conhecidos = {**LINKS_CONFIRMADOS, **_urls_extras()}
    ativas = [n.strip() for n in _env("CABANAS", "1,2,3,4,5").split(",") if n.strip()]
    return {n: conhecidos[n] for n in ativas if n in conhecidos}


def _cabanas_sem_link() -> list[str]:
    conhecidos = {**LINKS_CONFIRMADOS, **_urls_extras()}
    ativas = [n.strip() for n in _env("CABANAS", "1,2,3,4,5").split(",") if n.strip()]
    return [n for n in ativas if n not in conhecidos]


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))
    # Sem teto, uma chamada travada segura a resposta para sempre. 12s deixa
    # margem para o modelo e ainda cabe folgado na janela da Meta.
    gemini_timeout_s: float = field(default_factory=lambda: float(_env("GEMINI_TIMEOUT_S", "12")))

    whatsapp_token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN"))
    # ATENÇÃO: não é o telefone. É o ID numérico que a Meta dá ao número
    # dentro da WhatsApp Business Account (App → WhatsApp → API Setup).
    whatsapp_phone_number_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    # O telefone em si, só para conferência humana e para aparecer no /health.
    # Não é usado em chamada de API.
    whatsapp_phone_number: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER"))
    whatsapp_verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    # Usado para conferir a assinatura X-Hub-Signature-256 do webhook.
    # Sem ele qualquer pessoa que descubra a URL consegue injetar mensagens.
    whatsapp_app_secret: str = field(default_factory=lambda: _env("WHATSAPP_APP_SECRET"))
    graph_api_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0"))

    gcp_project_id: str = field(default_factory=lambda: _env("GCP_PROJECT_ID", "serious-trainer-465716-j9"))
    firestore_collection: str = field(default_factory=lambda: _env("FIRESTORE_COLLECTION", "cabanas_leads"))
    # Qual operação gerou o registro. Já entra agora, com o schema vazio, para
    # que os próximos nichos (academia, alojamento, sushi...) não exijam
    # migração de dado que já está em produção.
    nicho: str = field(default_factory=lambda: _env("NICHO", "cabanas"))
    # Nichos que o painel oferece no filtro. Cresce conforme as operações
    # entram (academia, alojamento, sushi...), sem migrar dado.
    nichos_painel: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            n.strip() for n in _env("NICHOS_PAINEL", "cabanas").split(",") if n.strip()
        )
    )
    # Cookie de sessão só sai por HTTPS. Desligar apenas em teste local.
    cookie_seguro: bool = field(
        default_factory=lambda: _env("COOKIE_SEGURO", "1") not in ("0", "false", "no")
    )

    # Número que recebe o aviso quando uma conversa é escalada para humano.
    # Formato internacional, só dígitos (ex.: 5548999998888).
    escalation_number: str = field(default_factory=lambda: _env("ESCALATION_NUMBER"))

    diaria: str = "R$150,00"
    cabanas: dict[str, str] = field(default_factory=_cabanas_from_env)
    # Cabanas listadas em CABANAS que ficaram de fora por não ter link.
    cabanas_sem_link: list[str] = field(default_factory=_cabanas_sem_link)

    # Quantas mensagens anteriores entram no contexto do modelo.
    history_limit: int = field(default_factory=lambda: int(_env("HISTORY_LIMIT", "6")))

    @property
    def total_cabanas(self) -> int:
        return len(self.cabanas)

    def faltando(self) -> list[str]:
        """Credenciais obrigatórias que não foram configuradas."""
        obrigatorias = {
            "GEMINI_API_KEY": self.gemini_api_key,
            "WHATSAPP_TOKEN": self.whatsapp_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
        }
        return sorted(nome for nome, valor in obrigatorias.items() if not valor)


settings = Settings()
