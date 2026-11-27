"""Funções utilitárias: normalização de texto, datas e semana epidemiológica."""

import math
import re
import unicodedata
from datetime import date, datetime, timedelta


def sem_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c))


def normalizar_texto(texto) -> str:
    """Maiúsculas, sem acentos e com espaços simples. Usado para comparar nomes."""
    if texto is None:
        return ""
    texto = sem_acentos(str(texto)).upper().strip()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_coluna(nome) -> str:
    texto = sem_acentos(str(nome)).upper().strip()
    texto = re.sub(r"[^A-Z0-9]+", "_", texto)
    return texto.strip("_")


_FORMATOS_DATA = (
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%Y%m%d",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%Y/%m/%d",
    "%d.%m.%Y",
)


def parse_data(valor):
    """Converte texto em date. Aceita os formatos usuais do SINAN/TabWin/Excel."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto or texto.upper() in {"NAN", "NAT", "NONE", "NULL"}:
        return None
    # Remove parte de hora ("2024-03-01 00:00:00" ou "2024-03-01T00:00")
    texto = re.split(r"[ T]", texto)[0]
    for formato in _FORMATOS_DATA:
        try:
            d = datetime.strptime(texto, formato).date()
        except ValueError:
            continue
        if 1900 <= d.year <= 2100:
            return d
    # Número serial do Excel (dias desde 1899-12-30)
    if re.fullmatch(r"\d{5}(\.0+)?", texto):
        d = date(1899, 12, 30) + timedelta(days=int(float(texto)))
        if 1900 <= d.year <= 2100:
            return d
    return None


# ---------------------------------------------------------------------------
# Semana epidemiológica (padrão do Ministério da Saúde / MMWR):
# semanas de domingo a sábado; a semana 1 é a que contém o dia 4 de janeiro.
# ---------------------------------------------------------------------------
def _inicio_semana1(ano: int) -> date:
    quatro_jan = date(ano, 1, 4)
    return quatro_jan - timedelta(days=(quatro_jan.weekday() + 1) % 7)


def inicio_semana(d: date) -> date:
    """Domingo que inicia a semana epidemiológica de ``d``."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def semana_epidemiologica(d: date):
    """Retorna (ano_epidemiologico, semana) para a data ``d``."""
    ano = d.year
    if d < _inicio_semana1(ano):
        ano -= 1
    elif d >= _inicio_semana1(ano + 1):
        ano += 1
    semana = (d - _inicio_semana1(ano)).days // 7 + 1
    return ano, semana


def distancia_m(lat1, lon1, lat2, lon2) -> float:
    """Distância em metros entre dois pontos (fórmula de Haversine)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_float(valor):
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto:
        return None
    try:
        numero = float(texto)
    except ValueError:
        return None
    if math.isnan(numero):
        return None
    return numero


# ---------------------------------------------------------------------------
# Endereços
# ---------------------------------------------------------------------------
ABREVIACOES = {
    "AV": "AVENIDA", "AVE": "AVENIDA", "R": "RUA", "TV": "TRAVESSA", "TR": "TRAVESSA", "TRAV": "TRAVESSA",
    "AL": "ALAMEDA", "PC": "PRACA", "PCA": "PRACA", "ROD": "RODOVIA", "EST": "ESTRADA", "CJ": "CONJUNTO",
    "CONJ": "CONJUNTO", "LOT": "LOTEAMENTO", "CONC": "CONDOMINIO", "COND": "CONDOMINIO",
    "DR": "DOUTOR", "DES": "DESEMBARGADOR", "GOV": "GOVERNADOR", "PROF": "PROFESSOR", "PE": "PADRE",
    "STA": "SANTA", "STO": "SANTO", "SEN": "SENADOR", "DEP": "DEPUTADO", "GAL": "GENERAL", "GEN": "GENERAL",
    "CEL": "CORONEL", "MAL": "MARECHAL", "VER": "VEREADOR", "PRES": "PRESIDENTE", "ENG": "ENGENHEIRO",
}


def normalizar_logradouro(texto):
    palavras = normalizar_texto(texto).split()
    return " ".join(ABREVIACOES.get(p, p) for p in palavras)


def normalizar_numero(valor):
    t = normalizar_texto(valor).replace(" ", "")
    if t in ("", "SN", "SNO", "0", "00", "SEMNUMERO", "SNUMERO"):
        return ""
    return t
