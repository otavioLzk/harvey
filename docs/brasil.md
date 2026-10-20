# Leads locais no Brasil (versão mínima)

Lista de empresas da sua cidade com telefone, se o número tem WhatsApp
(celular) e o motivo concreto para abordar: sem site, perfil do Google não
reivindicado, sem agendamento online etc. Nada é enviado; a abordagem é sua.

## Configurar

1. No Google Cloud Console, crie um projeto, ative **Places API (New)** e o
   faturamento, e gere uma chave de API.
2. Em `.env`: `GOOGLE_PLACES_API_KEY=sua_chave`
3. Em `harvey.yaml`, troque `icp.industries` pelos ramos que você quer, em
   português (por exemplo `padaria`, `oficina mecânica`, `clínica odontológica`,
   `salão de beleza`).
4. Confirme os sinais gratuitos: `harvey signals --confirm free`

## Usar

```bash
harvey discover --provider google_places --city "Ribeirão Preto, SP" --estimate
harvey discover --provider google_places --city "Ribeirão Preto, SP" --max-spend 2
harvey leads                         # todos -> leads.csv
harvey leads --whatsapp --no-website # só celular e sem site
```

Cada busca (ramo x cidade) devolve até 60 empresas em até 3 chamadas. O custo
estimado é cerca de US$ 0,035 por chamada, e o Google dá uma cota mensal
gratuita. Confira a tabela atual antes de rodar em volume.

O `leads.csv` abre direto no Excel e vem ordenado assim: primeiro quem não tem
site, depois quem tem celular. A coluna `whatsapp_link` abre a conversa no
WhatsApp (`wa.me`), e `signals` lista os argumentos para a abordagem. Um perfil
só de Instagram/Facebook conta como "sem site".
