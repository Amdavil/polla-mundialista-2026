"""
Carga de configuración, variables de entorno, logging y constantes del proyecto
(las 35 columnas de la base de datos y los catálogos controlados).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

# Raíz del proyecto = carpeta funding-agent/ (padre de modules/)
BASE_DIR = Path(__file__).resolve().parent.parent


# ── Variables de entorno ─────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Carga .env si existe. Usa python-dotenv si está disponible; si no, parser propio."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import dotenv_values  # type: ignore
        # El .env tiene prioridad sobre variables de entorno VACÍAS (p. ej. algunos
        # entornos definen ANTHROPIC_API_KEY="" y, con override=False, bloquearían la
        # del .env), pero respeta una variable ya definida con un valor real.
        for key, value in dotenv_values(env_path).items():
            if value is not None and not os.environ.get(key):
                os.environ[key] = value
        return
    except Exception:
        pass
    # Fallback manual: KEY=VALUE por línea
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not os.environ.get(key):
            os.environ[key] = value.strip().strip('"').strip("'")


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    _load_dotenv()
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Falta la variable de entorno requerida: {name}. "
            f"Configúrala en funding-agent/.env (ver .env.example) o como secreto de GitHub Actions."
        )
    return value


# ── Configuración (config.json + keywords + sources) ─────────────────────────

def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    """Lee config.json y anexa keywords/sources. Resuelve rutas a absolutas bajo BASE_DIR."""
    config = _read_json(BASE_DIR / "config.json")

    keywords_path = BASE_DIR / "config" / "keywords.json"
    sources_path = BASE_DIR / "config" / "sources.json"
    config["keywords"] = _read_json(keywords_path) if keywords_path.exists() else {}
    config["sources"] = _read_json(sources_path) if sources_path.exists() else {"fuentes": []}

    # Resolver rutas a absolutas
    rutas = config.get("rutas", {})
    for key, rel in rutas.items():
        rutas[key] = str((BASE_DIR / rel).resolve())
    config["rutas"] = rutas

    # Asegurar que existan las carpetas base
    for key in ("data", "output", "logs"):
        if key in rutas:
            Path(rutas[key]).mkdir(parents=True, exist_ok=True)

    return config


def all_queries(config: dict) -> list[str]:
    """Combina todas las listas de queries definidas en keywords.json, sin duplicados."""
    kw = config.get("keywords", {})
    queries: list[str] = []
    for key in ("queries_es", "queries_en", "queries_por_fuente"):
        queries.extend(kw.get(key, []))
    # Dedup preservando orden
    seen: set[str] = set()
    unique = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(logs_dir: str | Path) -> logging.Logger:
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"agente_{date.today().isoformat()}.log"

    logger = logging.getLogger("vision_circular")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Log de ejecución: %s", log_file)
    return logger


# ── Las 35 columnas de la base de datos ──────────────────────────────────────
# (clave interna, encabezado humano en español). El ORDEN define el orden en Excel/CSV.

COLUMNS: list[tuple[str, str]] = [
    ("id",                       "ID"),
    ("fecha_deteccion",          "Fecha de detección"),
    ("nombre",                   "Nombre de la oportunidad"),
    ("entidad_financiadora",     "Entidad financiadora"),
    ("tipo_entidad",             "Tipo de entidad"),
    ("pais_entidad",             "País / región de la entidad"),
    ("paises_elegibles",         "Países elegibles"),
    ("sector_principal",         "Sector o tema principal"),
    ("subtema",                  "Subtema"),
    ("tipo_apoyo",               "Tipo de apoyo"),
    ("monto_disponible",         "Monto disponible"),
    ("moneda",                   "Moneda"),
    ("cofinanciacion_requerida", "Cofinanciación requerida"),
    ("fecha_apertura",           "Fecha de apertura"),
    ("fecha_cierre",             "Fecha de cierre"),
    ("estado",                   "Estado"),
    ("nivel_urgencia",           "Nivel de urgencia"),
    ("url_oficial",              "URL oficial"),
    ("url_secundaria",           "URL secundaria"),
    ("resumen_ejecutivo",        "Resumen ejecutivo"),
    ("pertinencia_vision_circular", "Pertinencia para Visión Circular ANDI"),
    ("lineas_proyecto",          "Posibles líneas de proyecto aplicables"),
    ("requisitos_principales",   "Requisitos principales"),
    ("documentos_requeridos",    "Documentos requeridos"),
    ("aliados_potenciales",      "Aliados potenciales"),
    ("riesgos",                  "Riesgos o restricciones"),
    ("recomendacion_accion",     "Recomendación de acción"),
    ("proximo_paso",             "Próximo paso sugerido"),
    ("responsable_sugerido",     "Responsable sugerido"),
    ("score_pertinencia",        "Score de pertinencia (1-5)"),
    ("score_urgencia",           "Score de urgencia (1-5)"),
    ("score_probabilidad",       "Score de probabilidad de aplicación (1-5)"),
    ("observaciones",            "Observaciones"),
    ("clave_hash",               "Hash o clave para evitar duplicados"),
    ("fecha_ultima_revision",    "Fecha de última revisión"),
]

COLUMN_KEYS: list[str] = [key for key, _ in COLUMNS]
COLUMN_HEADERS: list[str] = [header for _, header in COLUMNS]
KEY_TO_HEADER: dict[str, str] = dict(COLUMNS)
HEADER_TO_KEY: dict[str, str] = {header: key for key, header in COLUMNS}

NO_ESPECIFICADO = "No especificado"

# ── Catálogos controlados ─────────────────────────────────────────────────────

TIPOS_APOYO = [
    "Grant no reembolsable", "Cooperación técnica", "Asistencia técnica",
    "Premio o challenge", "Financiamiento concesional", "Cofinanciación",
    "Donación", "Aceleración", "Investigación aplicada", "Innovación",
    "Piloto demostrativo", "Escalamiento", "Fortalecimiento institucional",
    "Inclusión social", "Financiamiento climático", "Otro",
]

NIVELES_URGENCIA = ["Alta", "Media", "Baja", "Requiere verificación"]

ESTADOS = [
    "Activa", "Próxima a abrir", "Cerrada",
    "Requiere verificación manual", "Sin fecha definida",
]
