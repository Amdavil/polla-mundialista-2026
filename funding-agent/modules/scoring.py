"""
Scoring y clasificación.

- Urgencia: DETERMINISTA, calculada a partir de la fecha de cierre (no la inventa el modelo).
- Estado y nivel de urgencia: derivados de fechas y de la marca 'requiere_verificacion'.
- Pertinencia y probabilidad: las propone el modelo; aquí solo se validan y acotan a 1-5.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from .settings import NO_ESPECIFICADO


def parse_date(value: str | None) -> date | None:
    """Intenta interpretar una fecha YYYY-MM-DD (o variantes comunes). Devuelve None si no es fecha exacta."""
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _clamp_score(value, default: int = 3) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(1, min(5, n))


def compute_urgency(fecha_cierre: str | None, today: date, thresholds: dict) -> tuple[int, date | None]:
    """Devuelve (score_urgencia 1-5, fecha_cierre_parseada|None)."""
    cierre = parse_date(fecha_cierre)
    if cierre is None:
        return 1, None  # sin fecha clara o convocatoria futura
    dias = (cierre - today).days
    if dias < 0:
        return 1, cierre  # ya cerró
    alta = int(thresholds.get("alta_max_dias", 15))
    media_alta = int(thresholds.get("media_alta_max_dias", 30))
    media = int(thresholds.get("media_max_dias", 60))
    if dias < alta:
        return 5, cierre
    if dias <= media_alta:
        return 4, cierre
    if dias <= media:
        return 3, cierre
    return 2, cierre


def _nivel_urgencia(score: int, requiere_verificacion: bool) -> str:
    if requiere_verificacion:
        return "Requiere verificación"
    if score >= 4:
        return "Alta"
    if score == 3:
        return "Media"
    return "Baja"


def _estado(opp: dict, today: date, cierre: date | None) -> str:
    if opp.get("requiere_verificacion"):
        return "Requiere verificación manual"
    apertura = parse_date(opp.get("fecha_apertura"))
    if apertura and apertura > today:
        return "Próxima a abrir"
    if cierre is not None:
        return "Cerrada" if (cierre - today).days < 0 else "Activa"
    # Sin fecha de cierre parseable
    raw = str(opp.get("fecha_cierre", "")).lower()
    if "permanente" in raw or "abierta" in raw:
        return "Activa"
    if raw in ("", NO_ESPECIFICADO.lower(), "no especificado"):
        return "Sin fecha definida"
    return "Activa"


def apply_scoring(opportunities: list[dict], config: dict, logger: logging.Logger,
                  today: date | None = None) -> list[dict]:
    today = today or date.today()
    thresholds = config.get("scoring", {}).get("urgencia_dias", {})

    for opp in opportunities:
        score_urg, cierre = compute_urgency(opp.get("fecha_cierre"), today, thresholds)
        requiere = bool(opp.get("requiere_verificacion"))

        opp["score_urgencia"] = score_urg
        opp["score_pertinencia"] = _clamp_score(opp.get("score_pertinencia"), default=3)
        opp["score_probabilidad"] = _clamp_score(opp.get("score_probabilidad"), default=3)
        opp["estado"] = _estado(opp, today, cierre)
        if opp["estado"] == "Cerrada":
            opp["score_urgencia"] = 1
        opp["nivel_urgencia"] = _nivel_urgencia(opp["score_urgencia"], requiere)

    logger.info("Scoring aplicado a %d oportunidades.", len(opportunities))
    return opportunities


def sort_opportunities(opportunities: list[dict]) -> list[dict]:
    """Orden priorizado: urgencia, pertinencia, probabilidad y luego fecha de cierre más próxima."""
    def key(o: dict):
        cierre = parse_date(o.get("fecha_cierre"))
        cierre_ord = cierre.toordinal() if cierre else 10**7  # sin fecha al final
        return (
            -int(o.get("score_urgencia", 1)),
            -int(o.get("score_pertinencia", 1)),
            -int(o.get("score_probabilidad", 1)),
            cierre_ord,
        )
    return sorted(opportunities, key=key)
