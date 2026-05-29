# Radar de Atracción de Recursos — Visión Circular ANDI

Agente automatizado que **cada día** identifica oportunidades de financiación, cooperación, grants,
convocatorias, asistencia técnica, premios y fondos climáticos en **economía circular, reciclaje,
envases/empaques, sostenibilidad, clima e innovación ambiental** aplicables a **Colombia**, con foco en
el programa **Visión Circular de la ANDI**.

Para cada jornada el agente:
1. Busca en la web con un proveedor configurable (Tavily por defecto).
2. Extrae y estructura las oportunidades con Claude.
3. Valida vigencia, fuente oficial, elegibilidad y temática.
4. Asigna puntajes de **pertinencia, urgencia y probabilidad** (1–5).
5. Deduplica contra el histórico (sin borrar registros previos).
6. Actualiza la base en **Excel + CSV** (35 columnas).
7. Genera un **informe diario en Markdown y PDF**.
8. Crea un **borrador de correo en Gmail** (no lo envía) para el equipo.
9. Deja **logs** y **trazabilidad de fuentes**.

---

## 1. Estructura del proyecto

```
funding-agent/
├── agent.py                  # Orquestador (punto de entrada)
├── config.json               # Proveedor de búsqueda, modo de correo, modelo, umbrales
├── config/
│   ├── keywords.json         # Consultas bilingües (ES/EN) — editable
│   └── sources.json          # Fuentes prioritarias y sus dominios oficiales — editable
├── modules/
│   ├── settings.py           # Config, .env, logging, las 35 columnas y catálogos
│   ├── search.py             # Búsqueda con proveedor intercambiable (+ modo simulado)
│   ├── extract.py            # Extracción/estructuración con Claude (+ modo offline)
│   ├── validate.py           # Reglas de validación y de no-invención
│   ├── scoring.py            # Urgencia determinista + pertinencia/probabilidad
│   ├── dedup.py              # Deduplicación por nombre + entidad + URL
│   ├── database.py           # Excel + CSV (histórico, 35 columnas)
│   ├── report.py             # Informe Markdown + PDF (9 secciones)
│   └── email_draft.py        # Borrador Gmail (IMAP) / envío SMTP / dry-run
├── data/                     # Base: .xlsx y .csv (histórico acumulado)
├── output/                   # Informes fechados (.md, .pdf) y correos dry-run (.eml)
├── logs/                     # Un log por día
├── tests/                    # Datos de prueba para el modo simulado
├── requirements.txt
├── .env.example              # Plantilla de variables de entorno
└── README.md
```

---

## 2. Instalación

Requiere **Python 3.11+**.

```bash
cd funding-agent
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Configurar variables de entorno

Copia la plantilla y completa tus claves:

```bash
cp .env.example .env      # En Windows PowerShell:  Copy-Item .env.example .env
```

| Variable              | Para qué sirve                                              | ¿Obligatoria?                |
|-----------------------|------------------------------------------------------------|------------------------------|
| `SEARCH_API_KEY`      | Clave del proveedor de búsqueda activo                     | Sí (salvo modo simulado)     |
| `GOOGLE_CSE_ID`       | ID del motor, solo si usas `google_cse`                   | Solo con Google CSE          |
| `ANTHROPIC_API_KEY`   | Análisis y estructuración con Claude                      | Sí (salvo modo simulado)     |
| `GMAIL_SENDER_EMAIL`  | Cuenta Gmail que crea el borrador                         | Sí (para el correo)          |
| `GMAIL_APP_PASSWORD`  | App Password de Gmail (16 caracteres, sin espacios)       | Sí (para el correo)          |
| `TEAM_EMAILS`         | Destinatarios del equipo, separados por coma              | Recomendada                  |

> Sin `SEARCH_API_KEY` o `ANTHROPIC_API_KEY`, el agente **cae automáticamente a modo simulado** (datos de
> prueba) y avisa en el log. Útil para probar, **no para producción**.

---

## 4. Ejecutar manualmente

```bash
python agent.py                 # Ejecución normal (usa config.json y .env)
python agent.py --simulate      # Prueba offline: datos simulados, sin red, correo en dry-run
python agent.py --no-email      # Hace todo menos el correo
python agent.py --provider exa  # Fuerza un proveedor de búsqueda solo en esta corrida
```

Tras una corrida revisa:
- `data/oportunidades_atraccion_recursos_vision_circular.xlsx` y `.csv` — la base actualizada.
- `output/informe_oportunidades_AAAA-MM-DD.md` y `.pdf` — el informe del día.
- `logs/agente_AAAA-MM-DD.log` — la traza completa.

---

## 5. Cambiar el proveedor de búsqueda

En `config.json` → `busqueda.proveedor`. Opciones: `tavily` (recomendado), `exa`, `brave`,
`google_cse`, `serpapi`, `simulado`.

```json
"busqueda": { "proveedor": "tavily", "max_resultados_por_query": 5, "profundidad": "advanced" }
```

La clave va siempre en `SEARCH_API_KEY` (y `GOOGLE_CSE_ID` solo para Google CSE). Obtén una key gratuita
de Tavily en https://tavily.com (1.000 búsquedas/mes).

---

## 6. Cambiar fuentes y palabras clave

- **Consultas de búsqueda:** edita `config/keywords.json` (listas `queries_es`, `queries_en`,
  `queries_por_fuente`). Agrega, quita o reordena libremente.
- **Fuentes prioritarias:** edita `config/sources.json`. Cada fuente tiene `nombre`, `tipo`, `region` y
  `dominios`. Los dominios se usan para reconocer URLs oficiales; si una oportunidad llega de un dominio
  no listado, el agente la marca **"Requiere verificación"** (no la descarta).

No hay que tocar código para ajustar el alcance temático o las fuentes.

---

## 7. Configurar Gmail para crear borradores

El modo por defecto (`config.json` → `correo.modo: "borrador_imap"`) crea un **borrador real** en tu
Gmail usando una **App Password** (sin OAuth). El correo **no se envía**: queda en Borradores para que lo
revises y lo mandes a mano.

1. Activa la **verificación en 2 pasos**: https://myaccount.google.com/security
2. Genera una **App Password**: https://myaccount.google.com/apppasswords
   - App: *Correo* · Dispositivo: *Otro* → nombre "Radar Visión Circular" → **Generar**.
   - Copia los 16 caracteres **sin espacios** → `GMAIL_APP_PASSWORD`.
3. Verifica que **IMAP esté habilitado** en Gmail → Configuración → *Reenvío y POP/IMAP* → *Habilitar IMAP*.
4. Pon tu correo en `GMAIL_SENDER_EMAIL` y los destinatarios en `TEAM_EMAILS`.

**Modos de correo** (`config.json` → `correo.modo`):
- `borrador_imap` — crea el borrador en Gmail (recomendado).
- `envio_smtp` — envía el correo de inmediato.
- `dry_run` — no toca la red; guarda el correo como `.eml` en `output/` (para pruebas).

---

## 8. Programar la ejecución diaria

### Opción A — GitHub Actions (recomendada, en la nube)

Ya viene un workflow en `.github/workflows/daily-funding-search.yml` que corre **de lunes a viernes a las
8:00 AM (hora Colombia)** y permite ejecución manual.

1. Sube el repo a GitHub.
2. En **Settings → Secrets and variables → Actions** crea estos secretos:
   `SEARCH_API_KEY`, `ANTHROPIC_API_KEY`, `GMAIL_SENDER_EMAIL`, `GMAIL_APP_PASSWORD`, `TEAM_EMAILS`
   (y `GOOGLE_CSE_ID` solo si usas Google CSE).
3. Pestaña **Actions → Radar Diario — Visión Circular ANDI → Run workflow** para probar.

El workflow guarda la base actualizada en el repo y sube el informe del día como *artifact*.
Para cambiar el horario, edita el `cron` (ayuda: https://crontab.guru).

### Opción B — Programador local (Windows)

Crea una tarea en el **Programador de tareas** que ejecute:
```
C:\ruta\a\funding-agent\.venv\Scripts\python.exe  C:\ruta\a\funding-agent\agent.py
```
con "Iniciar en" = la carpeta `funding-agent`. En macOS/Linux usa `cron`.

---

## 9. La base de datos (35 columnas)

Se guarda en `data/` como Excel **y** CSV con estas columnas: ID, Fecha de detección, Nombre, Entidad
financiadora, Tipo de entidad, País/región de la entidad, Países elegibles, Sector o tema principal,
Subtema, Tipo de apoyo, Monto disponible, Moneda, Cofinanciación requerida, Fecha de apertura, Fecha de
cierre, Estado, Nivel de urgencia, URL oficial, URL secundaria, Resumen ejecutivo, Pertinencia para
Visión Circular ANDI, Posibles líneas de proyecto, Requisitos principales, Documentos requeridos, Aliados
potenciales, Riesgos o restricciones, Recomendación de acción, Próximo paso sugerido, Responsable
sugerido, Score de pertinencia, Score de urgencia, Score de probabilidad, Observaciones, Hash/clave
anti-duplicados, Fecha de última revisión.

**El histórico nunca se borra.** Las oportunidades ya registradas se **actualizan en sitio** (estado,
urgencia, scores y fecha de última revisión); solo las nuevas agregan filas con ID secuencial (`VC-0001`…).

---

## 10. Cómo se calculan los puntajes

- **Urgencia (determinista, en Python a partir de la fecha de cierre):**
  5 = cierra en <15 días · 4 = 15–30 días · 3 = 31–60 días · 2 = >60 días · 1 = sin fecha clara.
- **Pertinencia (la propone Claude con la rúbrica):**
  5 = altamente alineada con Visión Circular · 4 = buena · 3 = indirecta aprovechable · 2 = baja · 1 = no prioritaria.
- **Probabilidad de aplicación:**
  5 = elegibilidad clara para ANDI/Colombia · 4 = aplicable con aliados · 3 = requiere interpretación · 2 = dudosa · 1 = baja.
- **Nivel de urgencia:** Alta (score 4–5) · Media (3) · Baja (1–2) · *Requiere verificación* (datos insuficientes).

---

## 11. Reglas de calidad aplicadas

- No se inventan nombres, montos, fechas ni URLs; lo que falta queda como **"No especificado"**.
- Toda oportunidad debe tener una **URL** válida; sin fuente se descarta como "Fuente no oficial".
- Lo dudoso se marca **"Requiere verificación manual"** con su motivo (no se elimina).
- Deduplicación por **nombre + entidad + dominio de la URL**.
- Lenguaje ejecutivo, apto para dirección.

---

## 12. Costos estimados

| Servicio          | Costo aproximado              |
|-------------------|-------------------------------|
| Tavily            | Gratis (1.000 búsquedas/mes)  |
| Claude API        | ~1–3 USD/mes según volumen    |
| GitHub Actions    | Gratis                        |
| Gmail (IMAP/SMTP) | Gratis                        |

---

## 13. Solución de problemas

- **"Falta la variable de entorno…"** → revisa tu `.env` (o los secretos de GitHub).
- **Cae a modo simulado sin querer** → faltan `SEARCH_API_KEY` o `ANTHROPIC_API_KEY`.
- **No aparece el borrador en Gmail** → confirma IMAP habilitado y App Password correcta; si tu Gmail está
  en español, el agente prueba también la carpeta "[Gmail]/Borradores".
- **No se generó el PDF** → instala `fpdf2` (`pip install fpdf2`). El Markdown se genera igual.
- **Logs** → `logs/agente_AAAA-MM-DD.log`.

---

## 14. De prototipo a versión estable (próximos pasos)

1. **Verificación de URLs en vivo** (HEAD/GET) para confirmar que la convocatoria sigue activa.
2. **Scraping dirigido** de páginas de convocatorias de las fuentes prioritarias (no solo búsqueda).
3. **Caché de fuentes** y control de cuota del proveedor de búsqueda.
4. **Alertas** (Slack/Teams) además del correo, para oportunidades de urgencia Alta.
5. **Tablero** (p. ej. Looker Studio o Power BI) sobre el CSV para ver el pipeline.
6. **Pruebas automatizadas** de cada módulo y validación de esquema del JSON de Claude.
7. **Migración opcional a Gmail API (OAuth)** si se requiere multi-cuenta o etiquetas automáticas.
