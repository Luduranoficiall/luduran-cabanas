"""Exporta as regras de intents.py para JavaScript, sem reescrever nenhuma.

As expressões regulares saem literalmente do módulo Python — o navegador roda
as MESMAS regras que o servidor. Reescrever à mão criaria duas verdades que
divergem na primeira alteração.
"""

import json
import sys
from pathlib import Path

RAIZ = Path("/home/user/luduran-cabanas/cabanas-agent")
sys.path.insert(0, str(RAIZ))

from app import intents as I  # noqa: E402


def fonte(p):
    return p.pattern


REGRAS = {
    "escalacao": [(motivo, fonte(p)) for motivo, p in I._GATILHOS_ESCALACAO],
    "intencao": [(nome, fonte(p)) for nome, p in I._ORDEM_INTENCOES],
    "sinais": [(sinal, [fonte(p) for p in ps]) for sinal, ps in I._SINAIS],
}

saida = Path(__file__).parent / "regras.js"
saida.write_text(
    "// GERADO por gerar_regras_js.py a partir de app/intents.py — não edite.\n"
    "const REGRAS = " + json.dumps(REGRAS, ensure_ascii=False, indent=2) + ";\n"
)
print(f"{saida.name}: {len(REGRAS['escalacao'])} gatilhos, "
      f"{len(REGRAS['intencao'])} intenções, {len(REGRAS['sinais'])} sinais")
