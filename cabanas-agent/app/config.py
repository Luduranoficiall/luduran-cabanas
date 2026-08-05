"""Configuração via variáveis de ambiente.

Em produção as credenciais vêm do Secret Manager, montadas como env vars
pelo Cloud Run. Nada de .env dentro da imagem.
"""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _cabanas_from_env() -> dict[str, str]:
    """Lê CABANAS no formato "1,2,4,5" e monta os links do Airbnb.

    Existe uma pendência aberta sobre a cabana 3 (a Camile mandou prints da
    1, 2, 4 e 5). Enquanto isso não se confirma, dá para tirar a cabana do ar
    sem mexer no código: basta subir com CABANAS=1,2,4,5.
    """
    raw = _env("CABANAS", "1,2,3,4,5")
    numeros = [n.strip() for n in raw.split(",") if n.strip()]
    return {n: f"https://airbnb.com.br/h/1992cabana{n}" for n in numeros}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))

    whatsapp_token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN"))
    whatsapp_phone_number_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    whatsapp_verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    # Usado para conferir a assinatura X-Hub-Signature-256 do webhook.
    # Sem ele qualquer pessoa que descubra a URL consegue injetar mensagens.
    whatsapp_app_secret: str = field(default_factory=lambda: _env("WHATSAPP_APP_SECRET"))
    graph_api_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0"))

    gcp_project_id: str = field(default_factory=lambda: _env("GCP_PROJECT_ID", "serious-trainer-465716-j9"))
    firestore_collection: str = field(default_factory=lambda: _env("FIRESTORE_COLLECTION", "cabanas_leads"))

    # Número que recebe o aviso quando uma conversa é escalada para humano.
    # Formato internacional, só dígitos (ex.: 5548999998888).
    escalation_number: str = field(default_factory=lambda: _env("ESCALATION_NUMBER"))

    diaria: str = "R$150,00"
    cabanas: dict[str, str] = field(default_factory=_cabanas_from_env)

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
