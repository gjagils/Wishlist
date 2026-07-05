#!/usr/bin/env python3
"""
Email monitor voor Wishlist via Gmail IMAP.
Checkt mailbox voor wishlist items en voegt ze toe aan database.

Setup Gmail:
1. Enable IMAP in Gmail settings
2. Enable 2-factor authentication
3. Create App Password: https://myaccount.google.com/apppasswords
4. Use App Password in EMAIL_PASSWORD env var
"""
import os
import time
import imaplib
import email
import urllib.parse
import difflib
from email.header import decode_header
from email.utils import parseaddr
import re
import requests
from typing import List, Tuple, Optional, Dict

import database as db
import email_sender

# Config
IMAP_SERVER = os.environ.get('EMAIL_IMAP_SERVER', 'imap.gmail.com')
IMAP_PORT = int(os.environ.get('EMAIL_IMAP_PORT', '993'))
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
CHECK_INTERVAL = int(os.environ.get('EMAIL_CHECK_INTERVAL', '300'))  # 5 minuten

# Mailbox settings
INBOX_FOLDER = os.environ.get('EMAIL_INBOX_FOLDER', 'INBOX')
PROCESSED_FOLDER = os.environ.get('EMAIL_PROCESSED_FOLDER', 'Wishlist/Processed')


def get_allowed_senders() -> List[str]:
    """
    Haal de toegestane afzenders op. Beheerbaar via het admin panel
    (opgeslagen in de settings-tabel); valt terug op EMAIL_ALLOWED_SENDERS
    als er nog niets via het admin panel is ingesteld.
    """
    raw = db.get_setting('email_allowed_senders', os.environ.get('EMAIL_ALLOWED_SENDERS', ''))
    return [s.strip() for s in (raw or '').split(',') if s.strip()]


def decode_header_value(header_value: str) -> str:
    """Decode email header met charset support."""
    if not header_value:
        return ''

    decoded_parts = decode_header(header_value)
    result = []

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(encoding or 'utf-8', errors='ignore'))
            except Exception:
                result.append(part.decode('utf-8', errors='ignore'))
        else:
            result.append(str(part))

    return ''.join(result)


def _normalize_for_match(text: str) -> str:
    """Reduceer tot kale alfanumerieke tekens voor tolerante vergelijking."""
    return re.sub(r'[^a-z0-9]+', '', text.lower())


def _similar(a: str, b: str, threshold: float = 0.75) -> bool:
    """Tolerante vergelijking: substring, of voldoende gelijkend (typefouten)."""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def _google_books_lookup(guess_title: str, guess_author: str) -> Optional[Dict[str, str]]:
    """
    Zoek op Google Books met een titel/auteur-gok. Geeft de canonieke titel en
    auteur terug (met correcte spelling) als er een overtuigende match is,
    anders None. Geen API key nodig (zelfde aanpak als de cover-lookup).
    """
    try:
        query = f"intitle:{urllib.parse.quote(guess_title)}+inauthor:{urllib.parse.quote(guess_author)}"
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=5&fields=items(volumeInfo(title,authors))"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return None

        norm_title_guess = _normalize_for_match(guess_title)
        norm_author_guess = _normalize_for_match(guess_author)

        for item in resp.json().get("items", []):
            vol = item.get("volumeInfo", {})
            result_title = vol.get("title", "")
            result_authors = vol.get("authors", [])
            if not result_title or not result_authors:
                continue

            norm_result_title = _normalize_for_match(result_title)
            title_ok = _similar(norm_title_guess, norm_result_title)
            author_ok = any(_similar(norm_author_guess, _normalize_for_match(a)) for a in result_authors)

            if title_ok and author_ok:
                return {"title": result_title, "author": result_authors[0]}

    except Exception as e:
        print(f"   \u26A0\uFE0F Google Books lookup mislukt: {e}")

    return None


def resolve_author_title(part_a: str, part_b: str) -> Tuple[str, str]:
    """
    Bepaal welk deel de auteur is en welk de titel, en corrigeer typefouten
    via Google Books. Probeert beide volgordes.

    Als geen van beide een overtuigende match oplevert, wordt aangenomen dat
    het eerste deel de auteur is (de gebruikelijke volgorde) \u2014 de tekst zoals
    getypt blijft dan gewoon staan.
    """
    match = _google_books_lookup(guess_title=part_b, guess_author=part_a)
    if match:
        return match["author"], match["title"]

    match = _google_books_lookup(guess_title=part_a, guess_author=part_b)
    if match:
        return match["author"], match["title"]

    print(f"   \u26A0\uFE0F Kon '{part_a}' / '{part_b}' niet bevestigen via Google Books, "
          f"aanname: '{part_a}' = auteur, '{part_b}' = titel")
    return part_a, part_b


def _parse_request_line(line: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Parse een regel als 'deel - deel', met optioneel '> plank' erachter.
    Aanhalingstekens rond een van beide delen zijn toegestaan maar niet
    verplicht; welk deel auteur/titel is wordt later bepaald.
    """
    shelf = None
    shelf_match = re.search(r'>\s*(.+)$', line)
    if shelf_match:
        shelf = shelf_match.group(1).strip() or None
        line = line[:shelf_match.start()].strip()

    parts = re.split(r'\s+-\s+', line, maxsplit=1)
    if len(parts) != 2:
        return None

    part_a = parts[0].strip(' \t"\u201C\u201D')
    part_b = parts[1].strip(' \t"\u201C\u201D')

    if not part_a or not part_b:
        return None

    return part_a, part_b, shelf


def extract_wishlist_items(subject: str, body: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Extract wishlist items uit email subject of body.

    Formaat: 'deel - deel', optioneel gevolgd door '> boekenplank'.
    Volgorde (auteur/titel) en aanhalingstekens maken niet uit \u2014 Google Books
    bepaalt welk deel de auteur is en welk de titel, en corrigeert typefouten.

    Voorbeelden die allemaal werken:
    - MJ Arlidge - Uit de as
    - Uit de as - MJ Arlidge
    - MJ Arlidge - "Uit de as" > Kobo GJ
    - Wishlist: Arlige - uit de As  (typefout, wordt gecorrigeerd)

    Returns: List van (author, title, shelf_name) tuples
    """
    items = []
    seen = set()

    lines = [subject] + body.split('\n')

    for line in lines:
        line = line.strip()

        # Skip lege regels en reply-quotes
        if not line or line.startswith('>'):
            continue

        # Verwijder prefixes
        line = re.sub(r'^(wishlist|voeg toe|add):\s*', '', line, flags=re.IGNORECASE)

        parsed = _parse_request_line(line)
        if not parsed:
            continue

        part_a, part_b, shelf = parsed
        author, title = resolve_author_title(part_a, part_b)

        key = (author.strip().lower(), title.strip().lower())
        if key in seen:
            continue
        seen.add(key)

        items.append((author, title, shelf))

    return items


def get_email_body(msg) -> str:
    """Haal email body op (plain text)."""
    body = ''

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                try:
                    charset = part.get_content_charset() or 'utf-8'
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(charset, errors='ignore')
                        break
                except Exception as e:
                    print(f"Fout bij lezen email body: {e}")
    else:
        try:
            charset = msg.get_content_charset() or 'utf-8'
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors='ignore')
        except Exception as e:
            print(f"Fout bij lezen email body: {e}")

    return body


def is_sender_allowed(sender: str) -> bool:
    """Check of sender toegestaan is."""
    allowed_senders = get_allowed_senders()
    if not allowed_senders:
        # Geen whitelist = alle senders toegestaan
        return True

    sender_lower = sender.lower()
    for allowed in allowed_senders:
        if allowed.lower() in sender_lower:
            return True

    return False


def process_email(mail: imaplib.IMAP4_SSL, email_id: bytes) -> int:
    """
    Verwerk een enkele email voor wishlist items.
    Returns: aantal toegevoegde items
    """
    added_count = 0

    try:
        # Haal email op
        _, msg_data = mail.fetch(email_id, '(RFC822)')
        email_body = msg_data[0][1]
        msg = email.message_from_bytes(email_body)

        # Parse headers
        from_header = decode_header_value(msg.get('From', ''))
        _, sender_email = parseaddr(from_header)
        sender_email = sender_email.lower()
        subject = decode_header_value(msg.get('Subject', ''))
        body = get_email_body(msg)

        print(f"\n📧 Email van: {from_header}")
        print(f"   Subject: {subject}")

        # Extract items (ook van niet-toegestane afzenders, om te kunnen rapporteren)
        items = extract_wishlist_items(subject, body)

        if not items:
            print("   Geen wishlist items gevonden")
            return 0

        # Check sender
        if not is_sender_allowed(from_header):
            print(f"   ⚠️ Sender niet toegestaan: {from_header} — admin geïnformeerd, niet toegevoegd")
            try:
                email_sender.notify_unauthorized_request(sender_email, items)
            except Exception as e:
                print(f"   ✗ Fout bij versturen admin-melding: {e}")
            return 0

        # Voeg items toe
        for author, title, shelf_name in items:
            try:
                item_id = db.add_wishlist_item(
                    author=author,
                    title=title,
                    added_via='email',
                    shelf_name=shelf_name,
                    requester_email=sender_email
                )
                shelf_msg = f" → {shelf_name}" if shelf_name else ""
                print(f"   ✓ Toegevoegd: {author} - \"{title}\"{shelf_msg}")
                added_count += 1

                try:
                    email_sender.notify_item_requested(db.get_wishlist_item(item_id))
                except Exception as e:
                    print(f"   ✗ Fout bij versturen bevestiging: {e}")

            except ValueError as e:
                # Duplicaat
                print(f"   ⊗ Al in lijst: {author} - \"{title}\"")
            except Exception as e:
                print(f"   ✗ Fout bij toevoegen: {e}")

    except Exception as e:
        print(f"Fout bij verwerken email: {e}")

    return added_count


def check_mailbox() -> int:
    """
    Check Gmail IMAP mailbox voor nieuwe wishlist emails.
    Returns: aantal verwerkte emails
    """
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("⚠️ EMAIL_ADDRESS of EMAIL_PASSWORD niet ingesteld")
        return 0

    processed_count = 0

    try:
        # Verbind met Gmail IMAP
        print(f"📬 Verbinden met {IMAP_SERVER}...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        print(f"✓ Ingelogd als {EMAIL_ADDRESS}")

        # Selecteer inbox
        status, messages = mail.select(INBOX_FOLDER)
        if status != 'OK':
            print(f"Kon {INBOX_FOLDER} niet openen")
            return 0

        # Zoek ongelezen emails met "wishlist" in subject
        # Of alle ongelezen emails
        search_criteria = '(UNSEEN)'
        # Optioneel: alleen emails met "wishlist" in subject
        # search_criteria = '(UNSEEN SUBJECT "wishlist")'

        status, messages = mail.search(None, search_criteria)
        if status != 'OK':
            print("Zoeken mislukt")
            return 0

        email_ids = messages[0].split()
        print(f"📨 {len(email_ids)} ongelezen email(s) gevonden")

        if not email_ids:
            return 0

        # Verwerk elke email
        for email_id in email_ids:
            added = process_email(mail, email_id)

            # Altijd markeren als gelezen zodra verwerkt, anders wordt een
            # niet-toegestane of onherkende email bij elke check opnieuw
            # opgepakt (en stuurt bv. steeds opnieuw een admin-melding).
            mail.store(email_id, '+FLAGS', '\\Seen')

            if added > 0:
                processed_count += 1

                # Optioneel: verplaats naar processed folder
                # (hiervoor moet je de folder eerst aanmaken in Gmail)
                try:
                    if PROCESSED_FOLDER and PROCESSED_FOLDER != INBOX_FOLDER:
                        mail.copy(email_id, PROCESSED_FOLDER)
                        mail.store(email_id, '+FLAGS', '\\Deleted')
                except Exception as e:
                    print(f"   Kon niet verplaatsen naar {PROCESSED_FOLDER}: {e}")

        # Cleanup
        if processed_count > 0:
            mail.expunge()

        mail.close()
        mail.logout()

    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP fout: {e}")
        print("   Check of IMAP enabled is en App Password gebruikt wordt")
    except Exception as e:
        print(f"❌ Fout bij checken mailbox: {e}")

    return processed_count


def main():
    """Main loop voor email monitoring."""
    print("📧 Email Monitor gestart")
    print(f"   Server: {IMAP_SERVER}")
    print(f"   Account: {EMAIL_ADDRESS}")
    print(f"   Interval: {CHECK_INTERVAL}s")

    allowed_senders = get_allowed_senders()
    if allowed_senders:
        print(f"   Whitelist: {', '.join(allowed_senders)} (via admin panel of EMAIL_ALLOWED_SENDERS)")
    else:
        print("   ⚠️ Geen sender whitelist - alle emails worden geaccepteerd")

    while True:
        try:
            processed = check_mailbox()
            if processed > 0:
                print(f"✓ {processed} email(s) verwerkt\n")
        except Exception as e:
            print(f"❌ Fout in main loop: {e}")

        print(f"Volgende check over {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
