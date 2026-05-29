"""
Generación del informe diario en Markdown y PDF.

Estructura (9 secciones): título, fecha, resumen ejecutivo, tabla priorizada,
oportunidades destacadas, oportunidades que requieren verificación, oportunidades
descartadas, recomendaciones de acción y anexo de fuentes consultadas.

El PDF se genera con fpdf2 (puro Python, sin dependencias de sistema). Si la librería
no está disponible o falla, se continúa solo con el Markdown (nunca rompe la ejecución).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .settings import NO_ESPECIFICADO

TITULO = "Informe diario de oportunidades de atracción de recursos para Visión Circular ANDI"


# ── Selección por categorías ──────────────────────────────────────────────────

def _es_internacional(opp: dict) -> bool:
    txt = f"{opp.get('tipo_entidad','')} {opp.get('pais_entidad','')}".lower()
    claves = ["multilateral", "bilateral", "onu", "fundación", "fundacion", "global", "cooperación", "cooperacion"]
    return any(k in txt for k in claves)


def _buckets(opps: list[dict]) -> dict[str, list[dict]]:
    inmediatas, semana, banco, aliado, estrategica = [], [], [], [], []
    for o in opps:
        urg = int(o.get("score_urgencia", 1))
        pert = int(o.get("score_pertinencia", 1))
        prob = int(o.get("score_probabilidad", 1))
        requiere = bool(o.get("requiere_verificacion"))
        if urg == 5 and not requiere:
            inmediatas.append(o)
        elif urg == 4:
            semana.append(o)
        if pert >= 3 and urg <= 2:
            banco.append(o)
        if _es_internacional(o) and prob <= 4:
            aliado.append(o)
        if requiere or (pert >= 4 and prob <= 2):
            estrategica.append(o)
    return {
        "inmediatas": inmediatas, "semana": semana, "banco": banco,
        "aliado": aliado, "estrategica": estrategica,
    }


def _fmt_monto(o: dict) -> str:
    monto = o.get("monto_disponible", NO_ESPECIFICADO)
    moneda = o.get("moneda", "")
    if monto == NO_ESPECIFICADO:
        return NO_ESPECIFICADO
    return f"{monto} {moneda}".strip()


# ── Markdown ──────────────────────────────────────────────────────────────────

def build_markdown(opps: list[dict], descartadas: list[dict], resumen: str,
                   sources: list[dict], today: str, config: dict) -> str:
    umbral = int(config.get("scoring", {}).get("umbral_destacada_pertinencia", 4))
    destacadas = [o for o in opps if int(o.get("score_pertinencia", 1)) >= umbral and not o.get("requiere_verificacion")]
    verificar = [o for o in opps if o.get("requiere_verificacion")]
    buckets = _buckets(opps)

    n_prior = len(destacadas)
    n_verif = len(verificar)
    n_urgentes = len([o for o in opps if int(o.get("score_urgencia", 1)) >= 4])

    md: list[str] = []
    md.append(f"# {TITULO}\n")
    md.append(f"**Fecha de elaboración:** {today}  ")
    md.append(f"**Generado por:** Radar de Atracción de Recursos — Projectability / Soluciones PAL\n")

    # 3. Resumen ejecutivo
    md.append("## 1. Resumen ejecutivo\n")
    md.append((resumen or "Sin resumen disponible.") + "\n")
    md.append(
        f"> **Cifras del día:** {len(opps)} oportunidades vigentes en seguimiento · "
        f"{n_prior} prioritarias · {n_verif} requieren verificación · {n_urgentes} con cierre próximo.\n"
    )

    # 4. Tabla priorizada
    md.append("## 2. Tabla priorizada de oportunidades\n")
    if opps:
        md.append("| # | Oportunidad | Entidad | Tipo de apoyo | Monto | Cierre | Estado | Urg. | Pert. | Prob. |")
        md.append("|---|-------------|---------|---------------|-------|--------|--------|:----:|:-----:|:-----:|")
        for i, o in enumerate(opps, 1):
            md.append(
                f"| {i} | {o.get('nombre','')} | {o.get('entidad_financiadora','')} | "
                f"{o.get('tipo_apoyo','')} | {_fmt_monto(o)} | {o.get('fecha_cierre','')} | "
                f"{o.get('estado','')} | {o.get('score_urgencia','')} | "
                f"{o.get('score_pertinencia','')} | {o.get('score_probabilidad','')} |"
            )
        md.append("")
    else:
        md.append("_No hay oportunidades vigentes en seguimiento hoy._\n")

    # 5. Oportunidades destacadas
    md.append("## 3. Oportunidades destacadas\n")
    if destacadas:
        for o in destacadas:
            md.append(f"### {o.get('nombre','')}\n")
            md.append(f"- **Entidad financiadora:** {o.get('entidad_financiadora','')}")
            md.append(f"- **Tipo de apoyo:** {o.get('tipo_apoyo','')}")
            md.append(f"- **Monto disponible:** {_fmt_monto(o)}")
            md.append(f"- **Fecha límite:** {o.get('fecha_cierre','')}  (Nivel de urgencia: {o.get('nivel_urgencia','')})")
            md.append(f"- **URL:** {o.get('url_oficial','')}")
            md.append(f"- **Resumen:** {o.get('resumen_ejecutivo','')}")
            md.append(f"- **Por qué es relevante para Visión Circular:** {o.get('pertinencia_vision_circular','')}")
            md.append(f"- **Cómo podría aplicarse:** {o.get('lineas_proyecto','')}")
            md.append(f"- **Riesgos:** {o.get('riesgos','')}")
            md.append(f"- **Próximo paso recomendado:** {o.get('proximo_paso','')}")
            md.append("")
    else:
        md.append("_No hay oportunidades destacadas hoy._\n")

    # 6. Requieren verificación manual
    md.append("## 4. Oportunidades que requieren verificación manual\n")
    if verificar:
        for o in verificar:
            motivo = o.get("motivo_verificacion", NO_ESPECIFICADO)
            md.append(f"- **{o.get('nombre','')}** ({o.get('entidad_financiadora','')}) — "
                      f"_{motivo}_ · {o.get('url_oficial','')}")
        md.append("")
    else:
        md.append("_Ninguna._\n")

    # 7. Descartadas
    md.append("## 5. Oportunidades descartadas\n")
    if descartadas:
        md.append("| Oportunidad | Motivo | URL |")
        md.append("|-------------|--------|-----|")
        for d in descartadas:
            md.append(f"| {d.get('nombre','')} | {d.get('motivo','')} | {d.get('url','')} |")
        md.append("")
    else:
        md.append("_Ninguna._\n")

    # 8. Recomendaciones de acción
    md.append("## 6. Recomendaciones de acción\n")
    _bucket_md(md, "Acciones inmediatas (próximas 48 horas)", buckets["inmediatas"])
    _bucket_md(md, "Acciones de esta semana", buckets["semana"])
    _bucket_md(md, "Oportunidades para banco de proyectos", buckets["banco"])
    _bucket_md(md, "Oportunidades que requieren aliado internacional", buckets["aliado"])
    _bucket_md(md, "Oportunidades que requieren decisión estratégica", buckets["estrategica"])

    # 9. Anexo de fuentes consultadas
    md.append("## 7. Anexo de fuentes consultadas\n")
    if sources:
        md.append("| URL consultada | Búsqueda | Fecha | Resultado |")
        md.append("|----------------|----------|-------|-----------|")
        for s in sources:
            md.append(f"| {s.get('url','')} | {s.get('query','')} | {today} | Analizado |")
        md.append("")
    else:
        md.append("_Sin fuentes registradas (modo simulado o sin resultados)._\n")

    return "\n".join(md)


def _bucket_md(md: list[str], titulo: str, items: list[dict]) -> None:
    md.append(f"**{titulo}:**\n")
    if items:
        for o in items:
            md.append(f"- {o.get('nombre','')} — {o.get('proximo_paso','')} (cierre: {o.get('fecha_cierre','')})")
    else:
        md.append("- _Sin elementos en esta categoría._")
    md.append("")


# ── PDF (fpdf2, con saneo a latin-1) ──────────────────────────────────────────

def _latin1(text: str) -> str:
    """fpdf2 con fuentes core usa latin-1: sustituye caracteres fuera de ese rango."""
    repl = {"–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "-", "→": "->", "…": "..."}
    for k, v in repl.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def _build_pdf(opps: list[dict], resumen: str, today: str, config: dict,
               pdf_path: Path, logger: logging.Logger) -> Path | None:
    try:
        from fpdf import FPDF  # type: ignore
        from fpdf.enums import XPos, YPos  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF no generado (instala 'fpdf2' para habilitarlo): %s", e)
        return None

    # Atajos para sustituir el obsoleto ln=1 sin desalinear el cursor.
    NEXT = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    try:
        umbral = int(config.get("scoring", {}).get("umbral_destacada_pertinencia", 4))
        destacadas = [o for o in opps if int(o.get("score_pertinencia", 1)) >= umbral and not o.get("requiere_verificacion")]

        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(pdf.epw, 7, _latin1(TITULO), **NEXT)
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(pdf.epw, 6, _latin1(f"Fecha de elaboración: {today}  ·  Projectability / Soluciones PAL"), **NEXT)
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(pdf.epw, 7, "1. Resumen ejecutivo", **NEXT)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(pdf.epw, 5, _latin1(resumen or "Sin resumen disponible."), **NEXT)
        pdf.ln(2)

        # Tabla priorizada — usa la API nativa pdf.table(), que ajusta el texto
        # automáticamente y evita el error "Not enough horizontal space".
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(pdf.epw, 7, "2. Tabla priorizada", **NEXT)
        pdf.set_font("Helvetica", "", 8)
        with pdf.table(col_widths=(40, 26, 16, 9, 9), first_row_as_headings=True,
                       line_height=5) as table:
            table.row(("Oportunidad", "Entidad", "Cierre", "Urg", "Per"))
            for o in opps:
                table.row((
                    _latin1(o.get("nombre", ""))[:80],
                    _latin1(o.get("entidad_financiadora", ""))[:50],
                    _latin1(str(o.get("fecha_cierre", "")))[:18],
                    str(o.get("score_urgencia", "")),
                    str(o.get("score_pertinencia", "")),
                ))
        pdf.ln(2)

        # Destacadas
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(pdf.epw, 7, "3. Oportunidades destacadas", **NEXT)
        for o in destacadas:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(pdf.epw, 5, _latin1(o.get("nombre", "")), **NEXT)
            pdf.set_font("Helvetica", "", 9)
            detalle = (
                f"Entidad: {o.get('entidad_financiadora','')} | Tipo: {o.get('tipo_apoyo','')} | "
                f"Monto: {_fmt_monto(o)} | Cierre: {o.get('fecha_cierre','')} ({o.get('nivel_urgencia','')})\n"
                f"URL: {o.get('url_oficial','')}\n"
                f"Resumen: {o.get('resumen_ejecutivo','')}\n"
                f"Relevancia: {o.get('pertinencia_vision_circular','')}\n"
                f"Próximo paso: {o.get('proximo_paso','')}"
            )
            pdf.multi_cell(pdf.epw, 5, _latin1(detalle), **NEXT)
            pdf.ln(1)
        if not destacadas:
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(pdf.epw, 5, "Sin oportunidades destacadas hoy.", **NEXT)

        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 8)
        pdf.multi_cell(pdf.epw, 5, _latin1(
            "Detalle completo, oportunidades que requieren verificación, descartadas, "
            "recomendaciones por horizonte y anexo de fuentes: ver el informe .md y la base en Excel/CSV."
        ), **NEXT)

        pdf.output(str(pdf_path))
        logger.info("  PDF:   %s", pdf_path)
        return pdf_path
    except Exception as e:  # noqa: BLE001 — el PDF nunca debe romper el flujo
        logger.warning("No se pudo generar el PDF: %s", e)
        return None


# ── Punto de entrada del módulo ───────────────────────────────────────────────

def write_reports(opps: list[dict], descartadas: list[dict], resumen: str,
                  sources: list[dict], config: dict, logger: logging.Logger,
                  today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    out_dir = Path(config["rutas"]["output"])
    out_dir.mkdir(parents=True, exist_ok=True)

    md_text = build_markdown(opps, descartadas, resumen, sources, today, config)
    md_path = out_dir / f"informe_oportunidades_{today}.md"
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("Informe generado:")
    logger.info("  MD:    %s", md_path)

    pdf_path = _build_pdf(opps, resumen, today, config, out_dir / f"informe_oportunidades_{today}.pdf", logger)

    return {"md_path": md_path, "pdf_path": pdf_path}
