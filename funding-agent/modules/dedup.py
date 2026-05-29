"""
Deduplicación de oportunidades.

Genera una clave estable (clave_hash) a partir de nombre + entidad + dominio de la URL,
normalizando texto (minúsculas, sin tildes, sin espacios extra). Permite:
  - evitar duplicados dentro del lote del día,
  - distinguir oportunidades NUEVAS de las YA REGISTRADAS en la base (para actualizar su estado
    sin duplicar ni borrar histórico).
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from urllib.parse import urlparse


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def _domain(url: str) -> str:
    try:
        net = urlparse((url or "").strip()).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def make_key(opp: dict) -> str:
    base = "|".join([
        _normalize(opp.get("nombre", "")),
        _normalize(opp.get("entidad_financiadora", "")),
        _domain(opp.get("url_oficial", "")) or _domain(opp.get("url_secundaria", "")),
    ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def assign_keys(opportunities: list[dict]) -> None:
    for opp in opportunities:
        opp["clave_hash"] = make_key(opp)


def split_new_existing(opportunities: list[dict], existing_keys: set[str],
                       logger: logging.Logger) -> tuple[list[dict], list[dict]]:
    """Devuelve (nuevas, ya_registradas). Deduplica también dentro del propio lote."""
    assign_keys(opportunities)

    nuevas: list[dict] = []
    ya_registradas: list[dict] = []
    vistas_en_lote: set[str] = set()

    for opp in opportunities:
        key = opp["clave_hash"]
        if key in vistas_en_lote:
            continue  # duplicado dentro del mismo día
        vistas_en_lote.add(key)
        if key in existing_keys:
            ya_registradas.append(opp)
        else:
            nuevas.append(opp)

    logger.info("Deduplicación: %d nuevas, %d ya registradas (se actualizará su revisión).",
                len(nuevas), len(ya_registradas))
    return nuevas, ya_registradas
