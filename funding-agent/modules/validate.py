"""
Validación de oportunidades y aplicación de las reglas de calidad.

- Rellena con "No especificado" los campos vacíos (regla de no-invención).
- Exige una URL (oficial o secundaria); sin ninguna URL -> se descarta como "Fuente no oficial".
- Descarta lo que no es financiación o no aplica a Colombia/LATAM (si el modelo no lo hizo).
- Marca 'requiere_verificacion' cuando faltan datos críticos (fecha y/o fuente conocida).
- Anota en observaciones si el dominio no pertenece a una fuente oficial conocida.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from .settings import NO_ESPECIFICADO

# Campos de texto que deben existir (se rellenan con "No especificado" si faltan)
_TEXT_FIELDS = [
    "nombre", "entidad_financiadora", "tipo_entidad", "pais_entidad", "paises_elegibles",
    "sector_principal", "subtema", "tipo_apoyo", "monto_disponible", "moneda",
    "cofinanciacion_requerida", "fecha_apertura", "fecha_cierre", "url_oficial",
    "url_secundaria", "resumen_ejecutivo", "pertinencia_vision_circular", "lineas_proyecto",
    "requisitos_principales", "documentos_requeridos", "aliados_potenciales", "riesgos",
    "recomendacion_accion", "proximo_paso", "responsable_sugerido", "observaciones",
    "motivo_verificacion",
]


def _is_url(value: str) -> bool:
    try:
        p = urlparse(value.strip())
        return p.scheme in ("http", "https") and bool(p.netloc) and "." in p.netloc
    except Exception:
        return False


def _domain(value: str) -> str:
    try:
        net = urlparse(value.strip()).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _known_domains(config: dict) -> set[str]:
    domains: set[str] = set()
    for src in config.get("sources", {}).get("fuentes", []):
        for d in src.get("dominios", []):
            domains.add(d.lower())
    return domains


def _fill_no_especificado(opp: dict) -> None:
    for field in _TEXT_FIELDS:
        val = opp.get(field)
        if val is None or str(val).strip() == "":
            opp[field] = NO_ESPECIFICADO


def _append_obs(opp: dict, note: str) -> None:
    cur = opp.get("observaciones", "")
    if cur in ("", NO_ESPECIFICADO):
        opp["observaciones"] = note
    else:
        opp["observaciones"] = f"{cur} | {note}"


def validate_opportunities(data: dict, config: dict, logger: logging.Logger) -> dict:
    raw = data.get("oportunidades", [])
    descartadas = list(data.get("descartadas", []))
    known = _known_domains(config)

    validas: list[dict] = []
    for opp in raw:
        nombre = (opp.get("nombre") or "").strip() or NO_ESPECIFICADO

        # Regla: debe ser financiación/cooperación
        if opp.get("es_financiacion") is False:
            descartadas.append({"nombre": nombre, "url": opp.get("url_oficial", ""), "motivo": "Sin financiación"})
            continue

        # Regla: Colombia/LATAM debe poder aplicar
        if opp.get("colombia_o_latam_elegible") is False:
            descartadas.append({"nombre": nombre, "url": opp.get("url_oficial", ""), "motivo": "No aplica para Colombia"})
            continue

        url_oficial = (opp.get("url_oficial") or "").strip()
        url_secundaria = (opp.get("url_secundaria") or "").strip()

        # Regla: debe existir alguna URL válida
        if not _is_url(url_oficial) and not _is_url(url_secundaria):
            descartadas.append({"nombre": nombre, "url": url_oficial or url_secundaria, "motivo": "Fuente no oficial"})
            continue

        # Rellenar faltantes con "No especificado"
        _fill_no_especificado(opp)

        # ¿Dominio reconocido como fuente oficial?
        dom = _domain(url_oficial) or _domain(url_secundaria)
        if dom and not any(dom == k or dom.endswith("." + k) for k in known):
            _append_obs(opp, f"Fuente fuera del listado oficial conocido ({dom}): verificar oficialidad")
            if not opp.get("requiere_verificacion"):
                opp["requiere_verificacion"] = True
                if opp.get("motivo_verificacion", NO_ESPECIFICADO) in ("", NO_ESPECIFICADO):
                    opp["motivo_verificacion"] = "Dominio no reconocido como fuente oficial conocida"

        # Sin fecha de cierre clara -> requiere verificación
        if str(opp.get("fecha_cierre")).strip() in ("", NO_ESPECIFICADO):
            opp["requiere_verificacion"] = True
            if opp.get("motivo_verificacion", NO_ESPECIFICADO) in ("", NO_ESPECIFICADO):
                opp["motivo_verificacion"] = "Sin fecha de cierre o ventana clara"

        validas.append(opp)

    logger.info("Validación: %d válidas, %d descartadas.", len(validas), len(descartadas))
    return {
        "oportunidades": validas,
        "descartadas": descartadas,
        "resumen_ejecutivo": data.get("resumen_ejecutivo", ""),
    }
