#!/usr/bin/env python3
"""Linha de comando do analisador de arboviroses.

Exemplos:
    python analisar.py dados/dengue_sinan.csv
    python analisar.py dados/chik.dbf --agravo chikungunya --saida saida/chik
    python analisar.py dados/dengue.xlsx --sem-geocodificacao --data-referencia 2026-11-21
"""

import argparse
import os
import sys
from datetime import date

from arbo.pipeline import carregar_config, executar


def main(argv=None):
    p = argparse.ArgumentParser(description="Analisa casos confirmados de arboviroses (SINAN) para o Vigiavetor.")
    p.add_argument("arquivo", help="Exportação do SINAN (.csv, .txt, .xlsx ou .dbf)")
    p.add_argument("--agravo", choices=["dengue", "chikungunya", "zika"],
                   help="Doença do arquivo, se não houver a coluna ID_AGRAVO")
    p.add_argument("--saida", default="saida", help="Pasta onde gravar os arquivos (padrão: saida)")
    p.add_argument("--config", help="Arquivo de configuração (padrão: config.json)")
    p.add_argument("--bairros", help="Cadastro de bairros (padrão: o definido no config.json)")
    p.add_argument("--data-referencia", help="Data de referência AAAA-MM-DD (padrão: último início de sintomas)")
    p.add_argument("--coordenadas", nargs="*", default=[],
                   help="Planilhas de coordenadas coletadas (além das que estão em dados/coordenadas/)")
    p.add_argument("--sem-geocodificacao", action="store_true", help="Não consultar endereços na internet")
    args = p.parse_args(argv)

    config = carregar_config(args.config)
    with open(args.arquivo, "rb") as f:
        conteudo = f.read()
    bairros = None
    if args.bairros:
        with open(args.bairros, "rb") as f:
            bairros = f.read()
    data_ref = date.fromisoformat(args.data_referencia) if args.data_referencia else None

    try:
        r = executar(conteudo, args.arquivo, args.saida, config=config, agravo_padrao=args.agravo,
                     bairros_conteudo=bairros, data_referencia=data_ref,
                     geocodificar_enderecos=False if args.sem_geocodificacao else None,
                     progresso=lambda m: print(m, file=sys.stderr),
                     coordenadas_conteudos=[(open(c, "rb").read(), c) for c in args.coordenadas])
    except ValueError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    res = r["resumo"]
    if res.get("tipo") == "enderecos_secretaria":
        print(f"\nPeríodo: {res['periodo']}  |  {res['total_casos']} casos "
              f"(dengue {res['total_dengue']}, chikungunya {res['total_chikungunya']}, zika {res['total_zika']})")
        print("  Bairros com mais casos: " + ", ".join(f"{b['bairro']} ({b['total']})" for b in r["bairros"][:8]))
        print(f"  Alertas: {res['total_alertas']} {res['alertas_por_nivel']}")
        for a in r["alertas"][:12]:
            print(f"   [{a['nivel'].upper():8}] {a['mensagem']}")
        print(f"  Localização: {res['localizacao']}")
        print(f"  Coordenadas coletadas usadas: {res.get('coordenadas_coletadas_usadas', 0)}  |  "
              f"endereços ainda a coletar: {res.get('enderecos_a_coletar', 0)} (coordenadas_a_coletar.xlsx)")
        if res["bairros_nao_cadastrados"]:
            print(f"  Bairros sem cadastro: {res['bairros_nao_cadastrados']}")
        for aviso in res["avisos"]:
            print(f"  Aviso: {aviso}")
        print(f"\nArquivos gravados em: {os.path.abspath(args.saida)}")
        return 0
    print(f"\nSemana epidemiológica {res['semana_epidemiologica']}/{res['ano_epidemiologico']} "
          f"(referência {res['data_referencia']})")
    for agravo, d in res["agravos"].items():
        if d["confirmados_arquivo"]:
            print(f"  {agravo:12} confirmados no ano: {d['confirmados_ano']:5}  "
                  f"últimas 4 semanas: {d['confirmados_ultimas_4_semanas']:4}  óbitos: {d['obitos_ano']}")
    print(f"  Alertas: {res['total_alertas']} {res['alertas_por_nivel']}")
    for a in r["alertas"][:10]:
        print(f"   [{a['nivel'].upper():8}] {a['mensagem']}")
    if res["bairros_nao_cadastrados"]:
        print(f"  Bairros do SINAN sem cadastro em bairros.csv: {', '.join(list(res['bairros_nao_cadastrados'])[:10])}")
    for aviso in res["avisos"]:
        print(f"  Aviso: {aviso}")
    print(f"\nArquivos gravados em: {os.path.abspath(args.saida)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
