"""Geocodificação de endereços (Nominatim/OpenStreetMap) com cache local.

Somente o endereço (logradouro, número, bairro, município e UF) é enviado ao
serviço; nome e demais dados do paciente nunca saem do computador/servidor.
O cache evita consultar o mesmo endereço duas vezes.
"""

import json
import os
import time

import requests

from .util import distancia_m, normalizar_texto


class Geocodificador:
    def __init__(self, config, caminho_cache=None, sessao=None):
        self.config = config
        self.url = config.get("geocodificacao_url", "https://nominatim.openstreetmap.org/search")
        self.intervalo = float(config.get("geocodificacao_intervalo_segundos", 1.1))
        self.raio_max_m = float(config.get("geocodificacao_raio_max_km", 5)) * 1000
        self.raio_municipio_m = float(config.get("raio_municipio_km", 25)) * 1000
        self.raio_rua_sem_bairro_m = float(config.get("geocodificacao_raio_rua_sem_bairro_km", 2)) * 1000
        self.caminho_cache = caminho_cache
        self.sessao = sessao or requests.Session()
        # O Nominatim recusa o User-Agent padrão do requests ("python-requests/x")
        self.sessao.headers["User-Agent"] = config.get("geocodificacao_user_agent", "analisador-arboviroses/1.0")
        self._ultima = 0.0
        self.consultas = 0
        self.erros = 0
        self.cache = {}
        if caminho_cache and os.path.exists(caminho_cache):
            try:
                with open(caminho_cache, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                self.cache = {}

    def salvar_cache(self):
        if not self.caminho_cache:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.caminho_cache)), exist_ok=True)
        with open(self.caminho_cache, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=0)

    def _consultar(self, consulta):
        espera = self.intervalo - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()
        self.consultas += 1
        params = {"q": consulta, "format": "jsonv2", "limit": 3, "countrycodes": "br"}
        resp = self.sessao.get(self.url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _referencia_municipio(self):
        lat = self.config.get("centro_municipio_latitude")
        lon = self.config.get("centro_municipio_longitude")
        return (float(lat), float(lon)) if lat is not None and lon is not None else None

    def _cidade(self):
        municipio = self.config.get("municipio", "")
        uf = self.config.get("uf", "")
        return f"{municipio} - {uf}" if uf else municipio

    def _buscar(self, consulta, referencia, raio_m, chave=None):
        chave = normalizar_texto(chave or consulta)
        if chave in self.cache:
            valor = self.cache[chave]
            if not valor:
                return None
            # Entradas antigas ([lat, lon]) não guardavam a precisão: trata como rua
            return (valor[0], valor[1], valor[2] if len(valor) > 2 else "rua")
        try:
            resultados = self._consultar(consulta)
        except (requests.RequestException, ValueError):
            self.erros += 1
            return None  # não grava no cache: tenta de novo na próxima execução

        ponto = None
        for r in resultados or []:
            try:
                lat, lon = float(r["lat"]), float(r["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if referencia and distancia_m(lat, lon, referencia[0], referencia[1]) > raio_m:
                continue
            exato = (r.get("type") == "house" or r.get("addresstype") in ("building", "house")
                     or r.get("category") == "building")
            ponto = (lat, lon, "endereco" if exato else "rua")
            break
        self.cache[chave] = list(ponto) if ponto else None
        if self.consultas % 50 == 0:
            self.salvar_cache()  # guarda o progresso em execuções longas
        return ponto

    def chave_endereco(self, endereco, bairro):
        partes = [endereco, bairro, self._cidade(), "Brasil"]
        return ", ".join(p for p in partes if p)

    def localizar(self, endereco, bairro, referencia=None):
        """Retorna (lat, lon, precisao) ou None. ``precisao`` é "endereco" quando o
        OpenStreetMap achou o imóvel e "rua" quando devolveu só o logradouro.

        ``referencia`` = (lat, lon) do centro do bairro; resultados longe demais
        dele são descartados (evita cair em rua homônima de outra cidade). Sem
        centro do bairro, o limite é o raio em volta do centro do município.
        """
        if not endereco:
            return None
        if referencia:
            raio = self.raio_max_m
        else:
            referencia, raio = self._referencia_municipio(), self.raio_municipio_m
        return self._buscar(self.chave_endereco(endereco, bairro), referencia, raio)

    def localizar_rua_sem_bairro(self, rua, bairro, referencia):
        """Busca só "rua, município" (o bairro anotado pode não ser o mesmo do mapa) e aceita
        o resultado apenas perto do centro do bairro informado."""
        if not rua or not referencia:
            return None
        consulta = ", ".join(p for p in [rua, self._cidade(), "Brasil"] if p)
        ponto = self._buscar(consulta, referencia, self.raio_rua_sem_bairro_m,
                             chave=f"SEM BAIRRO {bairro} | {consulta}")
        return (ponto[0], ponto[1], "rua") if ponto else None

    def localizar_bairro(self, bairro):
        """Centro aproximado do bairro, dentro do município."""
        if not bairro:
            return None
        consulta = ", ".join(p for p in [bairro, self._cidade(), "Brasil"] if p)
        return self._buscar(consulta, self._referencia_municipio(), self.raio_municipio_m)
