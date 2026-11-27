"""Analisador de casos confirmados de arboviroses (dengue, chikungunya e zika).

Lê exportações do SINAN, identifica os casos confirmados, geocodifica os
endereços e gera arquivos (JSON/CSV/GeoJSON) para alimentar o Vigiavetor.
"""

from .pipeline import executar  # noqa: F401

__version__ = "1.0.0"
