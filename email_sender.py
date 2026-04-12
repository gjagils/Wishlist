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


def _get_owner_email(item: dict) -> Optional[str]:
    """Haal e-mailadres van de item-eigenaar op."""
    user_id = item.get("user_id")
    if user_id:
        user = db.get_user_by_id(user_id)
        if user and user.get("email"):
            return user["email"]
    return None


def _get_admin_emails() -> List[str]:
    """Haal alle admin e-mailadressen op."""
    return [a["email"] for a in db.get_admin_users() if a.get("email")]


def _is_admin_item(item: dict) -> bool:
    """Check of het item van een admin is."""
    user_id = item.get("user_id")
    if not user_id:
        return True  # Geen user_id = legacy admin item
    user = db.get_user_by_id(user_id)
    return user and user.get("role") == "admin"


# Default e-mail templates. Placeholders: {title}, {author}, {shelf}
DEFAULT_FOUND_SUBJECT = "📖 {title} - {author} wordt gedownload"
DEFAULT_FOUND_BODY = """Hoi!

Goed nieuws — "{title}" van {author} is gevonden en wordt nu gedownload.

Je hoeft niks te doen, je krijgt nog een mailtje als het klaar staat.

Groetjes,
Boekjes van Gerd-Jan
https://wishlist.gerdjan.nl"""

DEFAULT_SHELVED_SUBJECT = "📚 {title} staat klaar!"
DEFAULT_SHELVED_BODY = """Hoi!

"{title}" van {author} staat klaar op je boekenplank ({shelf})!

Open Calibre-Web om het boek te lezen:
https://boekjes.gerdjan.nl

Of ga naar je Wishlist:
https://wishlist.gerdjan.nl

Veel leesplezier!

Groetjes,
Boekjes van Gerd-Jan"""


def _render_template(template: str, item: dict) -> str:
    """Vervang placeholders in een template."""
    return template.format(
        title=item.get("title", "Onbekend"),
        author=item.get("author", "Onbekend"),
        shelf=item.get("shelf_name", ""),
    )


def _send_with_admin_copy(item: dict, subject: str, body: str) -> None:
    """Stuur mail naar eigenaar, en een kopie naar admins met 'Admin kopie:' prefix."""
    owner_email = _get_owner_email(item)
    admin_emails = _get_admin_emails()
    is_admin = _is_admin_item(item)

    # Mail naar eigenaar
    if owner_email:
        send_notification([owner_email], subject, body)

    # Kopie naar admins (alleen als eigenaar geen admin is)
    if not is_admin and admin_emails:
        admin_subject = f"Admin kopie: {subject}"
        send_notification(admin_emails, admin_subject, body)
    elif is_admin and admin_emails and not owner_email:
        # Admin item zonder eigenaar-email: stuur naar alle admins
        send_notification(admin_emails, subject, body)


def notify_item_found(item: dict) -> None:
    """Stuur notificatie dat een boek gevonden is."""
    subject_tpl = db.get_setting("email_found_subject", DEFAULT_FOUND_SUBJECT)
    body_tpl = db.get_setting("email_found_body", DEFAULT_FOUND_BODY)

    _send_with_admin_copy(item, _render_template(subject_tpl, item),
                          _render_template(body_tpl, item))


def notify_item_shelved(item: dict) -> None:
    """Stuur notificatie dat een boek op de plank gezet is."""
    subject_tpl = db.get_setting("email_shelved_subject", DEFAULT_SHELVED_SUBJECT)
    body_tpl = db.get_setting("email_shelved_body", DEFAULT_SHELVED_BODY)

    _send_with_admin_copy(item, _render_template(subject_tpl, item),
                          _render_template(body_tpl, item))
