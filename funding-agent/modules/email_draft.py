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

# Carpetas de borradores candidatas (cuenta en inglés / español)
_DRAFT_FOLDERS = ['"[Gmail]/Drafts"', '"[Gmail]/Borradores"', "Drafts", "Borradores"]


def build_body(stats: dict, firma: str) -> str:
    return f"""Hola equipo,

Comparto el informe diario de oportunidades de atracción de recursos identificadas para Visión Circular ANDI, con énfasis en economía circular, reciclaje, sostenibilidad, innovación, cooperación internacional y financiamiento climático.

En esta revisión se priorizan las oportunidades según pertinencia estratégica, urgencia de aplicación y probabilidad de elegibilidad para Colombia o para una postulación mediante alianzas.

Resumen del día:

* Número de oportunidades nuevas identificadas: {stats.get('nuevas', 0)}
* Número de oportunidades prioritarias: {stats.get('prioritarias', 0)}
* Número de oportunidades que requieren verificación: {stats.get('verificar', 0)}
* Oportunidades con cierre próximo: {stats.get('urgentes', 0)}

Recomiendo revisar especialmente las oportunidades clasificadas con urgencia alta, ya que podrían requerir decisión rápida, contacto con aliados o preparación temprana de documentos.

Quedo atento para definir cuáles oportunidades avanzamos a ficha técnica, validación con aliados o estructuración preliminar.

Saludos,

{firma}
"""


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
                  sender: str, recipients: list[str]) -> MIMEMultipart:
    correo = config.get("correo", {})
    subject = correo.get("asunto", "Informe diario – Visión Circular ANDI – {fecha}").format(fecha=today)
    firma = correo.get("firma", "Projectability / Soluciones PAL")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients) if recipients else sender
    msg.attach(MIMEText(build_body(stats, firma), "plain", "utf-8"))

    for att in attachments:
        _attach(msg, att)
    return msg


def _create_draft_imap(msg: MIMEMultipart, user: str, password: str, logger: logging.Logger) -> bool:
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


def handle_email(stats: dict, config: dict, attachments: list[Path], logger: logging.Logger,
                 today: str | None = None, force_dry_run: bool = False) -> bool:
    today = today or date.today().isoformat()
    modo = "dry_run" if force_dry_run else config.get("correo", {}).get("modo", "borrador_imap")

    sender = get_env("GMAIL_SENDER_EMAIL") or get_env("GMAIL_USER") or "no-reply@example.com"
    recipients = [e.strip() for e in (get_env("TEAM_EMAILS") or "").split(",") if e.strip()]

    atts = []
    if config.get("correo", {}).get("adjuntar_informe", True):
        atts += [a for a in attachments if a and Path(a).suffix in (".md", ".pdf")]
    if config.get("correo", {}).get("adjuntar_excel", True):
        atts += [a for a in attachments if a and Path(a).suffix == ".xlsx"]

    msg = build_message(stats, config, atts, today, sender, recipients)

    if modo == "dry_run":
        return _dry_run(msg, config, today, logger)

    password = get_env("GMAIL_APP_PASSWORD")
    if not sender or sender == "no-reply@example.com" or not password:
        logger.warning("Faltan GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD. Cambiando a DRY_RUN.")
        return _dry_run(msg, config, today, logger)

    if modo == "envio_smtp":
        return _send_smtp(msg, sender, password, recipients, logger)
    return _create_draft_imap(msg, sender, password, logger)
