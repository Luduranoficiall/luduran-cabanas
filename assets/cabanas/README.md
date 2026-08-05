# Fotos das cabanas

O gerador da página já consome esta pasta. Basta commitar as imagens no
caminho certo e rodar:

```bash
python cabanas-agent/scripts/gerar_site.py
git add index.html assets/cabanas && git commit
```

Sem rodar o gerador, as fotos ficam no repositório mas não aparecem na página —
e o teste `test_index_commitado_esta_atualizado` falha para lembrar disso.

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
(ver `cabanas-agent/.env.example`). As cinco cabanas estão no ar, então as
pastas vão de `cabana1` a `cabana5`.

O gerador pega a **primeira imagem em ordem alfabética** de cada pasta como
capa — daí o prefixo `01-`. Aceita `.jpg`, `.jpeg`, `.png` e `.webp`, com
extensão em maiúscula ou minúscula. Cabana sem pasta ou sem imagem continua
com o bloco neutro, sem quebrar o grid.

## Cabana sem foto

Não some e não quebra o grid: o cartão fica na página, com link e preço, e no
lugar da imagem entra um bloco da **mesma proporção** com o rótulo
"foto em breve". Testado com 4 de 5 cabanas — as alturas dos cartões ficam
idênticas, e em 320px vira uma coluna sem rolagem lateral.

## Depois de rodar o gerador, confira

O próprio script diz o que aconteceu:

```
index.html gerado
  cabanas na página : 1, 2, 3, 4, 5
  com foto          : 1, 3, 4, 5
  sem foto          : 2 (bloco 'foto em breve')

  Tudo certo. Confira o index.html no navegador e commite.
```

1. **`com foto`** lista todas que deveriam ter foto. Faltou alguma que você
   subiu? O nome ou o caminho da pasta está errado.
2. **Sem aviso de peso.** Foto acima de 500 KB vira aviso e o script sai com
   erro — corrija antes de commitar, porque o Git guarda toda versão para
   sempre.
3. **Abra o `index.html` no navegador.** As fotos aparecem, a conversa da demo
   ainda anima, e o link de cada cartão abre o Airbnb certo.
4. **`pytest`** na pasta `cabanas-agent` — `test_index_commitado_esta_atualizado`
   falha se você editar o template e esquecer de gerar de novo.

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
