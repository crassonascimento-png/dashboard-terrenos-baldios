import io
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arbo.leitura import classificar, identificar_agravo, idade_em_anos, ler_arquivo  # noqa: E402
from arbo.pipeline import CONFIG_PADRAO, carregar_config, executar  # noqa: E402
from arbo.util import parse_data, semana_epidemiologica  # noqa: E402

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLO = os.path.join(PASTA, "exemplos", "sinan_exemplo_ficticio.csv")
with open(os.path.join(PASTA, "exemplos", "bairros_exemplo_ficticio.csv"), "rb") as _f:
    BAIRROS_EXEMPLO = _f.read()


@pytest.mark.parametrize("d, esperado", [
    (date(2024, 1, 1), (2024, 1)),     # 2024 começa na segunda; semana 1 = 31/12/2023
    (date(2023, 12, 31), (2024, 1)),
    (date(2023, 12, 30), (2023, 52)),
    (date(2021, 1, 2), (2020, 53)),    # 2020 teve 53 semanas
    (date(2021, 1, 3), (2021, 1)),
    (date(2026, 1, 4), (2026, 1)),
    (date(2026, 11, 21), (2026, 46)),
])
def test_semana_epidemiologica(d, esperado):
    assert semana_epidemiologica(d) == esperado


def test_parse_data():
    assert parse_data("05/03/2026") == date(2026, 3, 5)
    assert parse_data("2026-03-05 00:00:00") == date(2026, 3, 5)
    assert parse_data("20260305") == date(2026, 3, 5)
    assert parse_data("") is None and parse_data("lixo") is None


def test_agravo_e_classificacao():
    cfg = CONFIG_PADRAO
    assert identificar_agravo("A90") == "dengue"
    assert identificar_agravo("A92.0") == "chikungunya"
    assert identificar_agravo("A928") == "zika"
    assert identificar_agravo("", "zika") == "zika"
    assert classificar("11", "dengue", cfg) == (True, "Dengue com sinais de alarme")
    assert classificar("5", "dengue", cfg)[0] is False
    assert classificar("13", "chikungunya", cfg)[0] is True
    assert classificar("1", "zika", cfg)[0] is True
    assert classificar("", "dengue", cfg)[0] is False
    assert classificar("Confirmado", "zika", cfg)[0] is True
    assert classificar("Descartado", "zika", cfg)[0] is False


def test_idade():
    assert idade_em_anos("4035", None, None) == 35
    assert idade_em_anos("3006", None, None) == 0
    assert idade_em_anos("", date(2000, 6, 1), date(2026, 5, 31)) == 25


def test_leitura_csv_latin1_ponto_virgula():
    conteudo = "NM_BAIRRO;CLASSI_FIN\nSÃO JOSÉ;10\n".encode("cp1252")
    df = ler_arquivo(conteudo, "x.csv")
    assert list(df.columns) == ["NM_BAIRRO", "CLASSI_FIN"]
    assert df.iloc[0]["NM_BAIRRO"] == "SÃO JOSÉ"


def test_exemplo_completo(tmp_path):
    with open(EXEMPLO, "rb") as f:
        r = executar(f.read(), EXEMPLO, str(tmp_path), config=carregar_config(),
                     bairros_conteudo=BAIRROS_EXEMPLO, geocodificar_enderecos=False)
    res = r["resumo"]
    assert res["semana_epidemiologica"] == 46
    assert res["total_confirmados"] > 0
    assert "BAIRRO FICTICIO" in res["bairros_nao_cadastrados"]
    assert any("outros municípios" in a for a in res["avisos"])  # filtro IBGE 280030
    forte = next(b for b in r["bairros"] if b["bairro"] == "Dezoito do Forte")  # apelido "18 DO FORTE"
    assert forte["total_casos_ano"] > 0
    assert any(a["tipo"] == "incidencia_alta" and a["bairro"] == "Santa Maria" for a in r["alertas"])
    for nome in ("vigiavetor.xlsx", "vigiavetor.json", "alertas.csv", "bairros.csv", "mapa_casos.geojson",
                 "casos_processados.csv"):
        assert (tmp_path / nome).exists()
    mapa = json.loads((tmp_path / "mapa_casos.geojson").read_text(encoding="utf-8"))
    assert mapa["features"] and mapa["features"][0]["geometry"]["type"] == "Point"
    # todas as colunas originais continuam no CSV processado
    cab = (tmp_path / "casos_processados.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "NM_PACIENT" in cab and "vv_confirmado" in cab
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / "vigiavetor.xlsx")
    assert wb.sheetnames == ["Resumo", "Alertas", "Bairros", "Microareas", "Semanas", "Mapa_Casos",
                             "Casos_Confirmados"]
    assert wb["Alertas"].max_row == len(r["alertas"]) + 1
    assert wb["Casos_Confirmados"]["A2"].value == wb["Casos_Confirmados"]["A2"].value.zfill(7)  # zeros mantidos


def test_bairros_reais_de_aracaju():
    from arbo.leitura import ler_bairros
    cad = ler_bairros(os.path.join(PASTA, "bairros.csv"))
    assert cad["18 DO FORTE"]["bairro"] == "Dezoito do Forte"
    assert cad["AUGUSTO FRANCO"]["bairro"] == "Farolândia"
    assert cad["MOSQUEIRO"]["bairro"] == "Mosqueiro"
    assert cad["AERPORTO"]["bairro"] == "Aeroporto"


def _planilha_secretaria():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "CONFIRMADOS DENGUE"
    ws.append(["ENDEREÇOS DOS CASOS CONFIRMADOS - AGOSTO A 23 DE OUTUBRO 2026"])
    for _ in range(3):
        ws.append(["COROA DO MEIO", "RUA JOSIAS VIEIRA DANTAS", "328", None])
    ws.append(["COROA DO MEIO", "R JOSIAS VIEIRA DANTAS,", "10", None])
    ws.append(["COROA DO MEIO", "RUA JOSIAS VIEIRA DANTAS", "S/N", None])
    ws.append(["18 DO FORTE", "AV. JOAO RIBEIRO", "5", "CASA"])
    ws.append(["CAPUCHO", None, None, None])
    ws2 = wb.create_sheet("CONFIRMADOS CHIKUNGUNYA ")
    ws2.append(["ENDEREÇOS DOS CASOS CONFIRMADOS CHIKUNGUNYA - AGOSTO A 23 DE OUTUBRO 2026"])
    ws2.append(["COROA DO MEIO", "AVENIDA JOSIAS VIEIRA DANTAS", "99", None])
    ws2.append(["COROA DO MEIO", "RUA JOSIAS VIEIRA DANTAS", "50", None])
    wb.create_sheet("Plan3")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_planilha_da_secretaria(tmp_path):
    cfg = carregar_config()
    cfg["alertas_enderecos"] = {"rua_casos": {"alerta": 5, "critico": 10}, "cocirculacao_rua_minimo": 2}
    r = executar(_planilha_secretaria(), "enderecos.xlsx", str(tmp_path), config=cfg, geocodificar_enderecos=False)
    res = r["resumo"]
    assert res["tipo"] == "enderecos_secretaria"
    assert res["periodo"] == "AGOSTO A 23 DE OUTUBRO 2026"
    assert (res["total_casos"], res["total_dengue"], res["total_chikungunya"]) == (9, 7, 2)
    coroa = r["bairros"][0]
    assert coroa["bairro"] == "Coroa do Meio" and coroa["total"] == 7 and coroa["ranking"] == 1
    assert any(b["bairro"] == "Dezoito do Forte" for b in r["bairros"])
    rua = r["ruas"][0]  # "R JOSIAS..." e "RUA JOSIAS..." viram a mesma rua; "AVENIDA" é outra
    assert rua["total"] == 6 and rua["chikungunya"] == 1
    assert r["enderecos_repetidos"][0]["total"] == 3  # S/N não conta como mesmo endereço
    tipos = {a["tipo"] for a in r["alertas"]}
    assert {"rua_com_muitos_casos", "endereco_repetido", "cocirculacao"} <= tipos
    assert any("sem rua" in a for a in res["avisos"])
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / "vigiavetor.xlsx")
    assert wb.sheetnames == ["Resumo", "Alertas", "Bairros", "Ruas", "Enderecos_Repetidos", "Mapa_Casos", "Casos"]
    assert wb["Casos"].max_row == 10

class GeoFalso:
    """Substitui o Nominatim: devolve coordenadas fixas por logradouro."""

    def __init__(self, pontos):
        self.pontos, self.cache, self.config = pontos, {}, {}
        self.consultas = self.erros = 0

    def localizar(self, endereco, bairro, referencia=None):
        self.consultas += 1
        return self.pontos.get(endereco.split(",")[0])

    def localizar_bairro(self, bairro):
        self.consultas += 1
        return (-10.9, -37.05)

    def salvar_cache(self):
        pass


def _csv(linhas):
    cab = "NU_NOTIFIC;ID_AGRAVO;DT_SIN_PRI;NM_BAIRRO;NM_LOGRADO;NU_NUMERO;CLASSI_FIN;EVOLUCAO\n"
    return (cab + "\n".join(";".join(l) for l in linhas)).encode()


def test_aglomerado_e_obito(tmp_path):
    linhas = [
        ("1", "A90", "10/11/2026", "CENTRO", "RUA A", "10", "10", "1"),
        ("2", "A90", "12/11/2026", "CENTRO", "RUA B", "20", "11", "1"),
        ("3", "A92.0", "14/11/2026", "CENTRO", "RUA C", "30", "13", "1"),
        ("4", "A90", "15/11/2026", "CENTRO", "RUA LONGE", "1", "12", "2"),
        ("5", "A90", "15/11/2026", "CENTRO", "RUA A", "11", "5", "1"),  # descartado
        ("1", "A90", "10/11/2026", "CENTRO", "RUA A", "10", "10", "1"),  # duplicada
    ]
    geo = GeoFalso({"RUA A": (-10.0, -48.0), "RUA B": (-10.0005, -48.0005),
                    "RUA C": (-10.001, -48.0), "RUA LONGE": (-10.05, -48.05)})
    r = executar(_csv(linhas), "t.csv", str(tmp_path), config=carregar_config(),
                 geocodificar_enderecos=True, geocodificador=geo)
    centro = next(b for b in r["bairros"] if b["bairro"] == "Centro")
    assert (centro["latitude"], centro["longitude"]) == (-10.9, -37.05)  # buscado no mapa
    res = r["resumo"]
    assert res["duplicadas_removidas"] == 1
    assert res["total_confirmados"] == 4
    assert res["localizacao"]["endereco"] == 4
    tipos = {a["tipo"]: a for a in r["alertas"]}
    assert tipos["aglomerado"]["valor"] == 3
    assert "chikungunya" in tipos["aglomerado"]["agravo"]
    assert tipos["obito"]["nivel"] == "critico"
    assert r["alertas"][0]["nivel"] == "critico"


def test_sem_agravo_exige_parametro(tmp_path):
    conteudo = b"NM_BAIRRO;CLASSI_FIN;DT_SIN_PRI\nCENTRO;1;01/11/2026\n"
    with pytest.raises(ValueError):
        executar(conteudo, "z.csv", str(tmp_path), config=carregar_config(), geocodificar_enderecos=False)
    r = executar(conteudo, "z.csv", str(tmp_path), config=carregar_config(),
                 agravo_padrao="zika", geocodificar_enderecos=False)
    assert r["resumo"]["agravos"]["zika"]["confirmados_ano"] == 1


def test_sem_dados_pessoais(tmp_path):
    cfg = carregar_config()
    cfg["incluir_dados_pessoais_nas_saidas"] = False
    with open(EXEMPLO, "rb") as f:
        r = executar(f.read(), EXEMPLO, str(tmp_path), config=cfg, bairros_conteudo=BAIRROS_EXEMPLO,
                     geocodificar_enderecos=False)
    assert "nome" not in r["mapa_casos"]["features"][0]["properties"]
    cab = (tmp_path / "casos_processados.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "NM_PACIENT" not in cab and "NM_LOGRADO" not in cab


def test_web(monkeypatch):
    monkeypatch.setenv("ANALISADOR_SENHA", "teste123")
    import web

    web.app.config["TESTING"] = True
    cli = web.app.test_client()
    assert cli.get("/").status_code == 302
    assert cli.post("/login", data={"senha": "errada"}).status_code == 200
    cli.post("/login", data={"senha": "teste123"})
    with open(EXEMPLO, "rb") as f:
        resp = cli.post("/", data={"arquivo": (io.BytesIO(f.read()), "sinan.csv"),
                                   "bairros": (io.BytesIO(BAIRROS_EXEMPLO), "bairros.csv")},
                        content_type="multipart/form-data")
    assert resp.status_code == 302
    pagina = cli.get(resp.headers["Location"])
    assert pagina.status_code == 200 and "Santa Maria" in pagina.get_data(as_text=True)
    assert cli.get(resp.headers["Location"] + "/vigiavetor.xlsx").status_code == 200
    zip_resp = cli.get(resp.headers["Location"] + ".zip")
    assert zip_resp.status_code == 200 and zip_resp.data[:2] == b"PK"
    # outro usuário (sem a sessão) não acessa o resultado
    outro = web.app.test_client()
    outro.post("/login", data={"senha": "teste123"})
    assert outro.get(resp.headers["Location"]).status_code == 403


def test_web_planilha_secretaria(monkeypatch):
    monkeypatch.setenv("ANALISADOR_SENHA", "teste123")
    import web

    cli = web.app.test_client()
    cli.post("/login", data={"senha": "teste123"})
    resp = cli.post("/", data={"arquivo": (io.BytesIO(_planilha_secretaria()), "enderecos.xlsx")},
                    content_type="multipart/form-data")
    pagina = cli.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Ruas com mais casos" in pagina and "JOSIAS" in pagina
    assert cli.get(resp.headers["Location"] + "/ruas.csv").status_code == 200
    assert cli.get(resp.headers["Location"] + "/microareas.csv").status_code == 404


def test_conjunto_zona_de_expansao(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "CONFIRMADOS DENGUE"
    ws.append(["ENDEREÇOS DOS CASOS CONFIRMADOS - AGOSTO A 23 DE OUTUBRO 2026"])
    for i in range(60):
        ws.append(["MOSQUEIRO" if i % 2 else "ROBALO", f"RUA {i}", str(i), None])
    buf = io.BytesIO()
    wb.save(buf)
    r = executar(buf.getvalue(), "e.xlsx", str(tmp_path), config=carregar_config(), geocodificar_enderecos=False)
    mosq = next(b for b in r["bairros"] if b["bairro"] == "Mosqueiro")
    assert mosq["grupo_populacao"] == "Zona de Expansão"
    assert mosq["incidencia_grupo_100mil"] == round(60 * 100000 / 32219, 1)
    al = [a for a in r["alertas"] if a["tipo"].startswith("bairro")]
    assert len(al) == 1 and al[0]["bairro"] == "Zona de Expansão" and "Mosqueiro 30" in al[0]["mensagem"]


MODELO = ["Unidade Solicitante", "Data da solicitação", "Data do 1º sintoma", "CNS do Paciente", "Paciente",
          "Data de nascimento", "Idade", "Sexo", "Nome da mãe", "Endereço", "Número", "Bairro",
          "CEP de residência", "Telefone de contato", "Exame", "Data da coleta", "Resultado", "Latitude", "Longitude"]


def test_modelo_importacao_sinan(tmp_path):
    from openpyxl import load_workbook
    cab = "NU_NOTIFIC;ID_AGRAVO;DT_NOTIFIC;DT_SIN_PRI;NM_PACIENT;DT_NASC;NU_IDADE_N;CS_SEXO;NM_MAE_PAC;ID_CNS_SUS;" \
          "NM_BAIRRO;NM_LOGRADO;NU_NUMERO;NU_CEP;ID_DDD;NU_TELEFON;DT_NS1;CLASSI_FIN;ID_MN_RESI;LATITUDE;LONGITUDE\n"
    linhas = ["1;A90;01/09/2026;25/08/2026;MARIA FICTICIA;14/05/1990;4036;F;JOANA FICTICIA;700000000000000;"
              "CENTRO;RUA DAS FLORES;123;49000000;79;999999999;01/09/2026;10;280030;-10.91;-37.05",
              "2;A90;01/09/2026;25/08/2026;DESCARTADO;14/05/1990;4036;M;;;CENTRO;RUA X;1;;;;;5;280030;;"]
    r = executar((cab + "\n".join(linhas)).encode(), "s.csv", str(tmp_path), config=carregar_config(),
                 geocodificar_enderecos=False)
    ws = load_workbook(tmp_path / "vigiavetor_importacao.xlsx")["Notificações"]
    assert [c.value for c in ws[1]] == MODELO
    assert ws.max_row == 2  # só o confirmado
    v = dict(zip(MODELO, [c.value for c in ws[2]]))
    assert v["Data da solicitação"] == "2026-09-01" and v["Data do 1º sintoma"] == "2026-08-25"
    assert v["Paciente"] == "MARIA FICTICIA" and v["Idade"] == "36" and v["Sexo"] == "Feminino"
    assert v["CEP de residência"] == "49000-000" and v["Telefone de contato"] == "(79) 999999999"
    assert v["Exame"] == "Dengue" and v["Resultado"] == "Positivo" and v["Data da coleta"] == "2026-09-01"
    assert v["Latitude"] == -10.91 and v["Longitude"] == -37.05


def test_modelo_importacao_secretaria(tmp_path):
    from openpyxl import load_workbook
    executar(_planilha_secretaria(), "enderecos.xlsx", str(tmp_path), config=carregar_config(),
             geocodificar_enderecos=False)
    ws = load_workbook(tmp_path / "vigiavetor_importacao.xlsx")["Notificações"]
    assert [c.value for c in ws[1]] == MODELO
    assert ws.max_row == 10
    v = dict(zip(MODELO, [c.value for c in ws[2]]))
    assert (v["Endereço"], v["Número"], v["Bairro"], v["Exame"], v["Resultado"]) == \
        ("RUA JOSIAS VIEIRA DANTAS", "328", "Coroa do Meio", "Dengue", "Positivo")
    assert v["Latitude"] is None  # sem localização: fica em branco


def test_rua_sem_bairro_respeita_distancia():
    from arbo.geocodificacao import Geocodificador

    class Sessao:
        headers = {}

        def __init__(self, pontos):
            self.pontos = pontos

        def get(self, url, params, timeout):
            ponto = self.pontos

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return [{"lat": str(ponto[0]), "lon": str(ponto[1]), "addresstype": "road"}]
            return R()

    cfg = carregar_config()
    cfg["geocodificacao_intervalo_segundos"] = 0
    perto = Geocodificador(cfg, sessao=Sessao((-10.905, -37.05))).localizar_rua_sem_bairro(
        "RUA X", "Centro", (-10.91, -37.05))
    assert perto == (-10.905, -37.05, "rua")
    longe = Geocodificador(cfg, sessao=Sessao((-10.99, -37.05))).localizar_rua_sem_bairro(
        "RUA X", "Centro", (-10.91, -37.05))
    assert longe is None


def test_interpretar_coordenada():
    from arbo.coordenadas_coletadas import interpretar
    assert interpretar("-10.9123, -37.0567") == (-10.9123, -37.0567)
    assert interpretar("-10.9123,-37.0567") == (-10.9123, -37.0567)
    assert interpretar("-10,9123; -37,0567") == (-10.9123, -37.0567)
    assert interpretar("-10,9123, -37,0567") == (-10.9123, -37.0567)
    assert interpretar("", "-10,91", "-37,05") == (-10.91, -37.05)
    assert interpretar("") is None


def test_ciclo_coordenadas_coletadas(tmp_path):
    from openpyxl import load_workbook
    cfg = carregar_config()
    cfg["pasta_coordenadas_coletadas"] = str(tmp_path / "nao_existe")
    s1 = tmp_path / "s1"
    r = executar(_planilha_secretaria(), "e.xlsx", str(s1), config=cfg, geocodificar_enderecos=False)
    lista = s1 / "coordenadas_a_coletar.xlsx"
    wb = load_workbook(lista)
    ws = wb["A coletar"]
    cab = [c.value for c in ws[1]]
    linhas = {(ws.cell(i, 2).value, ws.cell(i, 3).value): i for i in range(2, ws.max_row + 1)}
    pendentes_antes = r["resumo"]["enderecos_a_coletar"]
    assert pendentes_antes == ws.max_row - 1 and "Coordenada" in cab
    # preenche: 1 pelo formato do Google Maps, 1 fora do município (erro), 1 só a rua (apaga o número)
    ws.cell(linhas[("RUA JOSIAS VIEIRA DANTAS", "328")], 7, "-10.9640, -37.0430")
    ws.cell(linhas[("AV. JOAO RIBEIRO", "5")], 7, "10.89, 37.05")
    i = linhas[("RUA JOSIAS VIEIRA DANTAS", "50")]
    ws.cell(i, 3).value = None  # apaga o número
    ws.cell(i, 8, -10.9650)
    ws.cell(i, 9, -37.0440)
    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)

    s2 = tmp_path / "s2"
    r2 = executar(_planilha_secretaria(), "e.xlsx", str(s2), config=cfg, geocodificar_enderecos=False,
                  coordenadas_conteudos=[(buf.getvalue(), "coletadas.xlsx")])
    res = r2["resumo"]
    # 328 tem 3 casos; "só a rua" vale para os outros casos dessa rua (10, S/N, 50) -> 3 casos
    assert res["localizacao"]["coletada"] == 6
    assert res["coordenadas_coletadas_usadas"] == 6
    assert any("fora do município" in a for a in res["avisos"])
    assert res["enderecos_a_coletar"] < pendentes_antes
    imp = load_workbook(s2 / "vigiavetor_importacao.xlsx").worksheets[0]
    assert imp.cell(2, 18).value == -10.964 and imp.cell(2, 19).value == -37.043
