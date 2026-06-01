"""
Radar de Atracción de Recursos — Visión Circular ANDI
Orquestador principal: búsqueda -> extracción -> validación -> scoring -> deduplicación
-> base de datos (Excel/CSV) -> informe (MD/PDF) -> borrador de correo.

Uso:
    python agent.py                 # ejecución normal (según config.json)
    python agent.py --simulate      # modo offline: datos de prueba, sin red, correo en dry-run
    python agent.py --no-email      # genera todo menos el correo
    python agent.py --provider exa  # fuerza un proveedor de búsqueda para esta corrida
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from modules import database, dedup, email_draft, extract, report, scoring, search, validate
from modules.settings import all_queries, load_config, setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Radar de Atracción de Recursos — Visión Circular ANDI")
    p.add_argument("--simulate", action="store_true",
                   help="Modo offline con datos de prueba (sin APIs ni red). Correo en dry-run.")
    p.add_argument("--no-email", action="store_true", help="No crear/enviar correo.")
    p.add_argument("--provider", help="Forzar proveedor de búsqueda (tavily|exa|brave|google_cse|serpapi|simulado).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today().isoformat()

    config = load_config()
    logger = setup_logging(config["rutas"]["logs"])

    if args.simulate:
        config["busqueda"]["proveedor"] = "simulado"
    if args.provider:
        config["busqueda"]["proveedor"] = args.provider

    logger.info("=" * 64)
    logger.info("  Radar de Atracción de Recursos — Visión Circular ANDI — %s", today)
    logger.info("  Proveedor búsqueda: %s | Modo correo: %s%s",
                config["busqueda"]["proveedor"],
                "dry_run" if (args.simulate or args.no_email) else config["correo"]["modo"],
                " | --simulate" if args.simulate else "")
    logger.info("=" * 64)

    # 1) Búsqueda
    logger.info("[1/7] Búsqueda web")
    queries = all_queries(config)
    search_results = search.run_searches(config, queries, logger)

    # 2) Extracción + estructuración
    logger.info("[2/7] Extracción y estructuración")
    data = extract.extract_opportunities(search_results, config, logger, force_offline=args.simulate)

    # 3) Validación
    logger.info("[3/7] Validación")
    data = validate.validate_opportunities(data, config, logger)
    valid = data["oportunidades"]
    descartadas = data["descartadas"]
    resumen = data.get("resumen_ejecutivo", "")

    # 4) Scoring
    logger.info("[4/7] Scoring y clasificación")
    scoring.apply_scoring(valid, config, logger)

    # 5) Deduplicación contra el histórico
    logger.info("[5/7] Deduplicación")
    df_existing = database.load_existing(
        Path(config["rutas"]["excel"]), Path(config["rutas"]["csv"])
    )
    nuevas, ya_registradas = dedup.split_new_existing(valid, database.existing_keys(df_existing), logger)

    # 6) Base de datos (Excel + CSV)
    logger.info("[6/7] Base de datos (Excel + CSV)")
    db = database.update_database(nuevas, ya_registradas, config, logger, today)

    # 7) Informe + correo
    logger.info("[7/7] Informe y correo")
    valid_sorted = scoring.sort_opportunities(valid)
    rep = report.write_reports(valid_sorted, descartadas, resumen, search_results, config, logger, today)

    umbral = int(config.get("scoring", {}).get("umbral_destacada_pertinencia", 4))
    stats = {
        "vigentes": len(valid),
        "nuevas": len(nuevas),
        "prioritarias": len([o for o in valid if int(o.get("score_pertinencia", 1)) >= umbral
                             and not o.get("requiere_verificacion")]),
        "verificar": len([o for o in valid if o.get("requiere_verificacion")]),
        "urgentes": len([o for o in valid if int(o.get("score_urgencia", 1)) >= 4]),
    }

    if args.no_email:
        logger.info("--no-email: se omite el correo.")
    else:
        attachments = [rep["md_path"], rep.get("pdf_path"), db["excel_path"]]
        email_draft.handle_email(stats, config, attachments, logger, today,
                                 force_dry_run=args.simulate,
                                 opps=valid_sorted,
                                 resumen=resumen)

    logger.info("=" * 64)
    logger.info("  RESUMEN: %d vigentes | %d nuevas | %d prioritarias | %d a verificar | %d urgentes",
                len(valid), stats["nuevas"], stats["prioritarias"], stats["verificar"], stats["urgentes"])
    logger.info("  Base total: %d filas", db["total"])
    logger.info("  Ejecución finalizada correctamente.")
    logger.info("=" * 64)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR FATAL] {exc}\n", file=sys.stderr)
        raise
