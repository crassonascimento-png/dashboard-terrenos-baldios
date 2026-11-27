"""Planilha de endereços de casos confirmados enviada pela Secretaria de Saúde.

Formato (uma aba por doença, sem cabeçalho de colunas):

    ENDEREÇOS DOS CASOS CONFIRMADOS CHIKUNGUNYA - AGOSTO A 23 DE OUTUBRO 2026
    BAIRRO | LOGRADOURO | NÚMERO | COMPLEMENTO

Todas as linhas já são casos confirmados. Não há datas, então a análise é
espacial: bairros, ruas, endereços repetidos, aglomerados e cocirculação.
"""

import io
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .analise import associar_bairros, geocodificar
from .util import distancia_m, normalizar_texto

AGRAVOS = ("dengue", "chikungunya", "zika")
NOME = {"dengue": "Dengue", "chikungunya": "Chikungunya", "zika": "Zika"}
NIVEL = {"critico": "Crítico", "alerta": "Alerta", "atencao": "Atenção"}
ORDEM = {"critico": 0, "alerta": 1, "atencao": 2}
COR = {"critico": "F4CCCC", "alerta": "FCE5CD", "atencao": "FFF2CC"}

ABREVIACOES = {
    "AV": "AVENIDA", "AVE": "AVENIDA", "R": "RUA", "TV": "TRAVESSA", "TR": "TRAVESSA", "TRAV": "TRAVESSA",
    "AL": "ALAMEDA", "PC": "PRACA", "PCA": "PRACA", "ROD": "RODOVIA", "EST": "ESTRADA", "CJ": "CONJUNTO",
    "CONJ": "CONJUNTO", "LOT": "LOTEAMENTO", "CONC": "CONDOMINIO", "COND": "CONDOMINIO",
    "DR": "DOUTOR", "DES": "DESEMBARGADOR", "GOV": "GOVERNADOR", "PROF": "PROFESSOR", "PE": "PADRE",
    "STA": "SANTA", "STO": "SANTO", "SEN": "SENADOR", "DEP": "DEPUTADO", "GAL": "GENERAL", "GEN": "GENERAL",
    "CEL": "CORONEL", "MAL": "MARECHAL", "VER": "VEREADOR", "PRES": "PRESIDENTE", "ENG": "ENGENHEIRO",
}

PADRAO_ALERTAS = {
    "bairro_casos": {"atencao": 25, "alerta": 50, "critico": 100},
    "bairro_incidencia_100mil": {"atencao": 100, "alerta": 300, "critico": 500},
    "rua_casos": {"alerta": 5, "critico": 10},
    "endereco_casos": {"alerta": 3, "critico": 5},
    "aglomerado": {"raio_metros": 200, "minimo_casos": 5},
    "cocirculacao_rua_minimo": 5,
}


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _titulo_valido(valor):
    t = normalizar_texto(valor)
    return t.startswith("ENDERE") and "CONFIRMAD" in t


def detectar(conteudo: bytes, nome_arquivo: str) -> bool:
    if os.path.splitext(nome_arquivo.lower())[1] not in (".xlsx", ".xlsm"):
        return False
    try:
        wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception:
        return False
    for ws in wb:
        for linha in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            if linha and _titulo_valido(linha[0]):
                return True
    return False


def _agravo(texto):
    t = normalizar_texto(texto)
    if "CHIK" in t:
        return "chikungunya"
    if "ZIKA" in t:
        return "zika"
    if "DENGUE" in t:
        return "dengue"
    return None


def normalizar_logradouro(texto):
    palavras = normalizar_texto(texto).split()
    return " ".join(ABREVIACOES.get(p, p) for p in palavras)


def normalizar_numero(valor):
    t = normalizar_texto(valor).replace(" ", "")
    if t in ("", "SN", "SNO", "0", "00", "SEMNUMERO", "SNUMERO"):
        return ""
    return t


def ler(conteudo: bytes):
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    casos, abas, avisos, periodo = [], [], [], ""
    for ws in wb:
        linhas = list(ws.iter_rows(values_only=True))
        if not linhas or not _titulo_valido(linhas[0][0] if linhas[0] else None):
            continue
        titulo = str(linhas[0][0]).strip()
        agravo = _agravo(titulo) or _agravo(ws.title) or "dengue"
        if not periodo and "-" in titulo:
            periodo = titulo.split("-", 1)[1].strip()
        n_aba = sem_endereco = 0
        for i, linha in enumerate(linhas[1:], start=2):
            valores = [("" if v is None else str(v).strip()) for v in (list(linha) + [None] * 4)[:4]]
            bairro, logradouro, numero, complemento = valores
            if not any(valores):
                continue
            if normalizar_texto(bairro) == "BAIRRO" and normalizar_texto(logradouro) in ("ENDERECO", "LOGRADOURO", "RUA"):
                continue  # cabeçalho
            logradouro = logradouro.rstrip(",;. ")
            if not logradouro:
                sem_endereco += 1
            n_aba += 1
            num_norm = normalizar_numero(numero)
            log_norm = normalizar_logradouro(logradouro)
            endereco = f"{log_norm}, {num_norm}" if log_norm and num_norm else log_norm
            casos.append({
                "aba": ws.title.strip(), "linha": i, "vv_agravo": agravo, "vv_confirmado": True,
                "bairro_original": bairro, "logradouro_original": logradouro, "numero_original": numero,
                "complemento": complemento,
                "vv_bairro": bairro, "vv_bairro_norm": normalizar_texto(bairro), "vv_microarea": "",
                "vv_logradouro_norm": log_norm, "vv_numero_norm": num_norm, "vv_endereco": endereco,
                "vv_latitude": "", "vv_longitude": "", "vv_precisao_localizacao": "",
            })
        abas.append({"aba": ws.title.strip(), "agravo": agravo, "casos": n_aba, "titulo": titulo})
        if sem_endereco:
            avisos.append(f"Aba '{ws.title.strip()}': {sem_endereco} caso(s) sem rua (contam só no bairro).")
    if not casos:
        raise ValueError("Não encontrei casos na planilha de endereços.")
    return casos, {"periodo": periodo, "abas": abas, "avisos": avisos}


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def _incidencia(n, pop):
    return round(n * 100000 / pop, 1) if pop else None


def _nivel(valor, limites):
    for nivel in ("critico", "alerta", "atencao"):
        if nivel in limites and valor is not None and valor >= limites[nivel]:
            return nivel
    return None


def _contagem(casos):
    c = Counter(x["vv_agravo"] for x in casos)
    return {a: c.get(a, 0) for a in AGRAVOS}


def analisar(casos, cadastro, config, info):
    lim = {**PADRAO_ALERTAS, **config.get("alertas_enderecos", {})}
    total = len(casos)
    alertas = []

    def alerta(tipo, nivel, agravo, bairro, msg, valor=None, limite=None, **extra):
        alertas.append({"nivel": nivel, "tipo": tipo, "agravo": agravo, "bairro": bairro, "mensagem": msg,
                        "valor": valor, "limite": limite, **extra})

    # ---- Bairros ----
    grupos = defaultdict(list)
    for c in casos:
        grupos[c["vv_bairro"] or "Não informado"].append(c)
    bairros = []
    for nome, lista in grupos.items():
        reg = lista[0].get("_cadastro") or {}
        cont = _contagem(lista)
        pop = reg.get("populacao")
        enderecos = Counter(_chave_end(c) for c in lista if _chave_end(c))
        b = {
            "bairro": nome, "populacao": pop, "cadastrado": bool(reg),
            "latitude": reg.get("latitude"), "longitude": reg.get("longitude"),
            **cont, "total": len(lista),
            "percentual_do_municipio": round(100 * len(lista) / total, 1),
            "incidencia_100mil": _incidencia(len(lista), pop),
            "dengue_incidencia_100mil": _incidencia(cont["dengue"], pop),
            "chikungunya_incidencia_100mil": _incidencia(cont["chikungunya"], pop),
            "ruas_com_casos": len({c["vv_logradouro_norm"] for c in lista if c["vv_logradouro_norm"]}),
            "enderecos_com_2_ou_mais_casos": sum(1 for n in enderecos.values() if n >= 2),
        }
        if pop:
            b["nivel"] = _nivel(b["incidencia_100mil"], lim["bairro_incidencia_100mil"]) or "baixo"
        else:
            b["nivel"] = _nivel(len(lista), lim["bairro_casos"]) or "baixo"
        bairros.append(b)
    bairros.sort(key=lambda b: (-b["total"], b["bairro"]))
    for pos, b in enumerate(bairros, start=1):
        b["ranking"] = pos
        if b["nivel"] in NIVEL:
            if b["incidencia_100mil"] is not None:
                msg = (f"{b['bairro']}: {b['total']} casos ({b['dengue']} dengue, {b['chikungunya']} chikungunya), "
                       f"incidência {b['incidencia_100mil']:g}/100 mil hab.")
                alerta("bairro_incidencia", b["nivel"], "todas", b["bairro"], msg, b["incidencia_100mil"],
                       lim["bairro_incidencia_100mil"][b["nivel"]])
            else:
                msg = (f"{b['bairro']}: {b['total']} casos ({b['dengue']} dengue, {b['chikungunya']} chikungunya) "
                       f"— {pos}º bairro com mais casos ({b['percentual_do_municipio']:g}% do município).")
                alerta("bairro_casos", b["nivel"], "todas", b["bairro"], msg, b["total"], lim["bairro_casos"][b["nivel"]])

    # ---- Ruas ----
    por_rua = defaultdict(list)
    for c in casos:
        if c["vv_logradouro_norm"]:
            por_rua[(c["vv_bairro"], c["vv_logradouro_norm"])].append(c)
    ruas = []
    for (bairro, rua), lista in por_rua.items():
        cont = _contagem(lista)
        nome_exibicao = Counter(c["logradouro_original"] for c in lista).most_common(1)[0][0]
        r = {"bairro": bairro, "rua": nome_exibicao, "rua_normalizada": rua, **cont, "total": len(lista),
             "enderecos_distintos": len({_chave_end(c) for c in lista if _chave_end(c)}),
             "numeros": ", ".join(sorted({c["numero_original"] for c in lista if c["numero_original"]},
                                         key=lambda n: (len(n), n)))}
        ruas.append(r)
        nivel = _nivel(len(lista), lim["rua_casos"])
        if nivel:
            alerta("rua_com_muitos_casos", nivel, "todas", bairro,
                   f"{nome_exibicao} ({bairro}): {len(lista)} casos em {r['enderecos_distintos']} endereço(s).",
                   len(lista), lim["rua_casos"][nivel], rua=nome_exibicao)
        if (cont["dengue"] and cont["chikungunya"]
                and cont["dengue"] + cont["chikungunya"] >= lim["cocirculacao_rua_minimo"]):
            alerta("cocirculacao", "atencao", "dengue,chikungunya", bairro,
                   f"{nome_exibicao} ({bairro}): dengue ({cont['dengue']}) e chikungunya ({cont['chikungunya']}) "
                   "na mesma rua.", len(lista), None, rua=nome_exibicao)
    ruas.sort(key=lambda r: (-r["total"], r["bairro"], r["rua"]))

    # ---- Endereços repetidos ----
    por_end = defaultdict(list)
    for c in casos:
        if _chave_end(c):
            por_end[_chave_end(c)].append(c)
    repetidos = []
    for chave, lista in por_end.items():
        if len(lista) < 2:
            continue
        c0 = lista[0]
        cont = _contagem(lista)
        e = {"bairro": c0["vv_bairro"], "rua": c0["logradouro_original"], "numero": c0["numero_original"],
             "complementos": " | ".join(sorted({c["complemento"] for c in lista if c["complemento"]})),
             **cont, "total": len(lista)}
        repetidos.append(e)
        nivel = _nivel(len(lista), lim["endereco_casos"])
        if nivel:
            alerta("endereco_repetido", nivel, "todas", e["bairro"],
                   f"{e['rua']}, {e['numero']} ({e['bairro']}): {len(lista)} casos no mesmo endereço"
                   f"{' — ' + e['complementos'] if e['complementos'] else ''}.",
                   len(lista), lim["endereco_casos"][nivel], rua=e["rua"])
    repetidos.sort(key=lambda e: (-e["total"], e["bairro"]))

    # ---- Aglomerados no mapa ----
    alertas.extend(_aglomerados(casos, lim["aglomerado"]))

    # ---- Mapa ----
    features = []
    for c in casos:
        if c["vv_latitude"] in ("", None):
            continue
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [float(c["vv_longitude"]), float(c["vv_latitude"])]},
                         "properties": {"agravo": c["vv_agravo"], "bairro": c["vv_bairro"],
                                        "endereco": _endereco_exibicao(c), "complemento": c["complemento"],
                                        "precisao_localizacao": c["vv_precisao_localizacao"]}})

    alertas.sort(key=lambda a: (ORDEM[a["nivel"]], a["tipo"], -(a["valor"] or 0)))
    loc = Counter(c["vv_precisao_localizacao"] for c in casos)
    resumo = {
        "tipo": "enderecos_secretaria",
        "periodo": info["periodo"],
        "municipio": config.get("municipio", ""), "uf": config.get("uf", ""),
        "total_casos": total, **{f"total_{a}": v for a, v in _contagem(casos).items()},
        "bairros_com_casos": len(bairros),
        "ruas_com_casos": len(ruas),
        "enderecos_com_2_ou_mais_casos": len(repetidos),
        "total_alertas": len(alertas),
        "alertas_por_nivel": {n: sum(1 for a in alertas if a["nivel"] == n) for n in ORDEM},
        "localizacao": {p: loc.get(p, 0) for p in ("endereco", "bairro", "sem_localizacao")},
        "abas": info["abas"],
        "avisos": info["avisos"],
    }
    return {"resumo": resumo, "alertas": alertas, "bairros": bairros, "ruas": ruas,
            "enderecos_repetidos": repetidos, "mapa_casos": {"type": "FeatureCollection", "features": features}}


def _chave_end(c):
    if not c["vv_logradouro_norm"] or not c["vv_numero_norm"]:
        return None
    return (c["vv_bairro"], c["vv_logradouro_norm"], c["vv_numero_norm"])


def _endereco_exibicao(c):
    partes = [c["logradouro_original"]]
    if c["numero_original"]:
        partes.append(c["numero_original"])
    return ", ".join(p for p in partes if p)


def _aglomerados(casos, cfg):
    pontos = [c for c in casos if c["vv_precisao_localizacao"] == "endereco"]
    raio, minimo = cfg["raio_metros"], cfg["minimo_casos"]
    # Grade de células do tamanho do raio para não comparar todos com todos
    celula = raio / 111000
    grade = defaultdict(list)
    for i, c in enumerate(pontos):
        grade[(int(float(c["vv_latitude"]) // celula), int(float(c["vv_longitude"]) // celula))].append(i)
    pai = list(range(len(pontos)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for (gx, gy), membros in grade.items():
        vizinhos = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grade.get((gx + dx, gy + dy), [])]
        for i in membros:
            a = pontos[i]
            for j in vizinhos:
                if j <= i:
                    continue
                b = pontos[j]
                if distancia_m(float(a["vv_latitude"]), float(a["vv_longitude"]),
                               float(b["vv_latitude"]), float(b["vv_longitude"])) <= raio:
                    pai[raiz(i)] = raiz(j)
    grupos = defaultdict(list)
    for i, c in enumerate(pontos):
        grupos[raiz(i)].append(c)
    saida = []
    for g in grupos.values():
        if len(g) < minimo:
            continue
        lat = sum(float(c["vv_latitude"]) for c in g) / len(g)
        lon = sum(float(c["vv_longitude"]) for c in g) / len(g)
        bairros = sorted({c["vv_bairro"] for c in g})
        cont = _contagem(g)
        nivel = "critico" if len(g) >= 3 * minimo else "alerta"
        saida.append({"nivel": nivel, "tipo": "aglomerado", "agravo": "todas", "bairro": ", ".join(bairros),
                      "mensagem": f"Aglomerado de {len(g)} casos ({cont['dengue']} dengue, {cont['chikungunya']} "
                                  f"chikungunya) a até {raio} m uns dos outros em {', '.join(bairros)}.",
                      "valor": len(g), "limite": minimo, "latitude": round(lat, 6), "longitude": round(lon, 6)})
    return saida


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _aba(wb, nome, cab, linhas, larguras=None):
    ws = wb.create_sheet(nome)
    ws.append(cab)
    for l in linhas:
        ws.append(["Sim" if v is True else "Não" if v is False else v for v in l])
    for cel in ws[1]:
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor="0B7A5A")
        cel.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if linhas:
        ws.auto_filter.ref = ws.dimensions
    for i, t in enumerate(cab, start=1):
        w = (larguras or {}).get(t)
        if w is None:
            maior = max([len(str(t))] + [len(str(ws.cell(r, i).value or "")) for r in range(2, min(ws.max_row, 300) + 1)])
            w = min(max(9, maior + 2), 50)
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def gravar_excel(caminho, r, casos):
    res = r["resumo"]
    wb = Workbook()
    wb.remove(wb.active)
    linhas = [
        ("Município", f"{res['municipio']} - {res['uf']}"), ("Período", res["periodo"]),
        ("Gerado em", res.get("gerado_em", "")), ("Total de casos confirmados", res["total_casos"]),
        ("Dengue", res["total_dengue"]), ("Chikungunya", res["total_chikungunya"]), ("Zika", res["total_zika"]),
        ("Bairros com casos", res["bairros_com_casos"]), ("Ruas com casos", res["ruas_com_casos"]),
        ("Endereços com 2 ou mais casos", res["enderecos_com_2_ou_mais_casos"]),
        ("Alertas críticos", res["alertas_por_nivel"]["critico"]), ("Alertas", res["alertas_por_nivel"]["alerta"]),
        ("Atenção", res["alertas_por_nivel"]["atencao"]),
        ("Localizados pelo endereço", res["localizacao"]["endereco"]),
        ("Localizados pelo centro do bairro", res["localizacao"]["bairro"]),
        ("Sem localização no mapa", res["localizacao"]["sem_localizacao"]),
    ]
    if res.get("bairros_nao_cadastrados"):
        linhas.append(("Bairros sem cadastro", ", ".join(f"{k} ({v})" for k, v in res["bairros_nao_cadastrados"].items())))
    linhas += [("Aviso", a) for a in res["avisos"]]
    _aba(wb, "Resumo", ["Indicador", "Valor"], linhas, {"Indicador": 38, "Valor": 60})

    ws = _aba(wb, "Alertas", ["Nível", "Tipo", "Bairro", "Mensagem", "Valor", "Limite", "Latitude", "Longitude"],
              [(NIVEL[a["nivel"]], a["tipo"], a["bairro"], a["mensagem"], a["valor"], a["limite"],
                a.get("latitude"), a.get("longitude")) for a in r["alertas"]], {"Mensagem": 90})
    for i, a in enumerate(r["alertas"], start=2):
        ws.cell(i, 1).fill = PatternFill("solid", fgColor=COR[a["nivel"]])

    _aba(wb, "Bairros", ["Ranking", "Bairro", "Dengue", "Chikungunya", "Zika", "Total", "% do município",
                         "População", "Incidência/100 mil", "Nível", "Ruas com casos", "Endereços c/ 2+ casos",
                         "Latitude", "Longitude", "Cadastrado"],
         [(b["ranking"], b["bairro"], b["dengue"], b["chikungunya"], b["zika"], b["total"],
           b["percentual_do_municipio"], b["populacao"], b["incidencia_100mil"], b["nivel"], b["ruas_com_casos"],
           b["enderecos_com_2_ou_mais_casos"], b["latitude"], b["longitude"], b["cadastrado"]) for b in r["bairros"]])

    _aba(wb, "Ruas", ["Bairro", "Rua", "Dengue", "Chikungunya", "Zika", "Total", "Endereços distintos", "Números"],
         [(x["bairro"], x["rua"], x["dengue"], x["chikungunya"], x["zika"], x["total"], x["enderecos_distintos"],
           x["numeros"]) for x in r["ruas"]], {"Números": 50})

    _aba(wb, "Enderecos_Repetidos", ["Bairro", "Rua", "Número", "Complementos", "Dengue", "Chikungunya", "Zika", "Total"],
         [(e["bairro"], e["rua"], e["numero"], e["complementos"], e["dengue"], e["chikungunya"], e["zika"], e["total"])
          for e in r["enderecos_repetidos"]])

    _aba(wb, "Mapa_Casos", ["Latitude", "Longitude", "Doença", "Bairro", "Endereço", "Complemento", "Precisão"],
         [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0], NOME[f["properties"]["agravo"]],
           f["properties"]["bairro"], f["properties"]["endereco"], f["properties"]["complemento"],
           f["properties"]["precisao_localizacao"]) for f in r["mapa_casos"]["features"]])

    _aba(wb, "Casos", ["Doença", "Bairro", "Rua", "Número", "Complemento", "Bairro (planilha)", "Rua padronizada",
                       "Latitude", "Longitude", "Precisão", "Aba de origem", "Linha de origem"],
         [(NOME[c["vv_agravo"]], c["vv_bairro"], c["logradouro_original"], c["numero_original"], c["complemento"],
           c["bairro_original"], c["vv_logradouro_norm"], c["vv_latitude"] or None, c["vv_longitude"] or None,
           c["vv_precisao_localizacao"], c["aba"], c["linha"]) for c in casos])
    wb.save(caminho)


def executar(conteudo, pasta_saida, config, cadastro, geocodificador, gravar_json, gravar_csv):
    casos, info = ler(conteudo)
    nao_cadastrados = associar_bairros(casos, cadastro)
    novas = geocodificar(casos, geocodificador, config.get("geocodificacao_max_por_execucao"))
    if geocodificador:
        geocodificador.salvar_cache()
    r = analisar(casos, cadastro, config, info)
    r["resumo"].update({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "bairros_nao_cadastrados": nao_cadastrados,
        "geocodificacao": {"ativada": bool(geocodificador), "consultas_novas": novas,
                           "erros": geocodificador.erros if geocodificador else 0},
    })
    os.makedirs(pasta_saida, exist_ok=True)
    gravar_excel(os.path.join(pasta_saida, "vigiavetor.xlsx"), r, casos)
    pacote = {"versao_formato": 1, **r}
    gravar_json(os.path.join(pasta_saida, "vigiavetor.json"), pacote)
    gravar_json(os.path.join(pasta_saida, "resumo.json"), r["resumo"])
    gravar_json(os.path.join(pasta_saida, "alertas.json"), r["alertas"])
    gravar_csv(os.path.join(pasta_saida, "alertas.csv"), r["alertas"],
               ["nivel", "tipo", "bairro", "mensagem", "valor", "limite", "latitude", "longitude"])
    gravar_csv(os.path.join(pasta_saida, "bairros.csv"), r["bairros"])
    gravar_csv(os.path.join(pasta_saida, "ruas.csv"), r["ruas"])
    gravar_csv(os.path.join(pasta_saida, "enderecos_repetidos.csv"), r["enderecos_repetidos"],
               ["bairro", "rua", "numero", "complementos", "dengue", "chikungunya", "zika", "total"])
    gravar_json(os.path.join(pasta_saida, "mapa_casos.geojson"), r["mapa_casos"])
    return pacote
