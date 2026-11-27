"""Leitura das exportações do SINAN (CSV, Excel ou DBF) e preparo dos casos.

Todas as colunas originais são mantidas. As colunas calculadas pelo
analisador recebem o prefixo ``vv_`` (de Vigiavetor).
"""

import csv
import io
import os
import tempfile

import pandas as pd

from .util import (
    normalizar_coluna,
    normalizar_texto,
    parse_data,
    parse_float,
    semana_epidemiologica,
)

# Nome canônico -> nomes de coluna aceitos (já normalizados: maiúsculas, sem acento, "_")
ALIASES = {
    "numero_notificacao": ["NU_NOTIFIC", "NUMERO_NOTIFICACAO", "N_NOTIFICACAO", "NOTIFICACAO", "NUM_NOTIFICACAO"],
    "agravo": ["ID_AGRAVO", "AGRAVO", "DOENCA", "CID", "AGRAVO_DOENCA"],
    "data_notificacao": ["DT_NOTIFIC", "DATA_NOTIFICACAO", "DATA_DA_NOTIFICACAO"],
    "data_sintomas": ["DT_SIN_PRI", "DATA_PRIMEIROS_SINTOMAS", "DATA_INICIO_SINTOMAS", "DATA_DOS_PRIMEIROS_SINTOMAS", "DATA_SINTOMAS", "INICIO_SINTOMAS"],
    "semana_sintomas": ["SEM_PRI", "SEMANA_PRIMEIROS_SINTOMAS", "SE_SINTOMAS"],
    "nome": ["NM_PACIENT", "NOME", "NOME_PACIENTE", "PACIENTE", "NOME_DO_PACIENTE"],
    "data_nascimento": ["DT_NASC", "DATA_NASCIMENTO", "DATA_DE_NASCIMENTO"],
    "idade": ["NU_IDADE_N", "IDADE", "NU_IDADE"],
    "sexo": ["CS_SEXO", "SEXO"],
    "gestante": ["CS_GESTANT", "GESTANTE"],
    "municipio_residencia": ["ID_MN_RESI", "MUNICIPIO_RESIDENCIA", "MUN_RESIDENCIA", "CO_MUN_RES"],
    "bairro": ["NM_BAIRRO", "BAIRRO", "BAIRRO_RESIDENCIA", "BAIRRO_DE_RESIDENCIA"],
    "logradouro": ["NM_LOGRADO", "LOGRADOURO", "ENDERECO", "RUA"],
    "numero": ["NU_NUMERO", "NUMERO", "NUMERO_RESIDENCIA", "NUM"],
    "complemento": ["NM_COMPLEM", "COMPLEMENTO"],
    "cep": ["NU_CEP", "CEP"],
    "microarea": ["MICROAREA", "MICRO_AREA", "ID_MICROAREA"],
    "classificacao": ["CLASSI_FIN", "CLASSIFICACAO_FINAL", "CLASSIFICACAO", "CLASSIF_FINAL"],
    "criterio": ["CRITERIO", "CRITERIO_CONFIRMACAO", "CRITERIO_DE_CONFIRMACAO"],
    "evolucao": ["EVOLUCAO", "EVOLUCAO_CASO", "EVOLUCAO_DO_CASO"],
    "data_obito": ["DT_OBITO", "DATA_OBITO"],
    "latitude": ["LATITUDE", "LAT", "ID_GEO1", "COORD_Y"],
    "longitude": ["LONGITUDE", "LON", "LNG", "LONG", "ID_GEO2", "COORD_X"],
}

DESCRICAO_CLASSIFICACAO = {
    "dengue": {"10": "Dengue", "11": "Dengue com sinais de alarme", "12": "Dengue grave",
               "5": "Descartado", "8": "Inconclusivo"},
    "chikungunya": {"13": "Chikungunya", "5": "Descartado", "8": "Inconclusivo"},
    "zika": {"1": "Zika confirmado", "2": "Descartado"},
}

DESCRICAO_EVOLUCAO = {
    "1": "Cura",
    "2": "Óbito pelo agravo",
    "3": "Óbito por outras causas",
    "4": "Óbito em investigação",
    "9": "Ignorado",
}

DESCRICAO_CRITERIO = {"1": "Laboratorial", "2": "Clínico-epidemiológico", "3": "Em investigação"}


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def _decodificar(conteudo: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1", errors="replace")


def _ler_csv(conteudo: bytes) -> pd.DataFrame:
    texto = _decodificar(conteudo)
    amostra = texto[:20000]
    try:
        separador = csv.Sniffer().sniff(amostra, delimiters=";,\t|").delimiter
    except csv.Error:
        separador = ";" if amostra.count(";") >= amostra.count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=separador, dtype=str,
                       keep_default_na=False, skipinitialspace=True)


def _ler_dbf(conteudo: bytes) -> pd.DataFrame:
    from dbfread import DBF

    with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        tabela = DBF(caminho, encoding="latin-1", char_decode_errors="replace")
        registros = [
            {k: ("" if v is None else (v.isoformat() if hasattr(v, "isoformat") else str(v)))
             for k, v in r.items()}
            for r in tabela
        ]
    finally:
        os.unlink(caminho)
    return pd.DataFrame(registros, dtype=str)


def ler_arquivo(conteudo: bytes, nome_arquivo: str) -> pd.DataFrame:
    """Lê CSV/TXT, XLSX/XLS ou DBF e devolve tudo como texto."""
    extensao = os.path.splitext(nome_arquivo.lower())[1]
    if extensao in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(io.BytesIO(conteudo), dtype=str).fillna("")
    elif extensao == ".dbf":
        df = _ler_dbf(conteudo)
    else:
        df = _ler_csv(conteudo)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    # Remove linhas totalmente vazias
    df = df[~(df.astype(str).apply(lambda col: col.str.strip()) == "").all(axis=1)]
    return df.reset_index(drop=True)


def mapear_colunas(df: pd.DataFrame, mapeamento_extra=None) -> dict:
    """Descobre qual coluna do arquivo corresponde a cada campo canônico."""
    normalizadas = {normalizar_coluna(c): c for c in df.columns}
    resultado = {}
    for canonico, aliases in ALIASES.items():
        extra = (mapeamento_extra or {}).get(canonico)
        candidatos = ([extra] if extra else []) + aliases
        for alias in candidatos:
            chave = normalizar_coluna(alias)
            if chave in normalizadas:
                resultado[canonico] = normalizadas[chave]
                break
    return resultado


# ---------------------------------------------------------------------------
# Interpretação dos campos
# ---------------------------------------------------------------------------
def identificar_agravo(valor, padrao=None):
    texto = normalizar_texto(valor).replace(" ", "")
    if texto:
        if texto.startswith("A90") or "DENGUE" in texto:
            return "dengue"
        if texto.startswith("A920") or "CHIK" in texto:
            return "chikungunya"
        if texto.startswith("A928") or "ZIKA" in texto or texto.startswith("U069"):
            return "zika"
    return padrao


def _codigo(valor) -> str:
    texto = str(valor or "").strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto


def classificar(valor, agravo, config):
    """Retorna (confirmado: bool, descricao: str)."""
    codigo = _codigo(valor)
    confirmados = {str(c) for c in config["classificacao_confirmada"].get(agravo, [])}
    descricoes = DESCRICAO_CLASSIFICACAO.get(agravo, {})
    if not codigo:
        return bool(config.get("incluir_em_investigacao")), "Em investigação"
    if codigo.isdigit():
        return codigo in confirmados, descricoes.get(codigo, f"Código {codigo}")
    texto = normalizar_texto(codigo)
    if any(p in texto for p in ("DESCART", "INCONCLUS", "NAO CONFIRM")):
        return False, codigo
    if "INVESTIG" in texto:
        return bool(config.get("incluir_em_investigacao")), codigo
    if any(p in texto for p in ("CONFIRM", "DENGUE", "CHIKUNGUNYA", "ZIKA", "ALARME", "GRAVE")):
        return True, codigo
    return False, codigo


def gravidade(descricao_classificacao: str) -> str:
    texto = normalizar_texto(descricao_classificacao)
    if "GRAVE" in texto:
        return "grave"
    if "ALARME" in texto:
        return "sinais_de_alarme"
    return ""


def idade_em_anos(valor_idade, data_nasc, data_ref):
    codigo = _codigo(valor_idade)
    if codigo.isdigit():
        n = int(codigo)
        if n >= 1000:  # padrão SINAN: 1º dígito = unidade (1 h, 2 dia, 3 mês, 4 ano)
            unidade, quantidade = n // 1000, n % 1000
            if unidade == 4:
                return quantidade
            if unidade in (1, 2, 3):
                return 0
        elif n <= 130:
            return n
    if data_nasc and data_ref:
        anos = data_ref.year - data_nasc.year - (
            (data_ref.month, data_ref.day) < (data_nasc.month, data_nasc.day))
        if 0 <= anos <= 130:
            return anos
    return None


def faixa_etaria(idade):
    if idade is None:
        return "Ignorada"
    faixas = [(0, 0, "<1"), (1, 4, "1-4"), (5, 9, "5-9"), (10, 14, "10-14"), (15, 19, "15-19"),
              (20, 39, "20-39"), (40, 59, "40-59"), (60, 64, "60-64"), (65, 79, "65-79")]
    for minimo, maximo, rotulo in faixas:
        if minimo <= idade <= maximo:
            return rotulo
    return "80+"


def montar_endereco(linha, colunas):
    partes = []
    logradouro = str(linha.get(colunas.get("logradouro", ""), "") or "").strip()
    numero = _codigo(linha.get(colunas.get("numero", ""), ""))
    if logradouro:
        partes.append(f"{logradouro}, {numero}" if numero and numero not in ("0", "SN", "S/N") else logradouro)
    complemento = str(linha.get(colunas.get("complemento", ""), "") or "").strip()
    if complemento:
        partes.append(complemento)
    return " - ".join(partes)


def preparar_casos(df: pd.DataFrame, config: dict, agravo_padrao=None):
    """Acrescenta as colunas ``vv_*`` e devolve (df, info)."""
    colunas = mapear_colunas(df, config.get("mapeamento_colunas"))
    info = {"colunas_reconhecidas": colunas, "linhas_lidas": len(df), "avisos": []}

    if "agravo" not in colunas and not agravo_padrao:
        raise ValueError(
            "Não encontrei a coluna do agravo (ID_AGRAVO). Informe qual é a doença do arquivo "
            "(dengue, chikungunya ou zika).")
    for obrigatoria in ("bairro",):
        if obrigatoria not in colunas:
            info["avisos"].append(f"Coluna '{obrigatoria}' não encontrada; análise por bairro ficará vazia.")
    if "data_sintomas" not in colunas and "data_notificacao" not in colunas:
        info["avisos"].append("Sem data de sintomas nem de notificação; não dá para calcular semanas.")

    def col(linha, nome):
        coluna = colunas.get(nome)
        return linha[coluna] if coluna is not None else ""

    municipio_filtro = _codigo(config.get("codigo_municipio_residencia", ""))[:6]
    derivados = []
    for _, linha in df.iterrows():
        agravo = identificar_agravo(col(linha, "agravo"), agravo_padrao)
        confirmado, desc_class = classificar(col(linha, "classificacao"), agravo, config) if agravo else (False, "")
        data_sint = parse_data(col(linha, "data_sintomas"))
        data_notif = parse_data(col(linha, "data_notificacao"))
        data_base = data_sint or data_notif
        ano_epi, sem_epi = semana_epidemiologica(data_base) if data_base else (None, None)
        evolucao = _codigo(col(linha, "evolucao"))
        bairro = str(col(linha, "bairro") or "").strip()
        idade = idade_em_anos(col(linha, "idade"), parse_data(col(linha, "data_nascimento")), data_base)
        lat = parse_float(col(linha, "latitude"))
        lon = parse_float(col(linha, "longitude"))
        if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
        if lat == 0 and lon == 0:
            lat = lon = None

        no_municipio = True
        if municipio_filtro and "municipio_residencia" in colunas:
            no_municipio = _codigo(col(linha, "municipio_residencia"))[:6] == municipio_filtro

        derivados.append({
            "vv_agravo": agravo or "",
            "vv_confirmado": bool(confirmado and no_municipio),
            "vv_residente_municipio": no_municipio,
            "vv_classificacao": desc_class,
            "vv_gravidade": gravidade(desc_class) if agravo == "dengue" else "",
            "vv_criterio": DESCRICAO_CRITERIO.get(_codigo(col(linha, "criterio")), _codigo(col(linha, "criterio"))),
            "vv_evolucao": DESCRICAO_EVOLUCAO.get(evolucao, evolucao),
            "vv_obito_agravo": evolucao == "2",
            "vv_obito_investigacao": evolucao == "4",
            "vv_data_sintomas": data_base.isoformat() if data_base else "",
            "vv_ano_epi": ano_epi or "",
            "vv_semana_epi": sem_epi or "",
            "vv_idade_anos": "" if idade is None else idade,
            "vv_faixa_etaria": faixa_etaria(idade),
            "vv_sexo": {"M": "Masculino", "F": "Feminino"}.get(str(col(linha, "sexo")).strip().upper()[:1], "Ignorado"),
            "vv_bairro": bairro,
            "vv_bairro_norm": normalizar_texto(bairro),
            "vv_endereco": montar_endereco(linha, colunas),
            "vv_cep": _codigo(col(linha, "cep")),
            "vv_microarea": str(col(linha, "microarea") or "").strip(),
            "vv_latitude": lat if lat is not None else "",
            "vv_longitude": lon if lon is not None else "",
            "vv_precisao_localizacao": "arquivo" if lat is not None else "",
        })

    resultado = pd.concat([df.reset_index(drop=True), pd.DataFrame(derivados)], axis=1)

    # Remove notificações duplicadas (mesmo número + agravo + data)
    chave = [c for c in (colunas.get("numero_notificacao"), "vv_agravo", "vv_data_sintomas") if c]
    if colunas.get("numero_notificacao"):
        antes = len(resultado)
        resultado = resultado.drop_duplicates(subset=chave, keep="last").reset_index(drop=True)
        info["duplicadas_removidas"] = antes - len(resultado)
    else:
        info["duplicadas_removidas"] = 0
        info["avisos"].append("Sem número da notificação: duplicidades não foram verificadas.")

    sem_agravo = int((resultado["vv_agravo"] == "").sum())
    if sem_agravo:
        info["avisos"].append(f"{sem_agravo} linha(s) sem agravo reconhecido foram ignoradas.")
    fora = int((~resultado["vv_residente_municipio"]).sum())
    if fora:
        info["avisos"].append(f"{fora} caso(s) de residentes de outros municípios foram desconsiderados.")
    return resultado, info


def ler_bairros(caminho_ou_bytes, nome="bairros.csv"):
    """Cadastro de bairros: bairro;microarea;populacao;latitude;longitude;apelidos

    ``apelidos`` (opcional) lista outros nomes do mesmo bairro, separados por "|",
    para casar com a grafia usada no SINAN.
    """
    if caminho_ou_bytes is None:
        return {}
    if isinstance(caminho_ou_bytes, (bytes, bytearray)):
        conteudo = bytes(caminho_ou_bytes)
    else:
        if not os.path.exists(caminho_ou_bytes):
            return {}
        with open(caminho_ou_bytes, "rb") as f:
            conteudo = f.read()
        nome = caminho_ou_bytes
    df = ler_arquivo(conteudo, nome)
    cols = {normalizar_coluna(c): c for c in df.columns}

    def pega(linha, *nomes):
        for n in nomes:
            if n in cols:
                return str(linha[cols[n]]).strip()
        return ""

    cadastro = {}
    for _, linha in df.iterrows():
        nome_bairro = pega(linha, "BAIRRO", "NOME", "NM_BAIRRO")
        if not nome_bairro:
            continue
        populacao = parse_float(pega(linha, "POPULACAO", "POP", "HABITANTES"))
        registro = {
            "bairro": nome_bairro,
            "microarea": pega(linha, "MICROAREA", "MICRO_AREA"),
            "populacao": int(populacao) if populacao else None,
            "latitude": parse_float(pega(linha, "LATITUDE", "LAT")),
            "longitude": parse_float(pega(linha, "LONGITUDE", "LON", "LNG")),
        }
        chaves = [nome_bairro] + [a for a in pega(linha, "APELIDOS", "ALIASES").split("|") if a.strip()]
        for c in chaves:
            cadastro[normalizar_texto(c)] = registro
    return cadastro
