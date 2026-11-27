"""Coordenadas coletadas em campo (uma a uma) e lista do que ainda falta coletar.

Fluxo:
1. Cada análise grava ``coordenadas_a_coletar.xlsx`` com os endereços sem coordenada
   precisa (bairro, rua, número já preenchidos; coluna "Coordenada" vazia).
2. A pessoa preenche "Coordenada" (ex.: colando "-10.9123, -37.0567" do Google Maps)
   ou as colunas "Latitude" e "Longitude", e guarda o arquivo na pasta
   ``dados/coordenadas/`` (pode haver vários arquivos).
3. Nas próximas análises, essas coordenadas são usadas antes de qualquer consulta ao
   mapa e marcadas com precisão "coletada". Cada endereço só precisa ser coletado uma vez.
"""

import os
import re
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .util import distancia_m, normalizar_coluna, normalizar_logradouro, normalizar_numero, normalizar_texto

COLUNAS_LISTA = ["Bairro", "Rua", "Número", "Complemento", "Casos", "Doenças",
                 "Coordenada", "Latitude", "Longitude", "Observação"]
NOME = {"dengue": "Dengue", "chikungunya": "Chikungunya", "zika": "Zika"}
EXTENSOES = (".xlsx", ".xlsm", ".csv", ".txt")


def chave(bairro, rua_normalizada, numero_normalizado):
    return (normalizar_texto(bairro), rua_normalizada, numero_normalizado)


def interpretar(coordenada="", latitude="", longitude=""):
    """Aceita "lat, lon" (como o Google Maps copia) ou latitude/longitude separadas.
    Vírgula decimal também vale ("-10,9123; -37,0567")."""
    def num(t):
        try:
            return float(str(t).strip().replace(",", "."))
        except ValueError:
            return None

    lat, lon = num(latitude) if latitude not in (None, "") else None, num(longitude) if longitude not in (None, "") else None
    if (lat is None or lon is None) and coordenada:
        texto = str(coordenada).strip()
        if texto.count(",") >= 3 or ";" in texto:  # vírgula decimal
            partes = re.split(r"[;\s]+|,\s+", texto)
        else:
            partes = re.split(r"[,;\s]+", texto)
        numeros = [num(p) for p in partes if re.fullmatch(r"-?\d+(?:[.,]\d+)?", p.strip())]
        if len(numeros) >= 2:
            lat, lon = numeros[0], numeros[1]
    if lat is None or lon is None:
        return None
    return lat, lon


def ler_pasta(pasta):
    """Arquivos (conteúdo, nome) da pasta de coordenadas coletadas."""
    if not pasta or not os.path.isdir(pasta):
        return []
    fontes = []
    for nome in sorted(os.listdir(pasta)):
        if nome.startswith(("~$", ".")) or not nome.lower().endswith(EXTENSOES):
            continue
        with open(os.path.join(pasta, nome), "rb") as f:
            fontes.append((f.read(), nome))
    return fontes


def carregar(fontes, cadastro, config):
    """Lê as coordenadas coletadas. Retorna (dicionário chave->(lat, lon), avisos)."""
    from .leitura import ler_arquivo  # evita import circular

    centro = (config.get("centro_municipio_latitude"), config.get("centro_municipio_longitude"))
    raio = float(config.get("raio_municipio_km", 25)) * 1000
    coletadas, avisos = {}, []
    for conteudo, nome in fontes:
        try:
            df = ler_arquivo(conteudo, nome)
        except Exception as erro:
            avisos.append(f"Não consegui ler '{nome}': {erro}")
            continue
        cols = {normalizar_coluna(c): c for c in df.columns}

        def pega(linha, *nomes):
            for n in nomes:
                if n in cols:
                    return str(linha[cols[n]] or "").strip()
            return ""

        for i, linha in df.iterrows():
            coord = interpretar(pega(linha, "COORDENADA", "COORDENADAS"),
                                pega(linha, "LATITUDE", "LAT"), pega(linha, "LONGITUDE", "LON", "LNG"))
            if coord is None:
                continue  # ainda não coletada
            bairro = pega(linha, "BAIRRO")
            rua = pega(linha, "RUA", "LOGRADOURO", "ENDERECO")
            if not bairro or not rua:
                avisos.append(f"'{nome}', linha {i + 2}: coordenada sem bairro ou rua, ignorada.")
                continue
            if centro[0] is not None and distancia_m(coord[0], coord[1], float(centro[0]), float(centro[1])) > raio:
                avisos.append(f"'{nome}', linha {i + 2}: coordenada {coord[0]}, {coord[1]} fora do município "
                              "(confira o sinal de menos e a ordem latitude, longitude), ignorada.")
                continue
            reg = cadastro.get(normalizar_texto(bairro))
            nome_bairro = reg["bairro"] if reg else bairro
            coletadas[chave(nome_bairro, normalizar_logradouro(rua), normalizar_numero(pega(linha, "NUMERO")))] = coord
    return coletadas, avisos


def aplicar(casos, coletadas):
    """Usa as coordenadas coletadas. Endereço exato primeiro; se a coleta foi feita só para
    a rua (sem número), vale para os casos daquela rua sem coordenada coletada."""
    usadas = 0
    if not coletadas:
        return 0
    for c in casos:
        if not c.get("vv_confirmado") or not c.get("vv_logradouro_norm"):
            continue
        ponto = coletadas.get(chave(c["vv_bairro"], c["vv_logradouro_norm"], c.get("vv_numero_norm", "")))
        if ponto is None:
            ponto = coletadas.get(chave(c["vv_bairro"], c["vv_logradouro_norm"], ""))
        if ponto:
            c["vv_latitude"], c["vv_longitude"] = round(ponto[0], 6), round(ponto[1], 6)
            c["vv_precisao_localizacao"] = "coletada"
            usadas += 1
    return usadas


def gravar_lista(caminho, casos):
    """Endereços (únicos) que ficaram só no centro do bairro ou sem localização."""
    grupos = defaultdict(list)
    for c in casos:
        if c.get("vv_confirmado") and c.get("vv_precisao_localizacao") in ("bairro", "sem_localizacao"):
            if not c.get("vv_logradouro_norm"):
                continue  # sem rua: não há o que coletar
            grupos[chave(c["vv_bairro"], c["vv_logradouro_norm"], c.get("vv_numero_norm", ""))].append(c)
    linhas = []
    for lista in grupos.values():
        c0 = lista[0]
        doencas = sorted({NOME.get(c["vv_agravo"], c["vv_agravo"]) for c in lista})
        complementos = " | ".join(sorted({c.get("vv_complemento", "") for c in lista if c.get("vv_complemento")}))
        linhas.append([c0["vv_bairro"], c0.get("vv_logradouro", ""), c0.get("vv_numero", ""), complementos,
                       len(lista), ", ".join(doencas), None, None, None, None])
    linhas.sort(key=lambda l: (normalizar_texto(l[0]), normalizar_texto(l[1]), str(l[2])))

    wb = Workbook()
    ws = wb.active
    ws.title = "A coletar"
    ws.append(COLUNAS_LISTA)
    for l in linhas:
        ws.append(l)
    for cel in ws[1]:
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor="0B7A5A")
        cel.alignment = Alignment(wrap_text=True)
    for cel in ws["G"][1:]:
        cel.fill = PatternFill("solid", fgColor="FFF2CC")
    ws.freeze_panes = "A2"
    if linhas:
        ws.auto_filter.ref = ws.dimensions
    for letra, largura in zip("ABCDEFGHIJ", (20, 38, 9, 30, 7, 22, 26, 12, 12, 25)):
        ws.column_dimensions[letra].width = largura

    ajuda = wb.create_sheet("Como preencher")
    for texto in [
        "Como preencher",
        "1. No Google Maps, toque e segure no local da casa: aparecem as coordenadas (ex.: -10.9123, -37.0567).",
        "2. Copie e cole na coluna 'Coordenada' da aba 'A coletar' (ou preencha 'Latitude' e 'Longitude').",
        "3. Em Aracaju a latitude começa com -10 ou -11 e a longitude com -37 (os dois com sinal de menos).",
        "4. Não precisa preencher tudo de uma vez: linhas sem coordenada são ignoradas.",
        "5. Guarde o arquivo na pasta dados/coordenadas/ do analisador (ou envie junto na página web).",
        "6. Na próxima análise essas coordenadas são usadas e o endereço sai desta lista.",
        "Se só souber a rua (sem a casa), apague o número: a coordenada vale para os casos da rua.",
    ]:
        ajuda.append([texto])
    ajuda["A1"].font = Font(bold=True)
    ajuda.column_dimensions["A"].width = 110
    wb.save(caminho)
    return len(linhas)
