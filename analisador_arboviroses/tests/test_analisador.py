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
                     geocodificar_enderecos=False)
    res = r["resumo"]
    assert res["semana_epidemiologica"] == 46
    assert res["total_confirmados"] > 0
    assert "PARQUE DAS AGUAS" in res["bairros_nao_cadastrados"]
    vila = next(b for b in r["bairros"] if b["bairro"] == "Vila Nova")  # casou pelo apelido "VL NOVA"
    assert vila["dengue"]["casos_ultimas_4_semanas"] > 0
    assert any(a["tipo"] == "incidencia_alta" and a["bairro"] == "Vila Nova" for a in r["alertas"])
    for nome in ("vigiavetor.json", "alertas.csv", "bairros.csv", "mapa_casos.geojson", "casos_processados.csv"):
        assert (tmp_path / nome).exists()
    mapa = json.loads((tmp_path / "mapa_casos.geojson").read_text(encoding="utf-8"))
    assert mapa["features"] and mapa["features"][0]["geometry"]["type"] == "Point"
    # todas as colunas originais continuam no CSV processado
    cab = (tmp_path / "casos_processados.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "NM_PACIENT" in cab and "vv_confirmado" in cab


class GeoFalso:
    """Substitui o Nominatim: devolve coordenadas fixas por logradouro."""

    def __init__(self, pontos):
        self.pontos, self.cache, self.config = pontos, {}, {}
        self.consultas = self.erros = 0

    def localizar(self, endereco, bairro, referencia=None):
        self.consultas += 1
        return self.pontos.get(endereco.split(",")[0])

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
        r = executar(f.read(), EXEMPLO, str(tmp_path), config=cfg, geocodificar_enderecos=False)
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
        resp = cli.post("/", data={"arquivo": (io.BytesIO(f.read()), "sinan.csv")},
                        content_type="multipart/form-data")
    assert resp.status_code == 302
    pagina = cli.get(resp.headers["Location"])
    assert pagina.status_code == 200 and "Vila Nova" in pagina.get_data(as_text=True)
    zip_resp = cli.get(resp.headers["Location"] + ".zip")
    assert zip_resp.status_code == 200 and zip_resp.data[:2] == b"PK"
    # outro usuário (sem a sessão) não acessa o resultado
    outro = web.app.test_client()
    outro.post("/login", data={"senha": "teste123"})
    assert outro.get(resp.headers["Location"]).status_code == 403
