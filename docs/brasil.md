# Leads locais no Brasil (versão mínima)

Lista de empresas da sua cidade com telefone, se o número tem WhatsApp
(celular) e o motivo concreto para abordar: sem site, perfil do Google não
reivindicado, sem agendamento online etc. Nada é enviado; a abordagem é sua.

## Sem nenhuma chave (grátis)

**OpenStreetMap** funciona sem cadastro. Ele entende ramos em português
(padaria, salão, barbearia, oficina, clínica, dentista, academia, pet shop,
farmácia, advogado, contador, imobiliária e outros) e já traz o telefone quando
alguém cadastrou no mapa.

```bash
harvey signals --confirm free
harvey discover --provider osm --city "Ribeirão Preto, SP"
harvey leads
```

Limites: o OSM só tem o que voluntários mapearam, então a cobertura varia muito
de cidade para cidade e muitos registros vêm sem telefone. "Sem site" no OSM
quer dizer que o mapa não conhece o site, não que a empresa não tenha um.
Confira antes de abordar.

**Serper Maps** é o próximo passo, ainda grátis: cadastro em serper.dev só com
e-mail, sem cartão, e 2.500 buscas grátis. Ele traz dados do Google Maps
(telefone, site, nota), bem mais completos que o OSM. Cada página de ~20
empresas gasta uma busca.

```bash
# .env: SERPER_API_KEY=sua_chave
harvey discover --provider serper_places --city "Ribeirão Preto, SP"
```

## Google Places (pago, com cota grátis)


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

## Mensagem pronta para cada lead

`harvey leads` também escreve uma mensagem de primeiro contato em português para
cada empresa, a partir do sinal mais forte dela (sem site, perfil do Google não
reivindicado, sem agendamento online etc.). Você envia do seu próprio WhatsApp.

```bash
harvey leads --nome "Seu Nome" --empresa "Sua Empresa"
```

- `leads.html`: abra no navegador (ou no celular). Cada empresa tem a mensagem
  numa caixa que você pode editar e um botão **Abrir no WhatsApp**, que abre a
  conversa já com o texto digitado. É só revisar e apertar enviar.
- `leads.csv`: as mesmas mensagens na coluna `whatsapp_message`, e o link com o
  texto em `whatsapp_link`.
- Telefone fixo não tem botão, mas a mensagem serve de roteiro para ligar ou
  visitar.

As mensagens não usam IA: são montadas por regras, então não custam nada e a
mesma empresa sempre recebe o mesmo texto. Para mudar o tom, edite
`harvey/br_messages.py`.
