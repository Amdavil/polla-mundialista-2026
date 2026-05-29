"""
Persistencia de la base de oportunidades en Excel (.xlsx) y CSV.

Reglas:
  - Conserva el histórico: nunca borra oportunidades anteriores.
  - Las oportunidades NUEVAS se agregan con ID secuencial y fecha de detección.
  - Las YA REGISTRADAS se actualizan en sitio (estado, nivel de urgencia, scores, fecha de cierre
    y fecha de última revisión), sin duplicar ni perder su ID/fecha de detección original.
  - Usa los encabezados en español definidos en settings.COLUMNS.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .settings import COLUMN_HEADERS, COLUMN_KEYS, KEY_TO_HEADER, NO_ESPECIFICADO

HASH_HEADER = KEY_TO_HEADER["clave_hash"]
ID_HEADER = KEY_TO_HEADER["id"]

# Campos que se refrescan cuando una oportunidad ya existía
_REFRESH_KEYS = [
    "estado", "nivel_urgencia", "fecha_apertura", "fecha_cierre",
    "score_urgencia", "score_pertinencia", "score_probabilidad", "fecha_ultima_revision",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMN_HEADERS)


def load_existing(excel_path: Path, csv_path: Path) -> pd.DataFrame:
    path = excel_path if excel_path.exists() else (csv_path if csv_path.exists() else None)
    if path is None:
        return _empty_df()
    try:
        if path.suffix == ".xlsx":
            df = pd.read_excel(path, dtype=str)
        else:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except Exception:
        return _empty_df()
    df = df.reindex(columns=COLUMN_HEADERS)  # asegura todas las columnas, en orden
    return df.fillna("")


def existing_keys(df: pd.DataFrame) -> set[str]:
    if HASH_HEADER not in df.columns:
        return set()
    return {str(k) for k in df[HASH_HEADER].tolist() if str(k).strip()}


def _next_id_counter(df: pd.DataFrame) -> int:
    max_n = 0
    if ID_HEADER in df.columns:
        for val in df[ID_HEADER].tolist():
            m = re.search(r"(\d+)", str(val))
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _opp_to_row(opp: dict) -> dict:
    """Convierte una oportunidad (claves internas) a una fila con encabezados en español."""
    row = {}
    for key in COLUMN_KEYS:
        val = opp.get(key, "")
        row[KEY_TO_HEADER[key]] = NO_ESPECIFICADO if (val is None or str(val).strip() == "") else str(val)
    return row


def update_database(nuevas: list[dict], ya_registradas: list[dict], config: dict,
                    logger: logging.Logger, today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    excel_path = Path(config["rutas"]["excel"])
    csv_path = Path(config["rutas"]["csv"])
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    df = load_existing(excel_path, csv_path)
    counter = _next_id_counter(df)

    # Índice rápido clave_hash -> posición de fila
    pos_by_key = {}
    if HASH_HEADER in df.columns:
        for idx, k in zip(df.index, df[HASH_HEADER].tolist()):
            if str(k).strip():
                pos_by_key[str(k)] = idx

    # 1) Actualizar las ya registradas (sin duplicar ni perder ID/fecha de detección)
    actualizadas = 0
    for opp in ya_registradas:
        idx = pos_by_key.get(opp.get("clave_hash"))
        if idx is None:
            continue
        for key in _REFRESH_KEYS:
            val = opp.get(key, "")
            if val is None or str(val).strip() == "":
                continue
            df.at[idx, KEY_TO_HEADER[key]] = str(val)
        df.at[idx, KEY_TO_HEADER["fecha_ultima_revision"]] = today
        actualizadas += 1

    # 2) Agregar las nuevas con ID y fechas
    nuevas_rows = []
    for opp in nuevas:
        opp.setdefault("fecha_deteccion", today)
        opp["fecha_ultima_revision"] = today
        opp["id"] = f"VC-{counter:04d}"
        counter += 1
        nuevas_rows.append(_opp_to_row(opp))

    if nuevas_rows:
        df = pd.concat([df, pd.DataFrame(nuevas_rows, columns=COLUMN_HEADERS)], ignore_index=True)

    # 3) Escribir Excel + CSV
    df = df.reindex(columns=COLUMN_HEADERS).fillna("")
    df.to_excel(excel_path, index=False)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    logger.info("Base actualizada: +%d nuevas, %d actualizadas. Total filas: %d",
                len(nuevas_rows), actualizadas, len(df))
    logger.info("  Excel: %s", excel_path)
    logger.info("  CSV:   %s", csv_path)

    return {
        "excel_path": excel_path,
        "csv_path": csv_path,
        "nuevas": len(nuevas_rows),
        "actualizadas": actualizadas,
        "total": len(df),
    }
