"""Planilha no modelo de importação do Vigiavetor (aba "Notificações", 19 colunas).

Colunas e formato iguais ao arquivo ``modelo_importacao_arboviroses.xlsx``:
datas como texto AAAA-MM-DD, idade como texto, latitude/longitude numéricas.
"""

from openpyxl import Workbook
from openpyxl.styles import Font

COLUNAS = [
    "Unidade Solicitante", "Data da solicitação", "Data do 1º sintoma", "CNS do Paciente", "Paciente",
    "Data de nascimento", "Idade", "Sexo", "Nome da mãe", "Endereço", "Número", "Bairro",
    "CEP de residência", "Telefone de contato", "Exame", "Data da coleta", "Resultado", "Latitude", "Longitude",
]

EXAME_PADRAO = {"dengue": "Dengue", "chikungunya": "Chikungunya", "zika": "Zika"}


def _texto(v):
    if v is None:
        return None
    t = str(v).strip()
    if t.endswith(".0") and t[:-2].isdigit():
        t = t[:-2]
    return t or None


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def gravar(caminho, linhas):
    """``linhas``: lista de dicts com as chaves de ``COLUNAS``."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Notificações"
    ws.append(COLUNAS)
    for linha in linhas:
        valores = []
        for col in COLUNAS:
            v = linha.get(col)
            valores.append(_num(v) if col in ("Latitude", "Longitude") else _texto(v))
        ws.append(valores)
    for cel in ws[1]:
        cel.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for letra, largura in zip("ABCDEFGHIJKLMNOPQRS", (22, 14, 14, 18, 30, 14, 7, 11, 30, 40, 9, 22, 13, 17, 14, 14, 11, 12, 12)):
        ws.column_dimensions[letra].width = largura
    wb.save(caminho)
    return len(linhas)


def coordenadas(caso, config):
    """Latitude/longitude para o modelo. Casos posicionados só no centro do bairro ficam em branco,
    a menos que ``modelo_vigiavetor_usar_centro_do_bairro`` seja true (evita pontos empilhados falsos)."""
    precisao = caso.get("vv_precisao_localizacao")
    if precisao in ("coletada", "endereco", "rua", "arquivo") or (
            precisao == "bairro" and config.get("modelo_vigiavetor_usar_centro_do_bairro", False)):
        return caso.get("vv_latitude"), caso.get("vv_longitude")
    return None, None


def exame(agravo, config):
    return config.get("modelo_vigiavetor_exame", {}).get(agravo, EXAME_PADRAO.get(agravo, agravo))
