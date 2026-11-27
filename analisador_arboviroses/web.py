"""Página web do analisador: envie o arquivo do SINAN e baixe os arquivos do Vigiavetor.

Os resultados ficam em uma pasta temporária e são apagados depois de
``RESULTADO_VALIDADE_MIN`` minutos (padrão 60). O arquivo enviado não é guardado.

Variáveis de ambiente:
    ANALISADOR_SENHA       senha de acesso (obrigatória)
    ANALISADOR_SECRET_KEY  chave das sessões do Flask (recomendada em produção)
"""

import hmac
import io
import json
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from datetime import date
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request, send_file,
                   session, url_for)

from arbo.pipeline import carregar_config, executar

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ANALISADOR_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

PASTA_RESULTADOS = os.path.join(tempfile.gettempdir(), "analisador_arboviroses")
VALIDADE_S = int(os.environ.get("RESULTADO_VALIDADE_MIN", "60")) * 60
EXTENSOES = {".csv", ".txt", ".xlsx", ".xls", ".dbf"}
ARQUIVOS = [
    ("vigiavetor_importacao.xlsx", "Planilha no modelo de importação do Vigiavetor"),
    ("vigiavetor.xlsx", "Análise completa em Excel (todas as abas)"),
    ("vigiavetor.json", "Pacote completo em JSON"),
    ("alertas.json", "Alertas"), ("alertas.csv", "Alertas (planilha)"),
    ("bairros.json", "Indicadores por bairro"), ("bairros.csv", "Indicadores por bairro (planilha)"),
    ("microareas.csv", "Casos por microárea (planilha)"),
    ("ruas.csv", "Ruas com casos (planilha)"),
    ("enderecos_repetidos.csv", "Endereços com 2 ou mais casos (planilha)"),
    ("semanas.csv", "Casos por semana epidemiológica"),
    ("mapa_casos.geojson", "Mapa de casos (GeoJSON)"),
    ("mapa_bairros.geojson", "Mapa de bairros (GeoJSON)"),
    ("casos_confirmados.csv", "Casos confirmados (todos os campos)"),
    ("casos_processados.csv", "Todas as notificações processadas"),
    ("resumo.json", "Resumo"),
]


def _senha():
    return os.environ.get("ANALISADOR_SENHA", "")


def login_obrigatorio(f):
    @wraps(f)
    def interna(*a, **kw):
        if not session.get("ok"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return interna


def _limpar_antigos():
    if not os.path.isdir(PASTA_RESULTADOS):
        return
    agora = time.time()
    for nome in os.listdir(PASTA_RESULTADOS):
        caminho = os.path.join(PASTA_RESULTADOS, nome)
        if os.path.isdir(caminho) and agora - os.path.getmtime(caminho) > VALIDADE_S:
            shutil.rmtree(caminho, ignore_errors=True)


def _pasta(token):
    if not token or not all(c in "0123456789abcdef" for c in token) or len(token) != 32:
        abort(404)
    if session.get("token") != token:
        abort(403)
    caminho = os.path.join(PASTA_RESULTADOS, token)
    if not os.path.isdir(caminho):
        abort(404)
    return caminho


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _senha():
        return render_template("login.html", sem_senha=True)
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("senha", "").encode(), _senha().encode()):
            session.clear()
            session["ok"] = True
            return redirect(url_for("inicio"))
        flash("Senha incorreta.")
    return render_template("login.html", sem_senha=False)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
@login_obrigatorio
def inicio():
    config = carregar_config()
    if request.method == "GET":
        return render_template("inicio.html", config=config)

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Escolha o arquivo exportado do SINAN.")
        return redirect(url_for("inicio"))
    if os.path.splitext(arquivo.filename.lower())[1] not in EXTENSOES:
        flash("Formato não aceito. Use CSV, TXT, XLSX ou DBF.")
        return redirect(url_for("inicio"))

    bairros = request.files.get("bairros")
    bairros_conteudo = bairros.read() if bairros and bairros.filename else None
    agravo = request.form.get("agravo") or None
    data_ref = request.form.get("data_referencia") or None
    geocodificar = request.form.get("geocodificar") == "1"
    if geocodificar and config.get("geocodificacao_max_por_execucao") is None:
        # Na web, limita as consultas novas para a página não estourar o tempo limite
        config["geocodificacao_max_por_execucao"] = int(os.environ.get("GEOCODIFICACAO_MAX_WEB", "150"))

    _limpar_antigos()
    token = secrets.token_hex(16)
    pasta = os.path.join(PASTA_RESULTADOS, token)
    try:
        resultado = executar(arquivo.read(), arquivo.filename, pasta, config=config,
                             agravo_padrao=agravo, bairros_conteudo=bairros_conteudo,
                             data_referencia=date.fromisoformat(data_ref) if data_ref else None,
                             geocodificar_enderecos=geocodificar)
    except ValueError as erro:
        shutil.rmtree(pasta, ignore_errors=True)
        flash(str(erro))
        return redirect(url_for("inicio"))
    except Exception as erro:  # arquivo corrompido, formato inesperado...
        shutil.rmtree(pasta, ignore_errors=True)
        app.logger.exception("Falha ao processar")
        flash(f"Não foi possível processar o arquivo: {erro}")
        return redirect(url_for("inicio"))

    session["token"] = token
    return redirect(url_for("resultado", token=token))


@app.route("/resultado/<token>")
@login_obrigatorio
def resultado(token):
    pasta = _pasta(token)
    with open(os.path.join(pasta, "vigiavetor.json"), encoding="utf-8") as f:
        dados = json.load(f)
    arquivos = [(n, d) for n, d in ARQUIVOS if os.path.exists(os.path.join(pasta, n))]
    modelo = "resultado_enderecos.html" if dados["resumo"].get("tipo") == "enderecos_secretaria" else "resultado.html"
    return render_template(modelo, token=token, d=dados, arquivos=arquivos, validade_min=VALIDADE_S // 60)


@app.route("/resultado/<token>/<nome>")
@login_obrigatorio
def baixar(token, nome):
    pasta = _pasta(token)
    if nome not in {n for n, _ in ARQUIVOS} or not os.path.exists(os.path.join(pasta, nome)):
        abort(404)
    return send_file(os.path.join(pasta, nome), as_attachment=True, download_name=nome)


@app.route("/resultado/<token>.zip")
@login_obrigatorio
def baixar_zip(token):
    pasta = _pasta(token)
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, _ in ARQUIVOS:
            if os.path.exists(os.path.join(pasta, nome)):
                z.write(os.path.join(pasta, nome), nome)
    memoria.seek(0)
    return send_file(memoria, as_attachment=True, download_name="vigiavetor_arboviroses.zip",
                     mimetype="application/zip")


@app.after_request
def sem_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", "5001")))
