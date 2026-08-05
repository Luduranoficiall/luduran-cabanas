# Fotos das cabanas

Pasta para receber as fotos que o Adriano vai mandar. Ainda vazia.

## Como nomear

Uma subpasta por cabana, foto de capa primeiro:

```
assets/cabanas/
├── cabana1/
│   ├── 01-capa.jpg
│   ├── 02-quarto.jpg
│   └── 03-varanda.jpg
├── cabana2/
└── ...
```

O número da pasta tem que bater com o número usado em `CABANAS`
(ver `cabanas-agent/.env.example`).

## Antes de commitar

- **JPG** para foto, **WebP** se for usar na página de demonstração.
- Redimensionar para no máximo **1600px** no lado maior e manter cada arquivo
  **abaixo de 500 KB**. Foto direto do celular vem com 4–8 MB; o repositório
  incha rápido e não tem como desinchar depois, porque o Git guarda todas as
  versões para sempre.

```bash
# redimensiona e comprime tudo de uma vez
mogrify -resize '1600x1600>' -quality 82 assets/cabanas/cabana1/*.jpg
```

## O que o agente faz com elas

Por enquanto, nada. O agente do WhatsApp manda o link do Airbnb, e é lá que a
pessoa vê as fotos — mandar imagem pelo WhatsApp gasta chamada de API e não
melhora a conversão, já que a reserva acontece no Airbnb de qualquer jeito.

Estas fotos servem para a página de demonstração e para material de
divulgação. Se em algum momento fizer sentido o agente enviar foto, o caminho
é `whatsapp_client.py` — a Cloud API aceita mensagem de imagem por URL pública.
