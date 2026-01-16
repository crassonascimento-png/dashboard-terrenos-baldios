from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
    UserMixin,
)
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime
from sqlalchemy import func

import csv
import io

import os



# Configuração básica do app
app = Flask(__name__)
app.config["SECRET_KEY"] = "troque-esta-chave-por-uma-frase-bem-difícil"

# Caminho do banco de dados SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "dados.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Configuração de upload de imagens
UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # limite: 10 MB por requisição

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)


# Configuração de login
login_manager = LoginManager(app)
login_manager.login_view = "login"


# ------------------------
# MODELOS DO BANCO
# ------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)


    def set_password(self, senha: str):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha: str) -> bool:
        return check_password_hash(self.senha_hash, senha)


class TerrenoBaldio(db.Model):
    __tablename__ = "terrenos_baldios"

    id = db.Column(db.Integer, primary_key=True)
    bairro = db.Column(db.String(100), nullable=False)
    microarea = db.Column(db.String(50))
    endereco = db.Column(db.String(200), nullable=False)
    referencia = db.Column(db.String(200))
    tem_lixo = db.Column(db.Boolean, default=False)
    tem_agua_parada = db.Column(db.Boolean, default=False)
    risco = db.Column(db.String(20), default="Baixo")
    situacao = db.Column(db.String(20), default="Pendente")
    observacoes = db.Column(db.Text)

    latitude = db.Column(db.String(30))   # já deixo aqui pro mapa
    longitude = db.Column(db.String(30))  # strings pra simplificar

    criado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    criado_por = db.relationship("User", backref="terrenos")

    fotos = db.relationship(
        "TerrenoFoto",
        backref="terreno",
        lazy=True,
        cascade="all, delete-orphan",
    )

    historico = db.relationship(
        "TerrenoHistoricoSituacao",
        backref="terreno",
        lazy=True,
        order_by="TerrenoHistoricoSituacao.data_hora.desc()",
        cascade="all, delete-orphan",
    )


class TerrenoHistoricoSituacao(db.Model):
    __tablename__ = "terreno_historico_situacao"

    id = db.Column(db.Integer, primary_key=True)
    terreno_id = db.Column(db.Integer, db.ForeignKey("terrenos_baldios.id"), nullable=False)
    data_hora = db.Column(db.DateTime, default=datetime.utcnow)
    situacao_anterior = db.Column(db.String(20))
    situacao_nova = db.Column(db.String(20))
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    usuario = db.relationship("User")


class TerrenoFoto(db.Model):
    __tablename__ = "terreno_fotos"

    id = db.Column(db.Integer, primary_key=True)
    arquivo = db.Column(db.String(255), nullable=False)
    terreno_id = db.Column(db.Integer, db.ForeignKey("terrenos_baldios.id"), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ------------------------
# ROTAS
# ------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# ==== Inicialização das tabelas no banco (Render e local) ====


@app.route("/initdb")
def initdb():
    """Rota manual para criar as tabelas no banco, se necessário."""
    db.create_all()
    return "Banco inicializado com sucesso."


@app.route("/registro", methods=["GET", "POST"])
def registro():
    # Garante que as tabelas (incluindo users) existem
    db.create_all()
    
    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = request.form["senha"]

        # Verifica se já existe usuário com esse e-mail
        if User.query.filter_by(email=email).first():
            flash("E-mail já cadastrado.", "danger")
            return redirect(url_for("registro"))

        # Se for o primeiro usuário do sistema, torna admin
        is_admin = False
        if User.query.count() == 0:
            is_admin = True

        usuario = User(nome=nome, email=email, is_admin=is_admin)
        usuario.set_password(senha)
        db.session.add(usuario)
        db.session.commit()

        flash("Cadastro realizado com sucesso. Faça login.", "success")
        return redirect(url_for("login"))

    return render_template("registro.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        senha = request.form["senha"]

        usuario = User.query.filter_by(email=email).first()
        if usuario and usuario.check_password(senha):
            login_user(usuario)
            return redirect(url_for("dashboard"))
        else:
            flash("E-mail ou senha inválidos.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    # filtros vindos da query string (?bairro=...&risco=...&situacao=...)
    bairro = request.args.get("bairro", "").strip()
    risco = request.args.get("risco", "").strip()
    situacao = request.args.get("situacao", "").strip()

    # base da query de acordo com o perfil
    if current_user.is_admin:
        base_query = TerrenoBaldio.query
    else:
        base_query = TerrenoBaldio.query.filter_by(criado_por_id=current_user.id)

    # query usada para listar terrenos com filtros
    query = base_query

    if bairro:
        query = query.filter(TerrenoBaldio.bairro == bairro)

    if risco:
        query = query.filter(TerrenoBaldio.risco == risco)

    if situacao:
        query = query.filter(TerrenoBaldio.situacao == situacao)

    terrenos = query.order_by(TerrenoBaldio.id.desc()).all()

    # lista de bairros para preencher o select de filtro
    bairros = [
        b[0]
        for b in base_query.with_entities(TerrenoBaldio.bairro)
        .distinct()
        .order_by(TerrenoBaldio.bairro)
        .all()
    ]

    riscos_lista = ["Baixo", "Médio", "Alto"]
    situacoes_lista = ["Pendente", "Em limpeza", "Limpo", "Reincidente"]
    # Indicadores (sempre usando a base_query, não o query filtrado)
    totais_por_situacao = (
        base_query.with_entities(TerrenoBaldio.situacao, func.count(TerrenoBaldio.id))
        .group_by(TerrenoBaldio.situacao)
        .all()
    )
    totais_por_risco = (
        base_query.with_entities(TerrenoBaldio.risco, func.count(TerrenoBaldio.id))
        .group_by(TerrenoBaldio.risco)
        .all()
    )

    totais_situacao = {s: c for s, c in totais_por_situacao}
    totais_risco = {r: c for r, c in totais_por_risco}
    total_geral = base_query.count()

    return render_template(
        "dashboard.html",
        terrenos=terrenos,
        bairros=bairros,
        bairro_selecionado=bairro,
        riscos_lista=riscos_lista,
        risco_selecionado=risco,
        situacoes_lista=situacoes_lista,
        situacao_selecionada=situacao,
        totais_situacao=totais_situacao,
        totais_risco=totais_risco,
        total_geral=total_geral,
    )

@app.route("/exportar")
@login_required
def exportar():
    # mesmos filtros do dashboard
    bairro = request.args.get("bairro", "").strip()
    risco = request.args.get("risco", "").strip()
    situacao = request.args.get("situacao", "").strip()

    if current_user.is_admin:
        base_query = TerrenoBaldio.query
    else:
        base_query = TerrenoBaldio.query.filter_by(criado_por_id=current_user.id)

    query = base_query

    if bairro:
        query = query.filter(TerrenoBaldio.bairro == bairro)

    if risco:
        query = query.filter(TerrenoBaldio.risco == risco)

    if situacao:
        query = query.filter(TerrenoBaldio.situacao == situacao)

    terrenos = query.order_by(TerrenoBaldio.id.desc()).all()

    # gerar CSV em memória
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    # cabeçalho
    writer.writerow([
        "ID",
        "Bairro",
        "Microárea",
        "Endereço",
        "Ponto de referência",
        "Tem lixo",
        "Tem água parada",
        "Risco",
        "Situação",
        "Observações",
        "Criado por",
        "Qtde fotos",
    ])

    for t in terrenos:
        writer.writerow([
            t.id,
            t.bairro,
            t.microarea or "",
            t.endereco,
            t.referencia or "",
            "Sim" if t.tem_lixo else "Não",
            "Sim" if t.tem_agua_parada else "Não",
            t.risco,
            t.situacao,
            (t.observacoes or "").replace("\n", " ").replace("\r", " "),
            t.criado_por.nome if t.criado_por else "",
            len(t.fotos),
        ])

    csv_data = output.getvalue()
    output.close()

    from flask import make_response

    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=terrenos_baldios.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"

    return response

from werkzeug.utils import secure_filename
import uuid
import os

@app.route("/terrenos/novo", methods=["GET", "POST"])
@login_required
def novo_terreno():
    if request.method == "POST":
        bairro = request.form["bairro"]
        microarea = request.form.get("microarea")
        endereco = request.form["endereco"]
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        referencia = request.form.get("referencia")
        tem_lixo = "tem_lixo" in request.form
        tem_agua_parada = "tem_agua_parada" in request.form
        risco = request.form["risco"]
        situacao = request.form.get("situacao", "Pendente")
        observacoes = request.form.get("observacoes")

        terreno = TerrenoBaldio(
            bairro=bairro,
            microarea=microarea,
            endereco=endereco,
            referencia=referencia,
            tem_lixo=tem_lixo,
            tem_agua_parada=tem_agua_parada,
            risco=risco,
            situacao=situacao,
            observacoes=observacoes,
            latitude=latitude,
            longitude=longitude,
            criado_por=current_user,
        )

        db.session.add(terreno)
        db.session.commit()

        # Tratamento das fotos (max = 5)
        arquivos = request.files.getlist("fotos")
        max_fotos = 5
        contador = 0

        for arquivo in arquivos:
            if arquivo and allowed_file(arquivo.filename):
                if contador >= max_fotos:
                    flash("Apenas as 5 primeiras fotos foram salvas.", "warning")
                    break

                filename = secure_filename(arquivo.filename)
                filename = f"{terreno.id}_{contador}_{filename}"

                caminho = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                arquivo.save(caminho)

                foto = TerrenoFoto(arquivo=filename, terreno_id=terreno.id)
                db.session.add(foto)

                contador += 1

        db.session.commit()

        flash("Terreno baldio cadastrado com sucesso.", "success")
        return redirect(url_for("dashboard"))

    # lista de situações para o select
    situacoes_lista = ["Pendente", "Em limpeza", "Limpo", "Reincidente"]
    return render_template("novo_terreno.html", situacoes_lista=situacoes_lista)

@app.route("/terrenos/<int:terreno_id>")
@login_required
def terreno_detalhe(terreno_id):
    # Garante que qualquer tabela nova (como TerrenoFoto) exista
    db.create_all()

    # Regra de permissão:
    # - Admin pode ver qualquer terreno
    # - ACE só pode ver os terrenos que ele mesmo cadastrou
  
flash("Você não tem permissão para visualizar este terreno.", "danger")



@app.route("/terrenos/<int:terreno_id>/editar", methods=["GET", "POST"])
@login_required
def terreno_editar(terreno_id):
    terreno = TerrenoBaldio.query.get_or_404(terreno_id)

    # Permissão:
    # - Admin pode editar qualquer terreno
    # - ACE só pode editar os que ele mesmo cadastrou
    if not current_user.is_admin and terreno.criado_por_id != current_user.id:
        flash("Você não tem permissão para editar este terreno.", "danger")
        return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))

    riscos_lista = ["Baixo", "Médio", "Alto"]

    if request.method == "POST":
        terreno.bairro = request.form["bairro"]
        terreno.microarea = request.form.get("microarea")
        terreno.endereco = request.form["endereco"]
        terreno.referencia = request.form.get("referencia")
        terreno.tem_lixo = "tem_lixo" in request.form
        terreno.tem_agua_parada = "tem_agua_parada" in request.form
        terreno.risco = request.form["risco"]
        terreno.latitude = request.form.get("latitude")
        terreno.longitude = request.form.get("longitude")
        terreno.observacoes = request.form.get("observacoes")

        # 🔹 Tratamento das novas fotos
        arquivos = request.files.getlist("novas_fotos")
        max_fotos_total = 15  # ajuste se quiser mais/menos
        fotos_existentes = len(terreno.fotos)
        espaco_restante = max_fotos_total - fotos_existentes

        if arquivos and espaco_restante <= 0:
            flash("Este terreno já atingiu o limite máximo de fotos.", "warning")
        else:
            adicionadas = 0
            for i, arquivo in enumerate(arquivos):
                if not arquivo or not allowed_file(arquivo.filename):
                    continue

                if adicionadas >= espaco_restante:
                    flash(
                        f"Limite de {max_fotos_total} fotos por terreno atingido. "
                        "Algumas fotos extras não foram salvas.",
                        "warning",
                    )
                    break

                filename = secure_filename(arquivo.filename)
                # Garante nome único, aproveitando qtd de fotos já existentes
                index = fotos_existentes + adicionadas
                filename = f"{terreno.id}_{index}_{filename}"

                caminho = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                arquivo.save(caminho)

                foto = TerrenoFoto(arquivo=filename, terreno_id=terreno.id)
                db.session.add(foto)

                adicionadas += 1

            if adicionadas > 0:
                flash(f"{adicionadas} nova(s) foto(s) adicionada(s) ao terreno.", "success")

        db.session.commit()

        flash("Terreno atualizado com sucesso.", "success")
        return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))

    return render_template(
        "terreno_editar.html",
        terreno=terreno,
        riscos_lista=riscos_lista,
    )



@app.route("/terrenos/<int:terreno_id>/atualizar_situacao", methods=["POST"])
@login_required
def atualizar_situacao(terreno_id):
    terreno = TerrenoBaldio.query.get_or_404(terreno_id)

    # Regra de permissão
    if not current_user.is_admin and terreno.criado_por_id != current_user.id:
        flash("Você não tem permissão para atualizar a situação deste terreno.", "danger")
        return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))

    nova_situacao = request.form.get("situacao", "").strip()
    situacoes_validas = ["Pendente", "Em limpeza", "Limpo", "Reincidente"]

    if nova_situacao not in situacoes_validas:
        flash("Situação inválida selecionada.", "danger")
        return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))

    situacao_anterior = terreno.situacao

    # Se não mudou nada, não grava histórico atoa
    if situacao_anterior == nova_situacao:
        flash("A situação já estava definida como essa.", "info")
        return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))

    terreno.situacao = nova_situacao

    registro = TerrenoHistoricoSituacao(
        terreno_id=terreno.id,
        situacao_anterior=situacao_anterior,
        situacao_nova=nova_situacao,
        usuario_id=current_user.id,
    )

    db.session.add(registro)
    db.session.commit()

    flash("Situação atualizada com sucesso.", "success")
    return redirect(url_for("terreno_detalhe", terreno_id=terreno.id))



if __name__ == "__main__":
    # Execução local
    app.run(host="0.0.0.0", port=5000, debug=True)



