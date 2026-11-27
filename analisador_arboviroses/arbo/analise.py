"""Cálculos epidemiológicos: bairros, semanas, mapa e alertas."""

from collections import defaultdict
from datetime import date, timedelta

from .util import distancia_m, inicio_semana, semana_epidemiologica

AGRAVOS = ("dengue", "chikungunya", "zika")
NOME_AGRAVO = {"dengue": "Dengue", "chikungunya": "Chikungunya", "zika": "Zika"}


def _data(valor):
    return date.fromisoformat(valor) if valor else None


def _num(valor):
    return None if valor in ("", None) else float(valor)


def _janela(data_ref, semanas):
    """Datas (início, fim) das últimas ``semanas`` semanas epidemiológicas até data_ref."""
    fim = inicio_semana(data_ref) + timedelta(days=6)
    inicio = inicio_semana(data_ref) - timedelta(weeks=semanas - 1)
    return inicio, fim


def _incidencia(casos, populacao):
    if not populacao:
        return None
    return round(casos * 100000 / populacao, 1)


def _nivel_incidencia(valor, limites):
    if valor is None:
        return "sem_populacao"
    if valor >= limites["alta"]:
        return "alta"
    if valor >= limites["media"]:
        return "media"
    return "baixa"


def associar_bairros(casos, cadastro):
    """Completa microárea/coordenadas pelo cadastro e lista bairros não cadastrados."""
    nao_cadastrados = defaultdict(int)
    for c in casos:
        registro = cadastro.get(c["vv_bairro_norm"])
        c["_cadastro"] = registro
        if registro:
            c["vv_bairro"] = registro["bairro"]
            if not c["vv_microarea"] and registro.get("microarea"):
                c["vv_microarea"] = registro["microarea"]
        elif c["vv_bairro_norm"] and c["vv_confirmado"]:
            nao_cadastrados[c["vv_bairro"]] += 1
    return dict(sorted(nao_cadastrados.items(), key=lambda kv: -kv[1]))


def geocodificar(casos, geocodificador, maximo=None):
    """Define vv_latitude/vv_longitude e vv_precisao_localizacao para os confirmados."""
    novas = 0
    for c in casos:
        if not c["vv_confirmado"] or c["vv_precisao_localizacao"] == "arquivo":
            continue
        cad = c.get("_cadastro") or {}
        ref = (cad["latitude"], cad["longitude"]) if cad.get("latitude") is not None and cad.get("longitude") is not None else None
        ponto = None
        if geocodificador and c["vv_endereco"]:
            em_cache = geocodificador.consultas
            if maximo is None or novas < maximo or _no_cache(geocodificador, c):
                ponto = geocodificador.localizar(c["vv_endereco"], c["vv_bairro"], ref)
                novas += geocodificador.consultas - em_cache
        if ponto:
            c["vv_latitude"], c["vv_longitude"] = round(ponto[0], 6), round(ponto[1], 6)
            c["vv_precisao_localizacao"] = "endereco"
        elif ref:
            c["vv_latitude"], c["vv_longitude"] = ref
            c["vv_precisao_localizacao"] = "bairro"
        else:
            c["vv_precisao_localizacao"] = "sem_localizacao"
    return novas


def _no_cache(geocodificador, caso):
    from .util import normalizar_texto

    cfg = geocodificador.config
    municipio, uf = cfg.get("municipio", ""), cfg.get("uf", "")
    partes = [caso["vv_endereco"], caso["vv_bairro"], f"{municipio} - {uf}" if uf else municipio, "Brasil"]
    return normalizar_texto(", ".join(p for p in partes if p)) in geocodificador.cache


def analisar(casos, cadastro, config, data_ref=None):
    """Recebe a lista de casos (dicts) e devolve as estruturas de saída."""
    confirmados = [c for c in casos if c["vv_confirmado"] and c["vv_data_sintomas"]]
    if data_ref is None:
        datas = [_data(c["vv_data_sintomas"]) for c in confirmados]
        data_ref = max(datas) if datas else date.today()
    ano_ref, semana_ref = semana_epidemiologica(data_ref)
    cfg_alerta = config["alertas"]
    limites = config["niveis_incidencia_acumulada"]

    ini4, fim = _janela(data_ref, 4)
    ini2, _ = _janela(data_ref, 2)
    ini_ant, _ = _janela(inicio_semana(data_ref) - timedelta(weeks=2), 2)

    # Só casos até a data de referência entram na análise
    confirmados = [c for c in confirmados if _data(c["vv_data_sintomas"]) <= fim]

    # ---------------- Bairros ----------------
    por_bairro = {}
    for nome_norm, reg in cadastro.items():
        por_bairro.setdefault(reg["bairro"], {"cadastro": reg, "casos": []})
    for c in confirmados:
        nome = c["vv_bairro"] or "Não informado"
        por_bairro.setdefault(nome, {"cadastro": c.get("_cadastro"), "casos": []})["casos"].append(c)

    bairros = []
    for nome, dados in por_bairro.items():
        reg = dados["cadastro"] or {}
        pop = reg.get("populacao")
        linha = {
            "bairro": nome,
            "microarea": reg.get("microarea", "") or _mais_comum([c["vv_microarea"] for c in dados["casos"]]),
            "populacao": pop,
            "latitude": reg.get("latitude"),
            "longitude": reg.get("longitude"),
            "cadastrado": bool(reg),
        }
        total_ano = total_4 = 0
        for agravo in AGRAVOS:
            lista = [c for c in dados["casos"] if c["vv_agravo"] == agravo]
            ano = [c for c in lista if c["vv_ano_epi"] == ano_ref]
            ult4 = [c for c in lista if ini4 <= _data(c["vv_data_sintomas"]) <= fim]
            ult2 = [c for c in lista if ini2 <= _data(c["vv_data_sintomas"]) <= fim]
            ant2 = [c for c in lista if ini_ant <= _data(c["vv_data_sintomas"]) < ini2]
            inc_ano = _incidencia(len(ano), pop)
            linha[agravo] = {
                "casos_total_arquivo": len(lista),
                "casos_ano": len(ano),
                "casos_ultimas_4_semanas": len(ult4),
                "casos_ultimas_2_semanas": len(ult2),
                "casos_2_semanas_anteriores": len(ant2),
                "incidencia_ano_100mil": inc_ano,
                "incidencia_4_semanas_100mil": _incidencia(len(ult4), pop),
                "nivel_incidencia": _nivel_incidencia(inc_ano, limites),
                "tendencia": _tendencia(len(ult2), len(ant2)),
                "obitos": sum(1 for c in lista if c["vv_obito_agravo"]),
                "obitos_em_investigacao": sum(1 for c in lista if c["vv_obito_investigacao"]),
                "graves_ou_alarme": sum(1 for c in lista if c["vv_gravidade"]),
            }
            total_ano += len(ano)
            total_4 += len(ult4)
        linha["total_casos_ano"] = total_ano
        linha["total_casos_ultimas_4_semanas"] = total_4
        linha["incidencia_total_ano_100mil"] = _incidencia(total_ano, pop)
        bairros.append(linha)
    bairros.sort(key=lambda b: (-b["total_casos_ultimas_4_semanas"], -b["total_casos_ano"], b["bairro"]))

    # ---------------- Microáreas ----------------
    microareas = defaultdict(lambda: {a: 0 for a in AGRAVOS} | {"ultimas_4_semanas": 0, "total": 0})
    for c in confirmados:
        if c["vv_ano_epi"] != ano_ref:
            continue
        chave = (c["vv_bairro"] or "Não informado", c["vv_microarea"] or "Não informada")
        microareas[chave][c["vv_agravo"]] += 1
        microareas[chave]["total"] += 1
        if ini4 <= _data(c["vv_data_sintomas"]) <= fim:
            microareas[chave]["ultimas_4_semanas"] += 1
    lista_micro = [{"bairro": b, "microarea": m, **v} for (b, m), v in microareas.items()]
    lista_micro.sort(key=lambda x: (-x["ultimas_4_semanas"], -x["total"]))

    # ---------------- Semanas ----------------
    semanas = defaultdict(int)
    for c in confirmados:
        semanas[(c["vv_ano_epi"], c["vv_semana_epi"], c["vv_agravo"])] += 1
    lista_semanas = [{"ano": a, "semana": s, "agravo": g, "casos": n}
                     for (a, s, g), n in sorted(semanas.items())]

    # ---------------- Mapa ----------------
    pessoais = config.get("incluir_dados_pessoais_nas_saidas", True)
    features = []
    for c in confirmados:
        lat, lon = _num(c["vv_latitude"]), _num(c["vv_longitude"])
        if lat is None or lon is None:
            continue
        props = {
            "agravo": c["vv_agravo"],
            "classificacao": c["vv_classificacao"],
            "gravidade": c["vv_gravidade"],
            "evolucao": c["vv_evolucao"],
            "data_sintomas": c["vv_data_sintomas"],
            "ano_epi": c["vv_ano_epi"],
            "semana_epi": c["vv_semana_epi"],
            "bairro": c["vv_bairro"],
            "microarea": c["vv_microarea"],
            "faixa_etaria": c["vv_faixa_etaria"],
            "sexo": c["vv_sexo"],
            "precisao_localizacao": c["vv_precisao_localizacao"],
            "recente": ini4 <= _data(c["vv_data_sintomas"]) <= fim,
        }
        if pessoais:
            props.update({
                "numero_notificacao": c.get("_numero_notificacao", ""),
                "nome": c.get("_nome", ""),
                "endereco": c["vv_endereco"],
                "idade": c["vv_idade_anos"],
            })
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": props})
    mapa_casos = {"type": "FeatureCollection", "features": features}

    mapa_bairros = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [b["longitude"], b["latitude"]]},
         "properties": {k: v for k, v in b.items() if k not in ("latitude", "longitude")}}
        for b in bairros if b["latitude"] is not None and b["longitude"] is not None
    ]}

    # ---------------- Alertas ----------------
    alertas = _alertas(bairros, confirmados, cfg_alerta, data_ref, ini4, fim, (ano_ref, semana_ref))

    # ---------------- Resumo ----------------
    resumo = {
        "data_referencia": data_ref.isoformat(),
        "ano_epidemiologico": ano_ref,
        "semana_epidemiologica": semana_ref,
        "periodo_ultimas_4_semanas": {"inicio": ini4.isoformat(), "fim": fim.isoformat()},
        "agravos": {},
        "total_alertas": len(alertas),
        "alertas_por_nivel": {n: sum(1 for a in alertas if a["nivel"] == n) for n in ("critico", "alerta", "atencao")},
        "localizacao": {p: sum(1 for c in confirmados if c["vv_precisao_localizacao"] == p)
                        for p in ("arquivo", "endereco", "bairro", "sem_localizacao")},
    }
    for agravo in AGRAVOS:
        lista = [c for c in confirmados if c["vv_agravo"] == agravo]
        ano = [c for c in lista if c["vv_ano_epi"] == ano_ref]
        resumo["agravos"][agravo] = {
            "confirmados_arquivo": len(lista),
            "confirmados_ano": len(ano),
            "confirmados_ultimas_4_semanas": sum(1 for c in lista if ini4 <= _data(c["vv_data_sintomas"]) <= fim),
            "obitos_ano": sum(1 for c in ano if c["vv_obito_agravo"]),
            "obitos_em_investigacao_ano": sum(1 for c in ano if c["vv_obito_investigacao"]),
            "graves_ou_alarme_ano": sum(1 for c in ano if c["vv_gravidade"]),
            "por_sexo": _contar(ano, "vv_sexo"),
            "por_faixa_etaria": _contar(ano, "vv_faixa_etaria"),
        }
    pop_total = sum(b["populacao"] or 0 for b in bairros if b["cadastrado"])
    resumo["populacao_cadastrada"] = pop_total or None
    for agravo in AGRAVOS:
        resumo["agravos"][agravo]["incidencia_ano_100mil"] = _incidencia(
            resumo["agravos"][agravo]["confirmados_ano"], pop_total)

    return {
        "resumo": resumo,
        "bairros": bairros,
        "microareas": lista_micro,
        "semanas": lista_semanas,
        "alertas": alertas,
        "mapa_casos": mapa_casos,
        "mapa_bairros": mapa_bairros,
    }


def _contar(casos, campo):
    resultado = defaultdict(int)
    for c in casos:
        resultado[c[campo]] += 1
    return dict(sorted(resultado.items()))


def _mais_comum(valores):
    valores = [v for v in valores if v]
    return max(set(valores), key=valores.count) if valores else ""


def _tendencia(ultimas, anteriores):
    if ultimas == 0 and anteriores == 0:
        return "sem_casos"
    if anteriores == 0:
        return "subindo"
    razao = ultimas / anteriores
    if razao >= 1.2:
        return "subindo"
    if razao <= 0.8:
        return "caindo"
    return "estavel"


NIVEL_ORDEM = {"critico": 0, "alerta": 1, "atencao": 2}


def _alertas(bairros, confirmados, cfg, data_ref, ini4, fim, semana):
    alertas = []
    ano_ref, semana_ref = semana

    def add(tipo, nivel, agravo, bairro, mensagem, valor=None, limite=None, extra=None):
        alerta = {"tipo": tipo, "nivel": nivel, "agravo": agravo, "bairro": bairro,
                  "mensagem": mensagem, "valor": valor, "limite": limite,
                  "ano_epi": ano_ref, "semana_epi": semana_ref}
        if extra:
            alerta.update(extra)
        alertas.append(alerta)

    lim_inc = cfg["incidencia_4_semanas_100mil"]
    cfg_aum = cfg["aumento_casos"]
    for b in bairros:
        for agravo in AGRAVOS:
            d = b[agravo]
            nome = NOME_AGRAVO[agravo]
            inc = d["incidencia_4_semanas_100mil"]
            if inc is not None and d["casos_ultimas_4_semanas"] > 0:
                for nivel in ("critico", "alerta", "atencao"):
                    if inc >= lim_inc[nivel]:
                        add("incidencia_alta", nivel, agravo, b["bairro"],
                            f"{nome}: incidência de {inc:g}/100 mil hab. nas últimas 4 semanas "
                            f"({d['casos_ultimas_4_semanas']} casos) em {b['bairro']}.",
                            inc, lim_inc[nivel])
                        break
            u, a = d["casos_ultimas_2_semanas"], d["casos_2_semanas_anteriores"]
            if u >= cfg_aum["minimo_casos"] and u >= cfg_aum["fator"] * max(a, 1) and u > a:
                add("aumento_casos", "alerta" if u >= 2 * cfg_aum["minimo_casos"] else "atencao",
                    agravo, b["bairro"],
                    f"{nome}: casos subiram de {a} para {u} (últimas 2 semanas x 2 anteriores) em {b['bairro']}.",
                    u, round(cfg_aum["fator"] * max(a, 1), 1), {"casos_anteriores": a})

    for c in confirmados:
        if not (ini4 <= _data(c["vv_data_sintomas"]) <= fim):
            continue
        nome = NOME_AGRAVO.get(c["vv_agravo"], c["vv_agravo"])
        if c["vv_obito_agravo"]:
            add("obito", "critico", c["vv_agravo"], c["vv_bairro"],
                f"Óbito por {nome} em {c['vv_bairro'] or 'bairro não informado'} "
                f"(sintomas em {c['vv_data_sintomas']}).")
        elif c["vv_obito_investigacao"]:
            add("obito_em_investigacao", "alerta", c["vv_agravo"], c["vv_bairro"],
                f"Óbito em investigação ({nome}) em {c['vv_bairro'] or 'bairro não informado'}.")
        elif c["vv_gravidade"] == "grave" and cfg.get("alertar_dengue_grave", True):
            add("dengue_grave", "alerta", c["vv_agravo"], c["vv_bairro"],
                f"Caso de dengue grave em {c['vv_bairro'] or 'bairro não informado'} "
                f"(sintomas em {c['vv_data_sintomas']}).")

    alertas.extend(_aglomerados(confirmados, cfg["aglomerado"], data_ref, ano_ref, semana_ref))
    alertas.sort(key=lambda x: (NIVEL_ORDEM[x["nivel"]], x["tipo"], x["bairro"] or ""))
    return alertas


def _aglomerados(confirmados, cfg, data_ref, ano_ref, semana_ref):
    """Casos com endereço próximos no espaço e no tempo (qualquer arbovirose: mesmo vetor)."""
    janela = timedelta(days=cfg["janela_dias"])
    pontos = [c for c in confirmados
              if c["vv_precisao_localizacao"] in ("endereco", "arquivo")
              and data_ref - janela <= _data(c["vv_data_sintomas"]) <= data_ref]
    pai = list(range(len(pontos)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(len(pontos)):
        for j in range(i + 1, len(pontos)):
            a, b = pontos[i], pontos[j]
            if abs((_data(a["vv_data_sintomas"]) - _data(b["vv_data_sintomas"])).days) > cfg["janela_dias"]:
                continue
            if distancia_m(float(a["vv_latitude"]), float(a["vv_longitude"]),
                           float(b["vv_latitude"]), float(b["vv_longitude"])) <= cfg["raio_metros"]:
                pai[raiz(i)] = raiz(j)

    grupos = defaultdict(list)
    for i, c in enumerate(pontos):
        grupos[raiz(i)].append(c)

    alertas = []
    for grupo in grupos.values():
        if len(grupo) < cfg["minimo_casos"]:
            continue
        lat = sum(float(c["vv_latitude"]) for c in grupo) / len(grupo)
        lon = sum(float(c["vv_longitude"]) for c in grupo) / len(grupo)
        bairros = sorted({c["vv_bairro"] for c in grupo if c["vv_bairro"]})
        agravos = sorted({c["vv_agravo"] for c in grupo})
        nivel = "critico" if len(grupo) >= 2 * cfg["minimo_casos"] else "alerta"
        alertas.append({
            "tipo": "aglomerado", "nivel": nivel, "agravo": ",".join(agravos),
            "bairro": ", ".join(bairros),
            "mensagem": f"Aglomerado de {len(grupo)} casos ({', '.join(NOME_AGRAVO.get(a, a) for a in agravos)}) "
                        f"num raio de {cfg['raio_metros']} m nos últimos {cfg['janela_dias']} dias "
                        f"em {', '.join(bairros) or 'local sem bairro'}.",
            "valor": len(grupo), "limite": cfg["minimo_casos"],
            "ano_epi": ano_ref, "semana_epi": semana_ref,
            "latitude": round(lat, 6), "longitude": round(lon, 6),
            "raio_metros": cfg["raio_metros"],
        })
    return alertas
