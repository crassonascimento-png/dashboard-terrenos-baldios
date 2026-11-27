"""Junta as etapas: leitura -> preparo -> localização -> análise -> arquivos."""

import copy
import csv
import json
import os
from datetime import date, datetime

from .analise import AGRAVOS, analisar, associar_bairros, geocodificar
from . import secretaria
from .excel import gravar_excel
from .geocodificacao import Geocodificador
from .leitura import ler_arquivo, ler_bairros, mapear_colunas, preparar_casos

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PADRAO = {
    "municipio": "",
    "uf": "",
    "codigo_municipio_residencia": "",
    "arquivo_bairros": "bairros.csv",
    "incluir_em_investigacao": False,
    "incluir_dados_pessoais_nas_saidas": True,
    "classificacao_confirmada": {"dengue": ["10", "11", "12"], "chikungunya": ["13"], "zika": ["1"]},
    "mapeamento_colunas": {},
    "geocodificar": True,
    "geocodificacao_url": "https://nominatim.openstreetmap.org/search",
    "geocodificacao_user_agent": "analisador-arboviroses/1.0",
    "geocodificacao_intervalo_segundos": 1.1,
    "geocodificacao_raio_max_km": 5,
    "centro_municipio_latitude": None,
    "centro_municipio_longitude": None,
    "raio_municipio_km": 25,
    "geocodificacao_max_por_execucao": None,
    "arquivo_cache_geocodificacao": "cache/geocodificacao.json",
    "niveis_incidencia_acumulada": {"media": 100, "alta": 300},
    "alertas": {
        "incidencia_4_semanas_100mil": {"atencao": 50, "alerta": 100, "critico": 300},
        "aumento_casos": {"minimo_casos": 5, "fator": 1.5},
        "aglomerado": {"raio_metros": 200, "janela_dias": 14, "minimo_casos": 3},
        "alertar_dengue_grave": True,
    },
}


def _mesclar(base, extra):
    resultado = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(resultado.get(k), dict):
            resultado[k] = _mesclar(resultado[k], v)
        else:
            resultado[k] = v
    return resultado


def carregar_config(caminho=None):
    caminho = caminho or os.path.join(PASTA, "config.json")
    extra = {}
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            extra = json.load(f)
    extra = {k: v for k, v in extra.items() if not k.startswith("_")}
    return _mesclar(CONFIG_PADRAO, extra)


def _caminho(relativo):
    if not relativo:
        return None
    return relativo if os.path.isabs(relativo) else os.path.join(PASTA, relativo)


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(str(type(o)))


def _gravar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=_json_default)


def _gravar_csv(caminho, linhas, campos=None):
    if not linhas:
        with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
            f.write(";".join(campos or []) + "\n")
        return
    campos = campos or list(linhas[0].keys())
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for linha in linhas:
            w.writerow({k: ("" if linha.get(k) is None else linha.get(k)) for k in campos})


def _bairros_planos(bairros):
    linhas = []
    for b in bairros:
        linha = {k: b[k] for k in ("bairro", "microarea", "populacao", "latitude", "longitude", "cadastrado",
                                   "total_casos_ano", "total_casos_ultimas_4_semanas", "incidencia_total_ano_100mil")}
        for agravo in AGRAVOS:
            for campo, valor in b[agravo].items():
                linha[f"{agravo}_{campo}"] = valor
        linhas.append(linha)
    return linhas


def executar(conteudo, nome_arquivo, pasta_saida, config=None, agravo_padrao=None,
             bairros_conteudo=None, data_referencia=None, geocodificar_enderecos=None,
             geocodificador=None, progresso=None):
    """Executa toda a análise e grava os arquivos em ``pasta_saida``.

    Retorna o dicionário com resumo, alertas etc. (o mesmo de ``vigiavetor.json``).
    """
    config = config or carregar_config()
    aviso = progresso or (lambda msg: None)
    os.makedirs(pasta_saida, exist_ok=True)

    if secretaria.detectar(conteudo, nome_arquivo):
        aviso("Planilha de endereços da Secretaria detectada.")
        cadastro = ler_bairros(bairros_conteudo) if bairros_conteudo else ler_bairros(_caminho(config.get("arquivo_bairros")))
        usar_geo = config.get("geocodificar", True) if geocodificar_enderecos is None else geocodificar_enderecos
        if usar_geo and geocodificador is None:
            geocodificador = Geocodificador(config, _caminho(config.get("arquivo_cache_geocodificacao")))
        pacote = secretaria.executar(conteudo, pasta_saida, config, cadastro,
                                     geocodificador if usar_geo else None, _gravar_json, _gravar_csv)
        pacote["resumo"]["arquivo_origem"] = os.path.basename(nome_arquivo)
        _gravar_json(os.path.join(pasta_saida, "resumo.json"), pacote["resumo"])
        _gravar_json(os.path.join(pasta_saida, "vigiavetor.json"), pacote)
        return pacote

    aviso("Lendo arquivo...")
    df = ler_arquivo(conteudo, nome_arquivo)
    df, info = preparar_casos(df, config, agravo_padrao)
    colunas = mapear_colunas(df, config.get("mapeamento_colunas"))

    cadastro = ler_bairros(bairros_conteudo) if bairros_conteudo else ler_bairros(_caminho(config.get("arquivo_bairros")))

    casos = df.to_dict(orient="records")
    for c in casos:
        c["_numero_notificacao"] = c.get(colunas["numero_notificacao"], "") if "numero_notificacao" in colunas else ""
        c["_nome"] = c.get(colunas["nome"], "") if "nome" in colunas else ""

    nao_cadastrados = associar_bairros(casos, cadastro)

    usar_geo = config.get("geocodificar", True) if geocodificar_enderecos is None else geocodificar_enderecos
    if usar_geo and geocodificador is None:
        geocodificador = Geocodificador(config, _caminho(config.get("arquivo_cache_geocodificacao")))
    if not usar_geo:
        geocodificador = None
    aviso("Localizando endereços...")
    novas = geocodificar(casos, geocodificador, config.get("geocodificacao_max_por_execucao"))
    if geocodificador:
        geocodificador.salvar_cache()

    aviso("Calculando indicadores...")
    resultado = analisar(casos, cadastro, config, data_referencia)
    resultado["resumo"].update({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "arquivo_origem": os.path.basename(nome_arquivo),
        "municipio": config.get("municipio", ""),
        "uf": config.get("uf", ""),
        "linhas_lidas": info["linhas_lidas"],
        "notificacoes_analisadas": len(casos),
        "duplicadas_removidas": info["duplicadas_removidas"],
        "total_confirmados": sum(1 for c in casos if c["vv_confirmado"]),
        "bairros_nao_cadastrados": nao_cadastrados,
        "geocodificacao": {
            "ativada": bool(geocodificador),
            "consultas_novas": novas,
            "erros": geocodificador.erros if geocodificador else 0,
        },
        "avisos": info["avisos"],
        "colunas_reconhecidas": info["colunas_reconhecidas"],
    })

    aviso("Gravando arquivos...")
    # Casos processados: todas as colunas originais + vv_*
    remover = {"_cadastro", "_numero_notificacao", "_nome", "vv_bairro_norm"}
    linhas = [{k: v for k, v in c.items() if k not in remover} for c in casos]
    if not config.get("incluir_dados_pessoais_nas_saidas", True):
        sensiveis = {colunas.get(k) for k in ("nome", "data_nascimento", "logradouro", "numero", "complemento", "cep")}
        sensiveis |= {"vv_endereco", "vv_cep"}
        linhas = [{k: v for k, v in l.items() if k not in sensiveis} for l in linhas]
    campos = list(linhas[0].keys()) if linhas else []
    _gravar_csv(os.path.join(pasta_saida, "casos_processados.csv"), linhas, campos)
    _gravar_csv(os.path.join(pasta_saida, "casos_confirmados.csv"),
                [l for l in linhas if l.get("vv_confirmado")], campos)

    _gravar_json(os.path.join(pasta_saida, "resumo.json"), resultado["resumo"])
    _gravar_json(os.path.join(pasta_saida, "bairros.json"), resultado["bairros"])
    _gravar_csv(os.path.join(pasta_saida, "bairros.csv"), _bairros_planos(resultado["bairros"]))
    _gravar_json(os.path.join(pasta_saida, "microareas.json"), resultado["microareas"])
    _gravar_csv(os.path.join(pasta_saida, "microareas.csv"), resultado["microareas"])
    _gravar_json(os.path.join(pasta_saida, "semanas.json"), resultado["semanas"])
    _gravar_csv(os.path.join(pasta_saida, "semanas.csv"), resultado["semanas"], ["ano", "semana", "agravo", "casos"])
    _gravar_json(os.path.join(pasta_saida, "alertas.json"), resultado["alertas"])
    _gravar_csv(os.path.join(pasta_saida, "alertas.csv"), resultado["alertas"],
                ["nivel", "tipo", "agravo", "bairro", "mensagem", "valor", "limite", "ano_epi", "semana_epi",
                 "latitude", "longitude"])
    _gravar_json(os.path.join(pasta_saida, "mapa_casos.geojson"), resultado["mapa_casos"])
    _gravar_json(os.path.join(pasta_saida, "mapa_bairros.geojson"), resultado["mapa_bairros"])

    pacote = {"versao_formato": 1, **resultado}
    _gravar_json(os.path.join(pasta_saida, "vigiavetor.json"), pacote)
    gravar_excel(os.path.join(pasta_saida, "vigiavetor.xlsx"), resultado,
                 [l for l in linhas if l.get("vv_confirmado")], campos)
    return pacote
