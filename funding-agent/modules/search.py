"""
Módulo de búsqueda web con proveedor intercambiable.

Proveedores soportados (se elige en config.json -> busqueda.proveedor):
  - tavily      (recomendado; usa el paquete tavily-python)
  - exa         (API de Exa, búsqueda neural)
  - brave       (Brave Search API)
  - google_cse  (Google Custom Search JSON API; requiere también GOOGLE_CSE_ID)
  - serpapi     (SerpAPI)
  - simulado    (lee tests/sample_search_results.json; NO sirve para producción)

Todos los proveedores devuelven una lista de dicts normalizados:
  { "title": str, "url": str, "content": str, "query": str }

La clave de API se lee de la variable de entorno SEARCH_API_KEY (excepto 'simulado').
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .settings import get_env


class SearchProvider:
    name = "base"

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        raise NotImplementedError


# ── Tavily ────────────────────────────────────────────────────────────────────

class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str):
        try:
            from tavily import TavilyClient  # type: ignore
        except ImportError as e:
            raise RuntimeError("Falta el paquete 'tavily-python'. Instala requirements.txt.") from e
        self.client = TavilyClient(api_key=api_key)

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        resp = self.client.search(
            query=query, search_depth=depth, max_results=max_results, include_answer=False
        )
        out = []
        for r in resp.get("results", []):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "query": query,
            })
        return out


# ── Exa ─────────────────────────────────────────────────────────────────────

class ExaProvider(SearchProvider):
    name = "exa"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        import requests
        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json={"query": query, "numResults": max_results, "contents": {"text": True}},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for r in resp.json().get("results", []):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("text") or "")[:2000],
                "query": query,
            })
        return out


# ── Brave ─────────────────────────────────────────────────────────────────────

class BraveProvider(SearchProvider):
    name = "brave"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        import requests
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            params={"q": query, "count": max_results},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for r in resp.json().get("web", {}).get("results", []):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("description", ""),
                "query": query,
            })
        return out


# ── Google Custom Search ──────────────────────────────────────────────────────

class GoogleCSEProvider(SearchProvider):
    name = "google_cse"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cx = get_env("GOOGLE_CSE_ID")
        if not self.cx:
            raise RuntimeError("Google CSE requiere la variable GOOGLE_CSE_ID (ID del motor de búsqueda).")

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        import requests
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": self.api_key, "cx": self.cx, "q": query, "num": min(max_results, 10)},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for r in resp.json().get("items", []):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "content": r.get("snippet", ""),
                "query": query,
            })
        return out


# ── SerpAPI ───────────────────────────────────────────────────────────────────

class SerpApiProvider(SearchProvider):
    name = "serpapi"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        import requests
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={"q": query, "api_key": self.api_key, "num": max_results, "engine": "google"},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for r in resp.json().get("organic_results", []):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "content": r.get("snippet", ""),
                "query": query,
            })
        return out


# ── Simulado (offline) ──────────────────────────────────────────────────────

class SimulatedProvider(SearchProvider):
    name = "simulado"

    def __init__(self, sample_path: str):
        self.sample_path = Path(sample_path)
        self._served = False

    def search(self, query: str, max_results: int, depth: str) -> list[dict]:
        # Devuelve todo el set de prueba en la primera query y nada después
        # (el deduplicador colapsaría duplicados igualmente).
        if self._served or not self.sample_path.exists():
            return []
        self._served = True
        data = json.loads(self.sample_path.read_text(encoding="utf-8"))
        results = data.get("resultados", data) if isinstance(data, dict) else data
        for r in results:
            r.setdefault("query", "[simulado]")
        return results


# ── Factory + runner ──────────────────────────────────────────────────────────

_PROVIDERS = {
    "tavily": TavilyProvider,
    "exa": ExaProvider,
    "brave": BraveProvider,
    "google_cse": GoogleCSEProvider,
    "serpapi": SerpApiProvider,
}


def get_provider(config: dict, logger: logging.Logger) -> SearchProvider:
    name = config.get("busqueda", {}).get("proveedor", "tavily").lower()

    if name == "simulado":
        logger.warning("Proveedor de búsqueda = SIMULADO. Datos de prueba, NO usar en producción.")
        return SimulatedProvider(config["rutas"]["datos_simulados"])

    if name not in _PROVIDERS:
        raise RuntimeError(f"Proveedor de búsqueda desconocido: '{name}'. Opciones: {list(_PROVIDERS) + ['simulado']}")

    api_key = get_env("SEARCH_API_KEY")
    if not api_key:
        logger.warning(
            "No hay SEARCH_API_KEY configurada para '%s'. Cambiando a modo SIMULADO.", name
        )
        return SimulatedProvider(config["rutas"]["datos_simulados"])

    return _PROVIDERS[name](api_key)


def run_searches(config: dict, queries: list[str], logger: logging.Logger) -> list[dict]:
    provider = get_provider(config, logger)
    busq = config.get("busqueda", {})
    max_results = int(busq.get("max_resultados_por_query", 5))
    depth = busq.get("profundidad", "advanced")

    logger.info("Búsqueda con proveedor '%s' — %d queries", provider.name, len(queries))

    all_results: list[dict] = []
    for q in queries:
        try:
            res = provider.search(q, max_results, depth)
            all_results.extend(res)
            logger.info("  ✓ %-55s → %d resultados", (q[:52] + "...") if len(q) > 55 else q, len(res))
        except Exception as e:  # noqa: BLE001 — queremos continuar pese a fallos puntuales
            logger.error("  ✗ Error en query '%s': %s", q[:55], e)

    # Deduplicar por URL
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        url = (r.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    logger.info("Resultados únicos por URL: %d (de %d brutos)", len(unique), len(all_results))
    return unique
