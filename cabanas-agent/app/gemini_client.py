"""Cliente do Gemini.

O SDK só é importado quando o cliente é realmente construído. Assim os testes
rodam sem a biblioteca instalada e sem chave de API.
"""

from __future__ import annotations

import logging

from .config import Settings, settings
from .prompts import build_system_prompt

logger = logging.getLogger(__name__)


class GeminiIndisponivel(RuntimeError):
    """O modelo não respondeu. Quem chama deve usar a resposta de fallback."""


class GeminiClient:
    def __init__(self, cfg: Settings | None = None, client=None) -> None:
        self.cfg = cfg or settings
        self._client = client
        self._system_prompt = build_system_prompt(self.cfg)

    def _get_client(self):
        if self._client is None:
            from google import genai  # import tardio: ver docstring do módulo

            if not self.cfg.gemini_api_key:
                raise GeminiIndisponivel("GEMINI_API_KEY não configurada")
            from google.genai import types

            self._client = genai.Client(
                api_key=self.cfg.gemini_api_key,
                # Sem teto explícito, uma chamada travada nunca retorna: a
                # tarefa de background fica pendurada e a pessoa não recebe
                # nem o fallback. O timeout é em milissegundos.
                http_options=types.HttpOptions(
                    timeout=int(self.cfg.gemini_timeout_s * 1000)
                ),
            )
        return self._client

    def responder(self, mensagem: str, historico: list[dict] | None = None) -> str:
        """Gera a resposta para uma mensagem, considerando o histórico.

        `historico` são as trocas anteriores, mais antigas primeiro, no formato
        {"role": "user"|"model", "text": str}.
        """
        from google.genai import types

        conteudos = []
        for turno in historico or []:
            papel = "model" if turno.get("role") == "model" else "user"
            texto = (turno.get("text") or "").strip()
            if texto:
                conteudos.append(
                    types.Content(role=papel, parts=[types.Part(text=texto)])
                )
        conteudos.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))

        try:
            resposta = self._get_client().models.generate_content(
                model=self.cfg.gemini_model,
                contents=conteudos,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    # Baixa, mas não zero: o tom precisa soar natural sem que o
                    # modelo comece a inventar informação que não está no prompt.
                    temperature=0.4,
                    max_output_tokens=400,
                ),
            )
        except Exception as exc:  # falha de rede, cota, timeout
            logger.warning("Gemini falhou: %s", exc)
            raise GeminiIndisponivel(str(exc)) from exc

        texto = (getattr(resposta, "text", None) or "").strip()
        if not texto:
            # Acontece quando a resposta é cortada por filtro de segurança.
            raise GeminiIndisponivel("resposta vazia do modelo")
        return texto
