"""Planilha Excel (vigiavetor.xlsx) com uma aba para cada tipo de dado."""

from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

AGRAVOS = ("dengue", "chikungunya", "zika")
NIVEL = {"critico": "Crítico", "alerta": "Alerta", "atencao": "Atenção"}
COR_NIVEL = {"critico": "F4CCCC", "alerta": "FCE5CD", "atencao": "FFF2CC"}


def _valor(v):
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, (dict, list)):
        return ", ".join(f"{k}: {x}" for k, x in v.items()) if isinstance(v, dict) else ", ".join(map(str, v))
    return v


def _aba(wb, nome, cabecalho, linhas, larguras=None):
    ws = wb.create_sheet(nome)
    ws.append(cabecalho)
    for linha in linhas:
        ws.append([_valor(v) for v in linha])
    for celula in ws[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="0B7A5A")
        celula.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if linhas:
        ws.auto_filter.ref = ws.dimensions
    for i, titulo in enumerate(cabecalho, start=1):
        largura = (larguras or {}).get(titulo)
        if largura is None:
            maior = max([len(str(titulo))] + [len(str(ws.cell(r, i).value or "")) for r in range(2, min(ws.max_row, 200) + 1)])
            largura = min(max(10, maior + 2), 45)
        ws.column_dimensions[get_column_letter(i)].width = largura
    return ws


def gravar_excel(caminho, resultado, casos_confirmados, campos_casos):
    r = resultado["resumo"]
    wb = Workbook()
    wb.remove(wb.active)

    # ---- Resumo ----
    linhas = [
        ("Município", f"{r.get('municipio', '')} - {r.get('uf', '')}"),
        ("Semana epidemiológica", f"{r['semana_epidemiologica']}/{r['ano_epidemiologico']}"),
        ("Data de referência", r["data_referencia"]),
        ("Últimas 4 semanas", f"{r['periodo_ultimas_4_semanas']['inicio']} a {r['periodo_ultimas_4_semanas']['fim']}"),
        ("Arquivo de origem", r.get("arquivo_origem", "")),
        ("Gerado em", r.get("gerado_em", "")),
        ("Total de confirmados no arquivo", r.get("total_confirmados")),
        ("Alertas", r["total_alertas"]),
    ]
    for ag in AGRAVOS:
        d = r["agravos"][ag]
        nome = ag.capitalize()
        linhas += [
            (f"{nome}: confirmados no ano", d["confirmados_ano"]),
            (f"{nome}: confirmados nas últimas 4 semanas", d["confirmados_ultimas_4_semanas"]),
            (f"{nome}: incidência no ano (por 100 mil hab.)", d["incidencia_ano_100mil"]),
            (f"{nome}: óbitos no ano", d["obitos_ano"]),
            (f"{nome}: óbitos em investigação", d["obitos_em_investigacao_ano"]),
            (f"{nome}: graves ou com sinais de alarme", d["graves_ou_alarme_ano"]),
        ]
    loc = r["localizacao"]
    linhas += [
        ("Localizados pelo endereço", loc["endereco"] + loc["arquivo"]),
        ("Coordenadas coletadas em campo", loc["coletada"]),
        ("Localizados pela rua (número não encontrado)", loc["rua"]),
        ("Localizados pelo centro do bairro", loc["bairro"]),
        ("Sem localização", loc["sem_localizacao"]),
        ("Bairros sem cadastro", r.get("bairros_nao_cadastrados", {})),
    ]
    linhas += [("Aviso", a) for a in r.get("avisos", [])]
    _aba(wb, "Resumo", ["Indicador", "Valor"], linhas, {"Indicador": 45, "Valor": 45})

    # ---- Alertas ----
    ws = _aba(wb, "Alertas",
              ["Nível", "Tipo", "Doença", "Bairro", "Mensagem", "Valor", "Limite", "Semana", "Latitude", "Longitude"],
              [(NIVEL[a["nivel"]], a["tipo"], a["agravo"], a["bairro"], a["mensagem"], a["valor"], a["limite"],
                f"{a['semana_epi']}/{a['ano_epi']}", a.get("latitude"), a.get("longitude"))
               for a in resultado["alertas"]],
              {"Mensagem": 80})
    for i, a in enumerate(resultado["alertas"], start=2):
        ws.cell(i, 1).fill = PatternFill("solid", fgColor=COR_NIVEL[a["nivel"]])

    # ---- Bairros ----
    cab = ["Bairro", "Microárea", "População", "Latitude", "Longitude", "Cadastrado",
           "Total no ano", "Total últimas 4 sem.", "Incidência total ano/100 mil"]
    for ag in AGRAVOS:
        n = ag.capitalize()
        cab += [f"{n} ano", f"{n} últ. 4 sem.", f"{n} últ. 2 sem.", f"{n} 2 sem. anteriores",
                f"{n} incid. ano/100 mil", f"{n} incid. 4 sem./100 mil", f"{n} nível", f"{n} tendência",
                f"{n} óbitos", f"{n} graves/alarme"]
    linhas = []
    for b in resultado["bairros"]:
        linha = [b["bairro"], b["microarea"], b["populacao"], b["latitude"], b["longitude"], b["cadastrado"],
                 b["total_casos_ano"], b["total_casos_ultimas_4_semanas"], b["incidencia_total_ano_100mil"]]
        for ag in AGRAVOS:
            d = b[ag]
            linha += [d["casos_ano"], d["casos_ultimas_4_semanas"], d["casos_ultimas_2_semanas"],
                      d["casos_2_semanas_anteriores"], d["incidencia_ano_100mil"], d["incidencia_4_semanas_100mil"],
                      d["nivel_incidencia"], d["tendencia"], d["obitos"], d["graves_ou_alarme"]]
        linhas.append(linha)
    _aba(wb, "Bairros", cab, linhas)

    # ---- Microáreas ----
    _aba(wb, "Microareas", ["Bairro", "Microárea", "Dengue", "Chikungunya", "Zika", "Total no ano", "Últimas 4 sem."],
         [(m["bairro"], m["microarea"], m["dengue"], m["chikungunya"], m["zika"], m["total"], m["ultimas_4_semanas"])
          for m in resultado["microareas"]])

    # ---- Semanas (uma linha por semana, uma coluna por doença) ----
    semanas = defaultdict(lambda: {a: 0 for a in AGRAVOS})
    for s in resultado["semanas"]:
        semanas[(s["ano"], s["semana"])][s["agravo"]] += s["casos"]
    _aba(wb, "Semanas", ["Ano", "Semana", "Dengue", "Chikungunya", "Zika", "Total"],
         [(a, s, v["dengue"], v["chikungunya"], v["zika"], sum(v.values())) for (a, s), v in sorted(semanas.items())])

    # ---- Mapa (um ponto por caso) ----
    feats = resultado["mapa_casos"]["features"]
    chaves = list(feats[0]["properties"].keys()) if feats else []
    _aba(wb, "Mapa_Casos", ["latitude", "longitude"] + chaves,
         [[f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]] + [f["properties"].get(k) for k in chaves]
          for f in feats])

    # ---- Casos confirmados (todas as colunas) ----
    _aba(wb, "Casos_Confirmados", campos_casos, [[c.get(k) for k in campos_casos] for c in casos_confirmados])

    wb.save(caminho)
