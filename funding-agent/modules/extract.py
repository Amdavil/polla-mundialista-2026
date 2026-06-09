"""
Extracción y estructuración de oportunidades con Claude.

Toma los resultados de búsqueda en crudo y produce oportunidades estructuradas
(la mayoría de los 35 campos; el scoring de urgencia, estado, ID y hash se calculan
después en Python). Aplica las reglas de validación y de no-invención.

Modo offline: si no hay ANTHROPIC_API_KEY (o se fuerza --simulate), carga
oportunidades enlatadas de tests/sample_opportunities.json para probar el pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .settings import get_env, TIPOS_APOYO, BASE_DIR

EXTRACTION_PROMPT = """Eres un analista senior de atracción de recursos para PROJECTABILITY / Soluciones PAL, \
que apoya el programa VISIÓN CIRCULAR de la ANDI (Colombia). Visión Circular trabaja en economía circular, \
cierre de ciclo de envases y empaques, reciclaje, ecodiseño, reciclabilidad, plásticos flexibles, \
inclusión de recicladores, cumplimiento de la Responsabilidad Extendida del Productor (REP), economía \
circular territorial, modelos de negocio circulares, pilotos empresariales y articulación con empresas, \
gremios, universidades, centros tecnológicos y autoridades.

Se te entregan resultados de búsqueda web del día de hoy. Tu tarea es identificar OPORTUNIDADES REALES y \
VIGENTES de financiación, cooperación, grants, convocatorias, asistencia técnica, premios, fondos climáticos \
o innovación aplicables a COLOMBIA o América Latina.

REGLAS DE VALIDACIÓN (aplícalas estrictamente):
1. Incluye solo oportunidades activas o próximas a abrir.
2. Colombia, América Latina o entidades colombianas deben poder aplicar (directamente o vía alianzas).
3. El tema debe relacionarse con economía circular, reciclaje, envases/empaques, sostenibilidad, clima, \
residuos, innovación ambiental o inclusión.
4. Debe existir una URL oficial o de fuente confiable.
5. Debe haber fecha límite, ventana estimada o estado de convocatoria.
6. NO incluyas noticias antiguas sin convocatoria vigente.
7. NO incluyas cursos, eventos o contenido académico salvo que tengan financiación, grant, asistencia \
técnica o cooperación asociada.

REGLAS DE CALIDAD (obligatorias):
- NO inventes nombres, montos, fechas ni URLs. Si un dato no aparece, escribe exactamente "No especificado".
- Diferencia lo confirmado de lo inferido: si infieres algo, dilo en "observaciones".
- Si hay incertidumbre sobre vigencia, elegibilidad o si la fuente es oficial, marca "requiere_verificacion": true \
y explica por qué en "motivo_verificacion" (NO la descartes).
- Si una oportunidad NO cumple las reglas, ponla en "descartadas" con su motivo.

CATÁLOGO de "tipo_apoyo" (elige uno o varios, separados por '; '): {tipos_apoyo}.

RÚBRICA DE SCORES (1 a 5; usa enteros):
- score_pertinencia: 5 = altamente alineada con Visión Circular (economía circular, reciclaje, envases/empaques, \
inclusión, sostenibilidad empresarial); 4 = buena relación temática; 3 = relación indirecta aprovechable; \
2 = baja relación; 1 = no prioritaria.
- score_probabilidad: 5 = elegibilidad clara para ANDI, empresas, gremios, Colombia o alianzas; 4 = aplicable con \
aliados; 3 = requiere interpretación; 2 = elegibilidad dudosa; 1 = baja probabilidad.
(El score de urgencia NO lo calculas tú; se deriva de la fecha de cierre.)

Para "fecha_cierre" y "fecha_apertura" usa formato YYYY-MM-DD si hay fecha exacta; si solo hay una ventana \
aproximada escribe una estimación textual (ej. "Aprox. 25 días" o "Abierta permanentemente"); si no hay \
información escribe "No especificado".

Responde ÚNICAMENTE con un JSON válido (sin texto adicional) con esta estructura EXACTA:
{{
  "oportunidades": [
    {{
      "nombre": "Nombre oficial de la convocatoria/fondo",
      "entidad_financiadora": "Organización que financia",
      "tipo_entidad": "Banca multilateral | Fondo climático | Fondo ambiental | Agencia ONU | Cooperación bilateral | Cooperación multilateral | Fundación | ONG | Gobierno | Plataforma | Otro",
      "pais_entidad": "País o región de la entidad",
      "paises_elegibles": "Países o regiones que pueden aplicar",
      "sector_principal": "Tema principal (ej. Economía circular, Reciclaje, Envases y empaques, Clima, Residuos)",
      "subtema": "Subtema específico (ej. Plásticos flexibles, Inclusión de recicladores, Ecodiseño, REP)",
      "tipo_apoyo": "Uno o varios del catálogo, separados por '; '",
      "monto_disponible": "Monto, rango o 'No especificado'",
      "moneda": "USD | EUR | COP | Otro | No especificado",
      "cofinanciacion_requerida": "Sí / No / Descripción / No especificado",
      "fecha_apertura": "YYYY-MM-DD | texto | No especificado",
      "fecha_cierre": "YYYY-MM-DD | texto | No especificado",
      "url_oficial": "URL oficial directa",
      "url_secundaria": "URL de apoyo o 'No especificado'",
      "resumen_ejecutivo": "2-3 oraciones ejecutivas: qué financia y bajo qué condiciones",
      "pertinencia_vision_circular": "Por qué es relevante para Visión Circular ANDI (1-2 oraciones)",
      "lineas_proyecto": "Posibles líneas de proyecto aplicables desde Visión Circular",
      "requisitos_principales": "Requisitos clave o 'No especificado'",
      "documentos_requeridos": "Documentos a preparar o 'No especificado'",
      "aliados_potenciales": "Aliados sugeridos (gremios, universidades, recicladores, cooperación) o 'No especificado'",
      "riesgos": "Riesgos o restricciones o 'No especificado'",
      "recomendacion_accion": "Recomendación de acción concreta",
      "proximo_paso": "Próximo paso sugerido (qué hacer ya)",
      "responsable_sugerido": "Perfil/área sugerida (ej. Coordinación de proyectos, Alianzas) o 'No especificado'",
      "score_pertinencia": 5,
      "score_probabilidad": 4,
      "observaciones": "Notas, supuestos o inferencias",
      "colombia_o_latam_elegible": true,
      "es_financiacion": true,
      "requiere_verificacion": false,
      "motivo_verificacion": ""
    }}
  ],
  "descartadas": [
    {{ "nombre": "...", "url": "...", "motivo": "No aplica para Colombia | Cerrada | Sin financiación | Fuente no oficial | No relacionada con sostenibilidad/circularidad | Duplicada" }}
  ],
  "resumen_ejecutivo": "Máximo 3 párrafos con los hallazgos del día, mejores oportunidades y fechas críticas."
}}

Si no encuentras oportunidades válidas, devuelve "oportunidades": [] y explica en "resumen_ejecutivo".

RESULTADOS DE BÚSQUEDA DE HOY:
"""


def _format_results(search_results: list[dict]) -> str:
    text = ""
    for i, r in enumerate(search_results, 1):
        text += f"\n[{i}]\nTÍTULO: {r.get('title', 'N/A')}\nURL: {r.get('url', 'N/A')}\n"
        text += f"CONTENIDO: {(r.get('content') or '')[:400]}\n---\n"
    return text


def _strip_fences(raw: str) -> str:
    """Quita envoltorios markdown ```json ... ``` si Claude los agrega."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def _salvage_opportunities(raw: str) -> list[dict]:
    """Recupera los objetos COMPLETOS del arreglo 'oportunidades' cuando el JSON
    llegó truncado (p. ej. por max_tokens). Devuelve los que sí cierran bien."""
    start = raw.find('"oportunidades"')
    if start == -1:
        return []
    bracket = raw.find("[", start)
    if bracket == -1:
        return []
    objs: list[dict] = []
    depth, buf, in_str, esc = 0, "", False, False
    for ch in raw[bracket + 1:]:
        if depth == 0 and ch == "]" and not in_str:
            break
        if ch == '"' and not esc:
            in_str = not in_str
        esc = (ch == "\\" and not esc)
        if not in_str and ch == "{":
            depth += 1
        if depth >= 1:
            buf += ch
        if not in_str and ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    objs.append(json.loads(buf))
                except json.JSONDecodeError:
                    pass
                buf = ""
    return objs


def _parse_json(raw: str, logger: logging.Logger) -> dict:
    text = _strip_fences(raw)
    match = re.search(r"\{[\s\S]*\}", text)
    candidate = match.group() if match else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.warning("JSON de Claude inválido (%s). Intento recuperar objetos completos...", e)
        opps = _salvage_opportunities(text)
        if opps:
            logger.info("Recuperadas %d oportunidades de una respuesta truncada.", len(opps))
            return {"oportunidades": opps, "descartadas": [], "resumen_ejecutivo": ""}
        logger.error("No se pudo recuperar nada del JSON de Claude.")
        return {"oportunidades": [], "descartadas": [], "resumen_ejecutivo": ""}


def _offline_extract(logger: logging.Logger) -> dict:
    sample = BASE_DIR / "tests" / "sample_opportunities.json"
    logger.warning("Extracción OFFLINE: usando %s (datos simulados, NO producción).", sample.name)
    if not sample.exists():
        return {"oportunidades": [], "descartadas": [], "resumen_ejecutivo": "Sin datos simulados disponibles."}
    return json.loads(sample.read_text(encoding="utf-8"))


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _call_claude(client, model: str, max_tokens: int, prompt: str) -> str:
    message = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_groq(api_key: str, model: str, max_tokens: int, prompt: str) -> str:
    """Llama a Groq con reintentos automáticos si hay rate-limit (429).
    Respeta el header Retry-After que Groq devuelve con el tiempo exacto."""
    import time as _time, requests as _req
    _time.sleep(13)  # llama-3.1-8b-instant: 20K TPM → ~1 llamada/13s
    for attempt in range(3):
        resp = _req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": min(max_tokens, 4000),
                "temperature": 0.1,
            },
            timeout=120,
        )
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "20"))
            _time.sleep(wait + 3)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    resp.raise_for_status()


def _call_gemini(api_key: str, model: str, max_tokens: int, prompt: str) -> str:
    """Llama a Google Gemini con reintentos automáticos.
    Free tier: 15 RPM → sleep 4.5s entre llamadas para no exceder el límite."""
    import time as _time, requests as _req
    _time.sleep(4.5)  # Gemini free: 15 req/min → 1 cada 4s
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": min(max_tokens, 8192),
            "temperature": 0.1,
        },
    }
    for attempt in range(3):
        resp = _req.post(url, json=body, timeout=120)
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "15"))
            _time.sleep(wait + 2)
            continue
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    resp.raise_for_status()


def _synthesize_summary(call_fn, parciales: list[str], logger: logging.Logger) -> str:
    """Funde los resúmenes por lote en uno solo y coherente (1 llamada corta)."""
    base = "\n\n".join(p for p in parciales if p)
    if not base:
        return ""
    try:
        prompt = (
            "Eres analista de atracción de recursos para Visión Circular (ANDI). "
            "A partir de estos resúmenes parciales del día, redacta UN único resumen "
            "ejecutivo en español, máximo 3 párrafos, sin inventar datos ni repetir información:\n\n"
            + base
        )
        return call_fn(prompt).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo sintetizar el resumen; se usa la concatenación. (%s)", e)
        return base


def extract_opportunities(search_results: list[dict], config: dict, logger: logging.Logger,
                          force_offline: bool = False) -> dict:
    anthropic_key = None if force_offline else get_env("ANTHROPIC_API_KEY")
    groq_key      = None if force_offline else get_env("GROQ_API_KEY")
    gemini_key    = None if force_offline else get_env("GEMINI_API_KEY")

    if not anthropic_key and not groq_key and not gemini_key:
        if not force_offline:
            logger.warning(
                "No hay ANTHROPIC_API_KEY, GROQ_API_KEY ni GEMINI_API_KEY. "
                "Extracción en modo OFFLINE (simulado)."
            )
        return _offline_extract(logger)

    modelo     = config.get("modelo", {})
    max_tokens = int(modelo.get("max_tokens", 8192))
    batch_size = max(1, int(modelo.get("batch_size", 25)))

    # ── Construir cadena de proveedores con fallback automático ─────────────
    providers: list[tuple[str, object]] = []
    if anthropic_key:
        try:
            import anthropic as _anthropic
            _client = _anthropic.Anthropic(api_key=anthropic_key)
            _mn = modelo.get("extraccion", "claude-sonnet-4-5")
            providers.append(("Claude", lambda p, c=_client, m=_mn: _call_claude(c, m, max_tokens, p)))
        except ImportError:
            pass
    # Gemini antes que Groq: 1M TPM vs 20K TPM — mucho más estable para uso diario
    if gemini_key:
        _mn = modelo.get("extraccion_gemini", "gemini-2.0-flash")
        providers.append(("Gemini", lambda p, k=gemini_key, m=_mn: _call_gemini(k, m, max_tokens, p)))
    if groq_key:
        _mn = modelo.get("extraccion_groq", "llama-3.1-8b-instant")
        providers.append(("Groq", lambda p, k=groq_key, m=_mn: _call_groq(k, m, max_tokens, p)))

    if not providers:
        return _offline_extract(logger)

    # Seleccionar proveedor activo; si falla por billing/auth, pasar al siguiente
    _BILLING_MARKERS = ("credit balance", "insufficient_quota", "billing", "quota", "unauthorized", "401", "403")

    def _is_billing_or_auth(exc: Exception) -> bool:
        return any(m in str(exc).lower() for m in _BILLING_MARKERS)

    def _pick_provider(batch_prompt: str) -> tuple[str, object, str]:
        """Intenta proveedores en orden; devuelve (nombre, call_fn, primera_respuesta)."""
        for pname, pfn in providers:
            try:
                resp = pfn(batch_prompt)
                logger.info("Proveedor IA activo: %s", pname)
                return pname, pfn, resp
            except Exception as e:
                if _is_billing_or_auth(e):
                    logger.warning("Proveedor %s sin créditos/acceso (%s) — probando siguiente...", pname, type(e).__name__)
                else:
                    raise
        raise RuntimeError("Ningún proveedor IA disponible (revisa las API keys y créditos).")

    base_prompt = EXTRACTION_PROMPT.format(tipos_apoyo=", ".join(TIPOS_APOYO))
    batches     = list(_chunks(search_results, batch_size))
    logger.info("Analizando %d resultados en %d lote(s) de hasta %d...",
                len(search_results), len(batches), batch_size)

    all_opps: list[dict] = []
    all_desc: list[dict] = []
    parciales: list[str] = []
    active_fn: object | None = None   # proveedor que funcionó, reutilizar en lotes siguientes

    for n, batch in enumerate(batches, 1):
        prompt = base_prompt + _format_results(batch)
        try:
            if active_fn is None:
                pname, active_fn, raw = _pick_provider(prompt)
            else:
                raw = active_fn(prompt)
        except Exception as e:  # noqa: BLE001
            logger.error("Lote %d/%d falló: %s", n, len(batches), e)
            continue
        data = _parse_json(raw, logger)
        opps = data.get("oportunidades", []) or []
        desc = data.get("descartadas", []) or []
        all_opps.extend(opps)
        all_desc.extend(desc)
        if data.get("resumen_ejecutivo"):
            parciales.append(data["resumen_ejecutivo"])
        logger.info("  Lote %d/%d: %d oportunidades, %d descartadas.", n, len(batches), len(opps), len(desc))

    resumen = _synthesize_summary(active_fn or (lambda p: ""), parciales, logger) if len(batches) > 1 else (parciales[0] if parciales else "")

    logger.info("Devolvió %d oportunidades y %d descartadas (total).", len(all_opps), len(all_desc))
    return {"oportunidades": all_opps, "descartadas": all_desc, "resumen_ejecutivo": resumen}
