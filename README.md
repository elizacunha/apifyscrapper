# TikTok Engagement Research Scraper

Actor para coletar dados públicos de vídeos do TikTok e ranquear postagens por engajamento, pensado para pesquisas sobre circulação algorítmica, saúde, emagrecimento, Mounjaro, Ozempic e Wegovy.

## O que este Actor faz

- Recebe URLs públicas do TikTok: busca, hashtag, perfil ou vídeo.
- Coleta vídeos visíveis/publicamente acessíveis.
- Extrai, quando disponíveis, métricas públicas:
  - visualizações (`playCount`)
  - curtidas (`diggCount`)
  - comentários (`commentCount`)
  - compartilhamentos (`shareCount`)
  - salvamentos (`collectCount`)
- Calcula interações totais:

```text
interactions = likes + comments + shares + saves
```

- Calcula taxa de engajamento por visualização:

```text
engagementRatePct = (interactions / playCount) * 100
```

- Calcula score híbrido de influência:

```text
rankScore = engagementRatePct * log10(playCount + 1)
```

- Classifica automaticamente o tema:
  - Mounjaro/Tirzepatida
  - Ozempic/Semaglutida
  - Wegovy
  - Outros

## Por que usar visualizações em vez de seguidores?

No TikTok, a distribuição é altamente algorítmica. Um vídeo pode alcançar milhões de pessoas fora da base de seguidores do perfil. Por isso, para análise de circulação e engajamento, o denominador mais adequado costuma ser `playCount`, e não o total de seguidores.

## Filtros metodológicos

Por padrão, o Actor mantém apenas vídeos com:

- `playCount >= 5000`
- `interactions >= 100`
- `engagementRatePct <= 30%`

O filtro de 30% reduz outliers típicos de scraping, posts com visualizações quebradas ou casos muito pequenos com taxa artificialmente alta.

## Entrada sugerida

```json
{
  "keywords": ["mounjaro", "ozempic", "wegovy", "tirzepatida", "semaglutida"],
  "maxVideosPerSource": 100,
  "minViews": 5000,
  "minInteractions": 100,
  "maxEngagementRatePct": 30,
  "keepOutliers": false,
  "scrollRounds": 12,
  "headless": true
}
```

Também é possível informar URLs diretamente:

```json
{
  "startUrls": [
    { "url": "https://www.tiktok.com/search?q=mounjaro" },
    { "url": "https://www.tiktok.com/tag/ozempic" },
    { "url": "https://www.tiktok.com/@nomedoperfil" }
  ]
}
```

## Campos de saída

Cada item do dataset contém:

- `url`
- `sourceUrl`
- `authorUsername`
- `authorNickname`
- `description`
- `theme`
- `playCount`
- `diggCount`
- `commentCount`
- `shareCount`
- `collectCount`
- `interactions`
- `engagementRatePct`
- `rankScore`
- `possibleOutlier`
- `scrapedAt`

## Limitações

O TikTok muda frequentemente a estrutura das páginas. Este Actor usa extração por estado JSON público da página e fallback por DOM. Em alguns cenários, a plataforma pode ocultar métricas, apresentar CAPTCHA ou limitar dados. O Actor não usa login, não acessa dados privados e não tenta contornar barreiras de acesso.

## Uso responsável

Este Actor foi pensado para pesquisa acadêmica e análise de dados públicos. Use com volume moderado, respeitando os termos das plataformas envolvidas, privacidade dos usuários e legislação aplicável.
