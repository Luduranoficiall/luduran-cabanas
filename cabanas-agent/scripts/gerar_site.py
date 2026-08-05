#!/usr/bin/env python3
"""Gera o index.html da demo a partir de site/index.template.html.

A seção das cabanas é montada aqui, lendo a MESMA configuração que o agente
usa (CABANAS / CABANA_URLS). Assim a página e o atendimento nunca divergem:
se uma cabana não está no ar para o agente, ela também não aparece no site.

Por que no build e não em runtime: a página é estática (GitHub Pages) e o
agente roda no Cloud Run. Gerar aqui evita expor endpoint público novo e
mantém a página funcionando mesmo com o agente fora do ar.

Uso:
    python cabanas-agent/scripts/gerar_site.py
    git add index.html && git commit

A trava é a mesma do agente: cabana sem link cadastrado não entra, e o script
sai com código 1 avisando qual ficou de fora.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
TEMPLATE = RAIZ / "site" / "index.template.html"
SAIDA = RAIZ / "index.html"
FOTOS = RAIZ / "assets" / "cabanas"

MARCADOR = "<!--CABANAS-->"


def encontrar_capa(numero: str) -> str | None:
    """Caminho relativo da foto de capa, se ela já tiver sido enviada.

    Aceita qualquer extensão comum e usa a primeira imagem em ordem
    alfabética — o padrão de nome combinado é `01-capa.jpg` (ver
    assets/cabanas/README.md).
    """
    pasta = FOTOS / f"cabana{numero}"
    if not pasta.is_dir():
        return None
    imagens = sorted(
        p
        for p in pasta.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not imagens:
        return None
    return str(imagens[0].relative_to(RAIZ))


def montar_cartao(numero: str, url: str, diaria: str) -> str:
    capa = encontrar_capa(numero)
    if capa:
        midia = (
            f'<img class="cabana-foto" src="{html.escape(capa)}" '
            f'alt="Cabana {html.escape(numero)}" loading="lazy">'
        )
    else:
        # Sem foto ainda. O bloco tem a mesma proporção da imagem, então o
        # grid não desalinha, e diz o que está acontecendo — um cartão vazio
        # no meio de quatro com foto passa impressão de página quebrada.
        midia = (
            '<div class="cabana-foto-vazia">\n'
            '        <svg viewBox="0 0 24 24" stroke-width="1.4" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>'
            '<path d="M10 21v-6h4v6"/></svg>\n'
            '        <span>foto em breve</span>\n'
            "      </div>"
        )

    return (
        f'    <a class="cabana" href="{html.escape(url)}" '
        f'target="_blank" rel="noopener">\n'
        f"      {midia}\n"
        f'      <div class="cabana-corpo">\n'
        f'        <div class="cabana-nome">Cabana {html.escape(numero)}</div>\n'
        f'        <div class="cabana-preco">{html.escape(diaria)} a diária</div>\n'
        f"      </div>\n"
        f"    </a>"
    )


def montar_secao(cfg: Settings) -> str:
    if not cfg.cabanas:
        return ""

    cartoes = "\n".join(
        montar_cartao(numero, cfg.cabanas[numero], cfg.diaria)
        for numero in sorted(cfg.cabanas, key=int)
    )
    total = len(cfg.cabanas)
    plural = "cabanas" if total > 1 else "cabana"

    return (
        '  <section class="cabanas">\n'
        f'    <h2 class="cabanas-titulo">{total} {plural} para reservar</h2>\n'
        '    <p class="cabanas-sub">Fotos, datas livres e reserva direto no '
        "Airbnb.</p>\n"
        '    <div class="cabanas-grid">\n'
        f"{cartoes}\n"
        "    </div>\n"
        "  </section>"
    )


def gerar(cfg: Settings | None = None) -> str:
    """Devolve o HTML final. Não escreve em disco — facilita testar."""
    cfg = cfg or Settings()
    template = TEMPLATE.read_text(encoding="utf-8")
    if MARCADOR not in template:
        raise SystemExit(f"Marcador {MARCADOR} não encontrado em {TEMPLATE}")
    return template.replace(MARCADOR, montar_secao(cfg))


LIMITE_FOTO_KB = 500


def main() -> int:
    cfg = Settings()
    SAIDA.write_text(gerar(cfg), encoding="utf-8")

    ativas = sorted(cfg.cabanas, key=int)
    com_foto = [n for n in ativas if encontrar_capa(n)]
    sem_foto = [n for n in ativas if n not in com_foto]

    print(f"{SAIDA.relative_to(RAIZ)} gerado")
    print(f"  cabanas na página : {', '.join(ativas) or 'nenhuma'}")
    print(f"  com foto          : {', '.join(com_foto) or 'nenhuma'}")
    if sem_foto:
        print(f"  sem foto          : {', '.join(sem_foto)} (bloco 'foto em breve')")

    # O repositório guarda toda versão de todo arquivo, para sempre. Foto de
    # celular tem 4–8 MB; depois de commitada não tem como desinchar.
    pesadas = []
    for numero in com_foto:
        capa = RAIZ / encontrar_capa(numero)
        kb = capa.stat().st_size / 1024
        if kb > LIMITE_FOTO_KB:
            pesadas.append(f"cabana{numero} ({kb:.0f} KB)")

    problemas = 0
    if pesadas:
        print(
            f"\n  AVISO: foto acima de {LIMITE_FOTO_KB} KB: {', '.join(pesadas)}.\n"
            f"  Redimensione ANTES de commitar — depois não tem como desinchar:\n"
            f"    mogrify -resize '1600x1600>' -quality 82 assets/cabanas/cabana*/*.jpg",
            file=sys.stderr,
        )
        problemas = 1

    if cfg.cabanas_sem_link:
        print(
            f"\n  AVISO: fora da página por falta de link: "
            f"{', '.join(cfg.cabanas_sem_link)}. Cadastre em CABANA_URLS.",
            file=sys.stderr,
        )
        problemas = 1

    if not problemas:
        print("\n  Tudo certo. Confira o index.html no navegador e commite.")
    return problemas


if __name__ == "__main__":
    raise SystemExit(main())
