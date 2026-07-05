#!/usr/bin/env python3
"""
SMTP email module voor uitgaande notificaties.
Stuurt meldingen wanneer boeken gevonden of op de plank gezet worden.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import List, Optional

import database as db

# SMTP configuratie — valt terug op bestaande EMAIL_* vars als SMTP_* niet gezet zijn
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "") or os.environ.get("EMAIL_ADDRESS", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "") or os.environ.get("EMAIL_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or os.environ.get("EMAIL_ADDRESS", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"


def is_configured() -> bool:
    """Check of SMTP geconfigureerd is."""
    return bool(SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM)


def send_notification(to_emails: List[str], subject: str, body: str) -> bool:
    """Verstuur e-mail notificatie via SMTP."""
    if not is_configured() or not to_emails:
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM)) if SMTP_FROM_NAME else SMTP_FROM
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
    """Haal e-mailadres van de item-eigenaar op (account, of anders de aanvrager per e-mail)."""
    user_id = item.get("user_id")
    if user_id:
        user = db.get_user_by_id(user_id)
        if user and user.get("email"):
            return user["email"]
    return item.get("requester_email") or None


def _get_admin_emails() -> List[str]:
    """Haal alle admin e-mailadressen op."""
    return [a["email"] for a in db.get_admin_users() if a.get("email")]


def _is_admin_item(item: dict) -> bool:
    """Check of het item van een admin is (dus geen aparte admin-kopie nodig)."""
    user_id = item.get("user_id")
    if not user_id:
        # Geen user_id: legacy admin item, tenzij het een e-mail aanvraag van
        # iemand zonder account is — die moet wél een admin-kopie krijgen.
        return item.get("added_via") != "email"
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


DEFAULT_DONE_SUBJECT = "📚 {title} - {author} is beschikbaar!"
DEFAULT_DONE_BODY = """Hoi!

"{title}" van {author} staat klaar in de bibliotheek!

Open Calibre-Web om het boek te lezen:
https://boekjes.gerdjan.nl

Groetjes,
Boekjes van Gerd-Jan"""


def notify_item_done(item: dict) -> None:
    """Stuur notificatie dat een boek beschikbaar is (geen boekenplank ingesteld)."""
    subject_tpl = db.get_setting("email_done_subject", DEFAULT_DONE_SUBJECT)
    body_tpl = db.get_setting("email_done_body", DEFAULT_DONE_BODY)

    _send_with_admin_copy(item, _render_template(subject_tpl, item),
                          _render_template(body_tpl, item))


DEFAULT_REQUESTED_SUBJECT = "📬 Aanvraag ontvangen: {title} - {author}"
DEFAULT_REQUESTED_BODY = """Hoi!

We hebben je aanvraag voor "{title}" van {author} ontvangen en toegevoegd aan de wishlist.

Je krijgt een mailtje zodra het boek gevonden is.

Groetjes,
Boekjes van Gerd-Jan"""


def notify_item_requested(item: dict) -> None:
    """Stuur bevestiging dat een aanvraag (bv. per e-mail) ontvangen en toegevoegd is."""
    subject_tpl = db.get_setting("email_requested_subject", DEFAULT_REQUESTED_SUBJECT)
    body_tpl = db.get_setting("email_requested_body", DEFAULT_REQUESTED_BODY)

    _send_with_admin_copy(item, _render_template(subject_tpl, item),
                          _render_template(body_tpl, item))


def notify_unauthorized_request(sender_email: str, items: List[tuple]) -> None:
    """
    Stuur alleen de admins een melding van een wishlist-aanvraag per e-mail
    van een afzender die niet op de EMAIL_ALLOWED_SENDERS-lijst staat.
    Het item wordt NIET toegevoegd — de admin beslist of het alsnog moet.
    """
    admin_emails = _get_admin_emails()
    if not admin_emails:
        return

    lines = "\n".join(
        f"- {author} - \"{title}\"" + (f" > {shelf}" if shelf else "")
        for author, title, shelf in items
    )

    subject = f"⚠️ Wishlist-aanvraag van ongeautoriseerd adres: {sender_email}"
    body = f"""Er kwam een wishlist-aanvraag binnen per e-mail van een adres dat niet op de toegestane lijst (EMAIL_ALLOWED_SENDERS) staat.

Afzender: {sender_email}

Aanvraag:
{lines}

Dit is NIET toegevoegd aan de wishlist. Voeg {sender_email} toe aan EMAIL_ALLOWED_SENDERS als je dit wilt toestaan, of voeg het boek zelf handmatig toe via de Wishlist-app."""

    send_notification(admin_emails, subject, body)
