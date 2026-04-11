#!/usr/bin/env python3
"""
SMTP email module voor uitgaande notificaties.
Stuurt meldingen wanneer boeken gevonden of op de plank gezet worden.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

import database as db

# SMTP configuratie — valt terug op bestaande EMAIL_* vars als SMTP_* niet gezet zijn
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "") or os.environ.get("EMAIL_ADDRESS", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "") or os.environ.get("EMAIL_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or os.environ.get("EMAIL_ADDRESS", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"


def is_configured() -> bool:
    """Check of SMTP geconfigureerd is."""
    return bool(SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM)


def send_notification(to_emails: List[str], subject: str, body: str) -> bool:
    """Verstuur e-mail notificatie via SMTP."""
    if not is_configured() or not to_emails:
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)

        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, to_emails, msg.as_string())
        server.quit()
        return True

    except Exception as e:
        print(f"[EMAIL] Verzenden mislukt: {e}")
        return False


def _get_notification_emails(item: dict) -> List[str]:
    """Verzamel e-mailadressen voor notificatie: item-eigenaar + alle admins."""
    emails = set()

    # Admin e-mails
    for admin in db.get_admin_users():
        if admin.get("email"):
            emails.add(admin["email"])

    # Item-eigenaar e-mail
    user_id = item.get("user_id")
    if user_id:
        user = db.get_user_by_id(user_id)
        if user and user.get("email"):
            emails.add(user["email"])

    return list(emails)


def notify_item_found(item: dict) -> None:
    """Stuur notificatie dat een boek gevonden is in Spotweb."""
    emails = _get_notification_emails(item)
    if not emails:
        return

    author = item.get("author", "Onbekend")
    title = item.get("title", "Onbekend")
    shelf = item.get("shelf_name", "")

    subject = f"Boek gevonden: {author} - {title}"
    body = f"""Goed nieuws! Het boek is gevonden op Spotweb en wordt gedownload.

Auteur: {author}
Titel: {title}
{f"Boekenplank: {shelf}" if shelf else ""}

Het boek wordt nu gedownload via SABnzbd.
{"Zodra het geimporteerd is in Calibre wordt het op de plank gezet." if shelf else ""}

— Wishlist"""

    send_notification(emails, subject, body)


def notify_item_shelved(item: dict) -> None:
    """Stuur notificatie dat een boek op de plank gezet is."""
    emails = _get_notification_emails(item)
    if not emails:
        return

    author = item.get("author", "Onbekend")
    title = item.get("title", "Onbekend")
    shelf = item.get("shelf_name", "")

    subject = f"Boek op plank: {author} - {title}"
    body = f"""Het boek is succesvol geimporteerd en op de boekenplank gezet!

Auteur: {author}
Titel: {title}
Boekenplank: {shelf}

Je kunt het boek nu lezen in Calibre-Web.

— Wishlist"""

    send_notification(emails, subject, body)
