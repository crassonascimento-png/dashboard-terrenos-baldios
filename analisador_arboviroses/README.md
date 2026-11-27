# Analisador de Arboviroses → Vigiavetor

Lê as exportações do **SINAN** (dengue, chikungunya e zika) e identifica os **casos confirmados**.
Depois localiza os endereços no mapa, calcula os indicadores por **bairro e microárea** e gera os
**alertas automáticos**. O resultado sai em arquivos JSON/CSV/GeoJSON, prontos para carregar no Vigiavetor.

Esta pasta é independente do app de terrenos baldios e não altera nenhum arquivo dele.

**Já configurado para Aracaju-SE** (código IBGE 2800308; o SINAN usa `280030`). O resultado principal é a
planilha **`vigiavetor.xlsx`**, para alimentar o Vigiavetor.

## O que ainda falta preencher: população dos bairros

O `bairros.csv` já traz os bairros de Aracaju e as grafias comuns no SINAN (ex.: `18 DO FORTE`,
`CONJ AUGUSTO FRANCO` → Farolândia, `MOSQUEIRO`/`ARUANA` → Zona de Expansão). A coluna **`populacao`
está vazia**. Sem ela, tudo funciona, menos a incidência por 100 mil habitantes e os alertas de incidência.

Onde encontrar a população por bairro:
- **Anuário Estatístico de Aracaju**, no Portal da Transparência da Prefeitura (tem tabela por bairro);
- **IBGE / Censo 2022**, agregados por bairro (SIDRA) ou pela Secretaria Municipal de Saúde/Vigilância.

Basta abrir o `bairros.csv` (no Excel ou em qualquer editor) e preencher a coluna. As colunas
`latitude`/`longitude` podem ficar vazias: o analisador busca o centro de cada bairro no OpenStreetMap
na primeira execução e guarda em cache. Esses centros aparecem na aba *Bairros* da planilha gerada;
copie-os para o `bairros.csv` se quiser fixá-los.

## Duas formas de usar

### 1. Pela página web (pelo celular)

1. Abra a página e entre com a senha.
2. Envie o arquivo exportado do SINAN (CSV, TXT, Excel ou DBF).
3. Veja o resumo e os alertas, e baixe o `.zip` com todos os arquivos.

Para publicar no Render (como o app de terrenos):

- **Root Directory:** `analisador_arboviroses`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn web:app --workers 1 --timeout 300`
- **Variáveis de ambiente:**
  - `ANALISADOR_SENHA`: senha de acesso (obrigatória; sem ela a página não libera o uso)
  - `ANALISADOR_SECRET_KEY`: uma frase longa e aleatória
  - `GEOCODIFICACAO_MAX_WEB` (opcional, padrão 150): máximo de endereços **novos** consultados
    por envio, para a página não estourar o tempo limite. Os já consultados ficam em cache.

### 2. Pela linha de comando (computador)

```bash
cd analisador_arboviroses
pip install -r requirements.txt
python analisar.py caminho/DENGON.csv                 # detecta o agravo pela coluna ID_AGRAVO
python analisar.py chik.dbf --agravo chikungunya --saida saida/chik
python analisar.py dengue.xlsx --sem-geocodificacao --data-referencia 2026-11-21
```

Para testar com dados fictícios: `python analisar.py exemplos/sinan_exemplo_ficticio.csv --sem-geocodificacao`

## Configuração

### `config.json`

| Campo | Para que serve |
|---|---|
| `municipio`, `uf` | Usados para localizar os endereços (Aracaju, SE). |
| `centro_municipio_latitude/longitude`, `raio_municipio_km` | Centro de Aracaju e raio (25 km). Endereços localizados fora dele são descartados. |
| `codigo_municipio_residencia` | Código IBGE (6 dígitos). Se preenchido, só conta residentes do município (`ID_MN_RESI`). |
| `classificacao_confirmada` | Códigos de `CLASSI_FIN` que contam como confirmado. Padrão SINAN: dengue 10/11/12, chikungunya 13, zika 1. |
| `incluir_em_investigacao` | `true` conta também os casos sem classificação final. |
| `incluir_dados_pessoais_nas_saidas` | `true` (padrão escolhido) mantém nome, endereço etc. nos arquivos gerados. `false` remove. |
| `mapeamento_colunas` | Se a sua planilha usa outros nomes de coluna, ex.: `{"bairro": "BAIRRO_RES"}`. |
| `geocodificar` | Liga ou desliga a localização dos endereços. |
| `geocodificacao_raio_max_km` | Descarta endereços localizados a mais de X km do centro do bairro (evita rua homônima em outra cidade). |
| `niveis_incidencia_acumulada` | Faixas de incidência no ano por 100 mil hab. (padrão do Ministério da Saúde: <100 baixa, 100–299 média, ≥300 alta). |
| `alertas` | Limites dos alertas (veja abaixo). |

### `bairros.csv` (cadastro de bairros)

```
bairro;microarea;populacao;latitude;longitude;apelidos
Vila Nova;02;8500;-10.0100;-48.0050;VL NOVA|V NOVA
```

- `populacao` é necessária para calcular **incidência** e os alertas de incidência.
- `latitude`/`longitude` (centro do bairro) servem de posição para casos cujo endereço não foi encontrado, e
  de referência para validar a geocodificação.
- `apelidos` faz o nome escrito no SINAN casar com o bairro cadastrado (separe por `|`).
- Os bairros que aparecem no SINAN e não estão no cadastro são listados em `resumo.json` → `bairros_nao_cadastrados`.

Os arquivos em `exemplos/` são **fictícios** (só para testes).

## Alertas gerados

| Tipo | Quando dispara | Nível |
|---|---|---|
| `incidencia_alta` | Incidência nas últimas 4 semanas ≥ 50 / 100 / 300 por 100 mil hab. | atenção / alerta / crítico |
| `aumento_casos` | Últimas 2 semanas ≥ 1,5× as 2 anteriores e pelo menos 5 casos | atenção (alerta se ≥ 10) |
| `aglomerado` | ≥ 3 casos com endereço num raio de 200 m em 14 dias (soma as três doenças, já que o mosquito é o mesmo) | alerta (crítico se ≥ 6) |
| `obito` | Óbito pelo agravo (`EVOLUCAO = 2`) nas últimas 4 semanas | crítico |
| `obito_em_investigacao` | `EVOLUCAO = 4` nas últimas 4 semanas | alerta |
| `dengue_grave` | Caso de dengue grave nas últimas 4 semanas | alerta |

Todos os limites podem ser ajustados no `config.json`.

## Arquivos gerados (para o Vigiavetor)

| Arquivo | Conteúdo |
|---|---|
| `vigiavetor.xlsx` | **Planilha para o Vigiavetor.** Abas: *Resumo*, *Alertas* (coloridas por nível), *Bairros*, *Microareas*, *Semanas* (uma coluna por doença), *Mapa_Casos* (latitude/longitude de cada caso) e *Casos_Confirmados* (todas as colunas). |
| `vigiavetor.json` | **Pacote único** com `resumo`, `bairros`, `microareas`, `semanas`, `alertas`, `mapa_casos`, `mapa_bairros`. |
| `resumo.json` | Semana epidemiológica de referência, totais por doença, óbitos, sexo, faixa etária e qualidade dos dados. |
| `bairros.json` / `.csv` | Por bairro e doença: casos no ano, nas últimas 4 e 2 semanas, incidência, nível, tendência e óbitos. |
| `microareas.json` / `.csv` | Casos no ano por bairro + microárea. |
| `semanas.json` / `.csv` | Casos por ano, semana epidemiológica e doença (para a curva epidêmica). |
| `alertas.json` / `.csv` | Lista de alertas, do mais grave para o menos grave, com mensagem pronta para exibir. |
| `mapa_casos.geojson` | Um ponto por caso confirmado. `precisao_localizacao` = `endereco`, `arquivo` ou `bairro`; `recente` = últimas 4 semanas. |
| `mapa_bairros.geojson` | Um ponto por bairro com todos os indicadores. |
| `casos_confirmados.csv` | Casos confirmados com **todas** as colunas originais + colunas calculadas `vv_*`. |
| `casos_processados.csv` | Todas as notificações (inclusive descartadas), com `vv_confirmado`. |

Os CSV usam `;` e UTF-8 com BOM, para abrir direto no Excel.

## Como os dados são tratados

- **Semana epidemiológica:** semanas de domingo a sábado, padrão do Ministério da Saúde. A data usada é o início dos sintomas
  (`DT_SIN_PRI`), ou a data de notificação quando não houver.
- **Data de referência:** por padrão, o início de sintomas mais recente do arquivo. As "últimas 4 semanas"
  são as 4 semanas epidemiológicas que terminam nela.
- **Duplicadas:** mesma notificação (`NU_NOTIFIC`), mesmo agravo e mesma data contam uma vez só.
- **Colunas reconhecidas automaticamente:** os nomes do SINAN (`NU_NOTIFIC`, `ID_AGRAVO`, `DT_SIN_PRI`, `NM_BAIRRO`,
  `NM_LOGRADO`, `NU_NUMERO`, `CLASSI_FIN`, `EVOLUCAO`, `CS_SEXO`, `NU_IDADE_N`...) e variações comuns
  ("Bairro", "Classificação final"...). Se a planilha tiver `LATITUDE`/`LONGITUDE`, elas são usadas direto.

## Privacidade (LGPD)

Por sua escolha, os arquivos gerados **mantêm os dados pessoais** (nome, endereço, idade). Por isso:

- a página web só funciona com senha, não guarda o arquivo enviado e apaga os resultados após 60 minutos;
- na geocodificação, **só o endereço** (rua, número, bairro, cidade) é enviado ao OpenStreetMap (Nominatim),
  nunca o nome ou outros dados. O resultado fica em `cache/geocodificacao.json`, que não vai para o Git;
- não coloque arquivos do SINAN nem a pasta `saida/` no Git (o `.gitignore` já bloqueia);
- para gerar arquivos sem dados pessoais, use `"incluir_dados_pessoais_nas_saidas": false`.

O serviço público do Nominatim permite no máximo 1 consulta por segundo. Para muitos endereços, rode pela linha
de comando: o cache faz as próximas execuções serem rápidas. Também é possível apontar `geocodificacao_url`
para um servidor Nominatim próprio.

## Testes

```bash
pip install pytest
python -m pytest tests
```
