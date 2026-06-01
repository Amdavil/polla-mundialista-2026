"""
Creación del correo del equipo.

Modos (config.json -> correo.modo):
  - borrador_imap : crea un BORRADOR REAL en Gmail vía IMAP APPEND (no envía). Recomendado.
  - envio_smtp    : envía el correo de inmediato vía SMTP_SSL.
  - dry_run       : no toca la red; guarda el .eml en output/ (para pruebas sin credenciales).

Credenciales (variables de entorno):
  GMAIL_SENDER_EMAIL (o GMAIL_USER), GMAIL_APP_PASSWORD, TEAM_EMAILS (separados por coma).
La App Password requiere verificación en 2 pasos e IMAP habilitado en Gmail (ver README).
"""

from __future__ import annotations

import html as _html_mod
import imaplib
import logging
import mimetypes
import smtplib
import time
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .settings import get_env

_DRAFT_FOLDERS = ['"[Gmail]/Drafts"', '"[Gmail]/Borradores"', "Drafts", "Borradores"]


# ── Helpers HTML ──────────────────────────────────────────────────────────────

def _e(text) -> str:
    """Escapa caracteres HTML especiales."""
    return _html_mod.escape(str(text) if text else "")


def _t(text, n: int) -> str:
    """Trunca texto a n caracteres con ellipsis."""
    s = str(text) if text else ""
    return (s[:n] + "…") if len(s) > n else s


def _score_dot(score) -> str:
    """Círculo de color con el score de pertinencia."""
    try:
        s = int(score)
    except (TypeError, ValueError):
        s = 1
    colors = {5: "#1B5E20", 4: "#43A047", 3: "#F57C00", 2: "#EF5350", 1: "#BDBDBD"}
    c = colors.get(s, "#BDBDBD")
    return (
        f'<span style="display:inline-block;width:22px;height:22px;background:{c};'
        f'color:#fff;border-radius:50%;text-align:center;line-height:22px;'
        f'font-weight:bold;font-size:11px;">{s}</span>'
    )


def _estado_badge(estado: str) -> str:
    """Badge de color según estado de la oportunidad."""
    e = str(estado)
    if "Activa" in e:
        return ('<span style="background:#4CAF50;color:#fff;padding:2px 8px;'
                'border-radius:10px;font-size:10px;font-weight:bold;white-space:nowrap;">Activa</span>')
    if "verificaci" in e.lower():
        return ('<span style="background:#FF8F00;color:#fff;padding:2px 8px;'
                'border-radius:10px;font-size:10px;white-space:nowrap;">Verificar</span>')
    if "Próxima" in e:
        return ('<span style="background:#1565C0;color:#fff;padding:2px 8px;'
                'border-radius:10px;font-size:10px;white-space:nowrap;">Próxima</span>')
    return ('<span style="background:#9E9E9E;color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:10px;white-space:nowrap;">Revisar</span>')


def _opp_rows(opps: list[dict], max_rows: int = 8) -> str:
    """Genera las filas HTML de la tabla de oportunidades."""
    if not opps:
        return ('<tr><td colspan="6" style="padding:16px;text-align:center;'
                'color:#888;font-style:italic;font-size:12px;">'
                'Sin oportunidades identificadas hoy.</td></tr>')
    rows = []
    for i, o in enumerate(opps[:max_rows]):
        bg = "#ffffff" if i % 2 == 0 else "#F1F8F1"
        rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 6px 8px 10px;color:#999;font-size:11px;">{i + 1}</td>'
            f'<td style="padding:8px 6px;font-size:12px;font-weight:bold;color:#1B5E20;">'
            f'{_e(_t(o.get("nombre", ""), 55))}</td>'
            f'<td style="padding:8px 6px;font-size:11px;color:#555;">'
            f'{_e(_t(o.get("entidad_financiadora", ""), 28))}</td>'
            f'<td style="padding:8px 6px;font-size:11px;color:#555;text-align:center;white-space:nowrap;">'
            f'{_e(_t(o.get("fecha_cierre", "—"), 16))}</td>'
            f'<td style="padding:8px 6px;text-align:center;">'
            f'{_score_dot(o.get("score_pertinencia", 1))}</td>'
            f'<td style="padding:8px 10px 8px 6px;text-align:center;">'
            f'{_estado_badge(o.get("estado", ""))}</td>'
            f'</tr>'
        )
    if len(opps) > max_rows:
        extra = len(opps) - max_rows
        rows.append(
            '<tr style="background:#f5f5f5;"><td colspan="6" style="padding:8px 10px;'
            f'text-align:center;font-size:11px;color:#888;font-style:italic;">'
            f'… y {extra} oportunidad(es) más — ver informe adjunto</td></tr>'
        )
    return "\n".join(rows)


def _urgentes_row(urgentes: int) -> str:
    """Banner de alerta cuando hay oportunidades con cierre próximo."""
    if not urgentes:
        return ""
    return (
        '<tr><td style="padding:12px 20px 0;">'
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#FFF8E1;border-left:4px solid #FF8F00;border-radius:0 4px 4px 0;">'
        '<tr><td style="padding:10px 14px;">'
        f'<span style="color:#E65100;font-weight:bold;font-size:12px;">'
        f'&#9889; {urgentes} oportunidad(es) con cierre en los próximos 15 días '
        f'— acción inmediata requerida</span>'
        '</td></tr></table></td></tr>'
    )


# ── Construcción del cuerpo HTML ──────────────────────────────────────────────

def build_html_body(stats: dict, firma: str, opps: list[dict],
                    fecha: str, resumen: str = "") -> str:
    vigentes     = stats.get("vigentes", len(opps))
    nuevas       = stats.get("nuevas", 0)
    prioritarias = stats.get("prioritarias", 0)
    verificar    = stats.get("verificar", 0)
    urgentes     = stats.get("urgentes", 0)

    # Resumen ejecutivo: primer párrafo, máx 400 caracteres
    resumen_html = ""
    if resumen:
        primer_parrafo = resumen.split("\n\n")[0] if "\n\n" in resumen else resumen
        resumen_html = (
            '<tr><td style="padding:0 20px 20px;">'
            '<h2 style="margin:0 0 8px;font-size:12px;color:#1B5E20;text-transform:uppercase;'
            'letter-spacing:0.5px;border-bottom:2px solid #C8E6C9;padding-bottom:6px;">'
            'Resumen ejecutivo</h2>'
            f'<p style="margin:0;font-size:12px;color:#444;line-height:1.7;">{_e(_t(primer_parrafo, 420))}</p>'
            '<p style="margin:8px 0 0;font-size:11px;color:#999;font-style:italic;">'
            'Análisis completo en el informe PDF adjunto.</p>'
            '</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ECEFF1;font-family:Arial,Helvetica,sans-serif;color:#333333;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#ECEFF1;">
<tr><td align="center" style="padding:24px 12px;">

  <table width="600" cellpadding="0" cellspacing="0"
         style="background:#ffffff;border-radius:10px;overflow:hidden;max-width:600px;">

    <!-- HEADER -->
    <tr>
      <td style="background:#1B5E20;padding:24px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <p style="margin:0;color:#A5D6A7;font-size:10px;text-transform:uppercase;letter-spacing:2px;">
                Projectability / Soluciones PAL
              </p>
              <h1 style="margin:6px 0 4px;color:#ffffff;font-size:20px;font-weight:bold;line-height:1.2;">
                Radar de Atracción de Recursos
              </h1>
              <p style="margin:0;color:#C8E6C9;font-size:12px;">
                Visión Circular ANDI &nbsp;·&nbsp; {_e(fecha)}
              </p>
            </td>
            <td align="right" valign="middle" style="padding-left:16px;white-space:nowrap;">
              <span style="background:rgba(255,255,255,0.18);color:#ffffff;padding:6px 14px;
                           border-radius:20px;font-size:11px;font-weight:bold;
                           border:1px solid rgba(255,255,255,0.3);">
                INFORME DIARIO
              </span>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- KPI CARDS -->
    <tr>
      <td style="padding:20px 16px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td width="25%" style="padding:0 4px 0 0;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#E8F5E9;border-radius:8px;border:1px solid #C8E6C9;">
                <tr><td style="padding:14px 8px;text-align:center;">
                  <div style="font-size:30px;font-weight:bold;color:#1B5E20;line-height:1;">{vigentes}</div>
                  <div style="font-size:10px;color:#388E3C;text-transform:uppercase;
                               font-weight:bold;margin-top:5px;letter-spacing:0.5px;">Vigentes</div>
                </td></tr>
              </table>
            </td>
            <td width="25%" style="padding:0 4px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#E3F2FD;border-radius:8px;border:1px solid #BBDEFB;">
                <tr><td style="padding:14px 8px;text-align:center;">
                  <div style="font-size:30px;font-weight:bold;color:#1565C0;line-height:1;">{nuevas}</div>
                  <div style="font-size:10px;color:#1976D2;text-transform:uppercase;
                               font-weight:bold;margin-top:5px;letter-spacing:0.5px;">Nuevas hoy</div>
                </td></tr>
              </table>
            </td>
            <td width="25%" style="padding:0 4px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#FFF8E1;border-radius:8px;border:1px solid #FFE082;">
                <tr><td style="padding:14px 8px;text-align:center;">
                  <div style="font-size:30px;font-weight:bold;color:#E65100;line-height:1;">{prioritarias}</div>
                  <div style="font-size:10px;color:#F57C00;text-transform:uppercase;
                               font-weight:bold;margin-top:5px;letter-spacing:0.5px;">Prioritarias</div>
                </td></tr>
              </table>
            </td>
            <td width="25%" style="padding:0 0 0 4px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#FCE4EC;border-radius:8px;border:1px solid #F8BBD9;">
                <tr><td style="padding:14px 8px;text-align:center;">
                  <div style="font-size:30px;font-weight:bold;color:#880E4F;line-height:1;">{verificar}</div>
                  <div style="font-size:10px;color:#C2185B;text-transform:uppercase;
                               font-weight:bold;margin-top:5px;letter-spacing:0.5px;">Verificar</div>
                </td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    {_urgentes_row(urgentes)}

    <!-- TABLA PRIORIZADA -->
    <tr>
      <td style="padding:20px 20px 8px;">
        <h2 style="margin:0 0 10px;font-size:12px;color:#1B5E20;text-transform:uppercase;
                   letter-spacing:0.5px;border-bottom:2px solid #C8E6C9;padding-bottom:6px;">
          Oportunidades priorizadas
        </h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr style="background:#2E7D32;color:#ffffff;">
            <th style="padding:8px 6px 8px 10px;text-align:left;font-size:11px;
                        font-weight:bold;width:20px;">#</th>
            <th style="padding:8px 6px;text-align:left;font-size:11px;font-weight:bold;">Oportunidad</th>
            <th style="padding:8px 6px;text-align:left;font-size:11px;font-weight:bold;">Entidad</th>
            <th style="padding:8px 6px;text-align:center;font-size:11px;
                        font-weight:bold;white-space:nowrap;">Cierre</th>
            <th style="padding:8px 6px;text-align:center;font-size:11px;font-weight:bold;">Per</th>
            <th style="padding:8px 10px 8px 6px;text-align:center;font-size:11px;font-weight:bold;">Estado</th>
          </tr>
          {_opp_rows(opps)}
        </table>
      </td>
    </tr>

    {resumen_html}

    <!-- FOOTER -->
    <tr>
      <td style="background:#F5F7F5;padding:16px 20px;border-top:1px solid #E0E0E0;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <p style="margin:0;font-size:11px;color:#777;">
                Informe completo (PDF) y base de datos actualizada (Excel) adjuntos.
              </p>
            </td>
            <td align="right">
              <p style="margin:0;font-size:11px;color:#888;white-space:nowrap;">
                <strong style="color:#1B5E20;">{_e(firma)}</strong>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


# ── Texto plano (fallback para clientes sin HTML) ─────────────────────────────

def build_body(stats: dict, firma: str) -> str:
    return f"""Hola equipo,

Comparto el informe diario de oportunidades de atracción de recursos identificadas para Visión Circular ANDI.

Resumen del día:
  - Oportunidades vigentes en seguimiento: {stats.get('vigentes', 0)}
  - Nuevas identificadas hoy:              {stats.get('nuevas', 0)}
  - Prioritarias (pertinencia alta):       {stats.get('prioritarias', 0)}
  - Requieren verificación manual:         {stats.get('verificar', 0)}
  - Con cierre próximo (<15 días):         {stats.get('urgentes', 0)}

Recomiendo revisar especialmente las oportunidades con urgencia alta.
Informe completo (PDF) y base de datos (Excel) adjuntos.

Saludos,
{firma}
"""


# ── Construcción del mensaje MIME ─────────────────────────────────────────────

def _attach(msg: MIMEMultipart, path: Path | None) -> None:
    if not path or not Path(path).exists():
        return
    path = Path(path)
    ctype, _ = mimetypes.guess_type(path.name)
    maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
    part = MIMEBase(maintype, subtype)
    part.set_payload(path.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=path.name)
    msg.attach(part)


def build_message(stats: dict, config: dict, attachments: list[Path], today: str,
                  sender: str, recipients: list[str],
                  opps: list[dict] | None = None,
                  resumen: str = "") -> MIMEMultipart:
    correo = config.get("correo", {})
    subject = correo.get("asunto", "Informe diario – Visión Circular ANDI – {fecha}").format(fecha=today)
    firma = correo.get("firma", "Projectability / Soluciones PAL")
    opps = opps or []

    # Estructura MIME: mixed > alternative (plain + html) + adjuntos
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients) if recipients else sender

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_body(stats, firma), "plain", "utf-8"))
    alt.attach(MIMEText(build_html_body(stats, firma, opps, today, resumen), "html", "utf-8"))
    msg.attach(alt)

    for att in attachments:
        _attach(msg, att)
    return msg


# ── Envío / guardado ──────────────────────────────────────────────────────────

def _create_draft_imap(msg: MIMEMultipart, user: str, password: str,
                       logger: logging.Logger) -> bool:
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        imap.login(user, password)
        raw = msg.as_bytes()
        stamp = imaplib.Time2Internaldate(time.time())
        last_err = None
        for folder in _DRAFT_FOLDERS:
            try:
                typ, _ = imap.append(folder, r"(\Draft)", stamp, raw)
                if typ == "OK":
                    logger.info("Borrador creado en Gmail (carpeta %s). Revísalo antes de enviar.", folder)
                    return True
            except Exception as e:  # noqa: BLE001
                last_err = e
        logger.error("No se pudo crear el borrador en ninguna carpeta. Último error: %s", last_err)
        return False
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _send_smtp(msg: MIMEMultipart, user: str, password: str, recipients: list[str],
               logger: logging.Logger) -> bool:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.sendmail(user, recipients or [user], msg.as_string())
    logger.info("Correo enviado a: %s", ", ".join(recipients) if recipients else user)
    return True


def _dry_run(msg: MIMEMultipart, config: dict, today: str, logger: logging.Logger) -> bool:
    out = Path(config["rutas"]["output"]) / f"correo_borrador_{today}.eml"
    out.write_bytes(msg.as_bytes())
    logger.warning("Modo DRY_RUN: correo NO enviado. Guardado para revisión en %s", out)
    return True


def handle_email(stats: dict, config: dict, attachments: list[Path],
                 logger: logging.Logger, today: str | None = None,
                 force_dry_run: bool = False,
                 opps: list[dict] | None = None,
                 resumen: str = "") -> bool:
    today = today or date.today().isoformat()
    modo = "dry_run" if force_dry_run else config.get("correo", {}).get("modo", "borrador_imap")

    sender = get_env("GMAIL_SENDER_EMAIL") or get_env("GMAIL_USER") or "no-reply@example.com"
    recipients = [e.strip() for e in (get_env("TEAM_EMAILS") or "").split(",") if e.strip()]

    atts: list[Path] = []
    if config.get("correo", {}).get("adjuntar_informe", True):
        atts += [a for a in attachments if a and Path(a).suffix in (".md", ".pdf")]
    if config.get("correo", {}).get("adjuntar_excel", True):
        atts += [a for a in attachments if a and Path(a).suffix == ".xlsx"]

    msg = build_message(stats, config, atts, today, sender, recipients,
                        opps=opps or [], resumen=resumen)

    if modo == "dry_run":
        return _dry_run(msg, config, today, logger)

    password = get_env("GMAIL_APP_PASSWORD")
    if not sender or sender == "no-reply@example.com" or not password:
        logger.warning("Faltan GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD. Cambiando a DRY_RUN.")
        return _dry_run(msg, config, today, logger)

    if modo == "envio_smtp":
        return _send_smtp(msg, sender, password, recipients, logger)
    return _create_draft_imap(msg, sender, password, logger)
