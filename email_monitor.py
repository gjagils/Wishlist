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
from email.header import decode_header
import re
from typing import List, Tuple, Optional

import database as db

# Config
IMAP_SERVER = os.environ.get('EMAIL_IMAP_SERVER', 'imap.gmail.com')
IMAP_PORT = int(os.environ.get('EMAIL_IMAP_PORT', '993'))
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
CHECK_INTERVAL = int(os.environ.get('EMAIL_CHECK_INTERVAL', '300'))  # 5 minuten

# Mailbox settings
INBOX_FOLDER = os.environ.get('EMAIL_INBOX_FOLDER', 'INBOX')
PROCESSED_FOLDER = os.environ.get('EMAIL_PROCESSED_FOLDER', 'Wishlist/Processed')
ALLOWED_SENDERS = os.environ.get('EMAIL_ALLOWED_SENDERS', '').split(',')


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


def extract_wishlist_items(subject: str, body: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Extract wishlist items uit email subject of body.

    Formaten:
    - auteur - "titel"
    - auteur - "titel" > boekenplank
    - Wishlist: auteur - "titel"
    - Voeg toe: auteur - "titel" > boekenplank

    Returns: List van (author, title, shelf_name) tuples
    """
    items = []

    # Patroon: auteur - "titel" optioneel > plank
    pattern = r'([^-"]+?)\s*-\s*["\u201C]([^"\u201D]+)["\u201D]\s*(?:>\s*(.+?))?\s*$'

    # Probeer subject
    for match in re.finditer(pattern, subject):
        author = match.group(1).strip()
        title = match.group(2).strip()
        shelf = (match.group(3) or '').strip() or None
        if author and title:
            items.append((author, title, shelf))

    # Probeer body (elke regel)
    for line in body.split('\n'):
        line = line.strip()

        # Skip lege regels en replies
        if not line or line.startswith('>'):
            continue

        # Verwijder prefixes
        line = re.sub(r'^(wishlist|voeg toe|add):\s*', '', line, flags=re.IGNORECASE)

        for match in re.finditer(pattern, line):
            author = match.group(1).strip()
            title = match.group(2).strip()
            shelf = (match.group(3) or '').strip() or None
            if author and title:
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
    if not ALLOWED_SENDERS or not ALLOWED_SENDERS[0]:
        # Geen whitelist = alle senders toegestaan
        return True

    sender_lower = sender.lower()
    for allowed in ALLOWED_SENDERS:
        if allowed.strip().lower() in sender_lower:
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
        subject = decode_header_value(msg.get('Subject', ''))
        body = get_email_body(msg)

        print(f"\n📧 Email van: {from_header}")
        print(f"   Subject: {subject}")

        # Check sender
        if not is_sender_allowed(from_header):
            print(f"   ⚠️ Sender niet toegestaan: {from_header}")
            return 0

        # Extract items
        items = extract_wishlist_items(subject, body)

        if not items:
            print("   Geen wishlist items gevonden")
            return 0

        # Voeg items toe
        for author, title, shelf_name in items:
            try:
                item_id = db.add_wishlist_item(
                    author=author,
                    title=title,
                    added_via='email',
                    shelf_name=shelf_name
                )
                shelf_msg = f" → {shelf_name}" if shelf_name else ""
                print(f"   ✓ Toegevoegd: {author} - \"{title}\"{shelf_msg}")
                added_count += 1

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

            if added > 0:
                # Markeer als gelezen
                mail.store(email_id, '+FLAGS', '\\Seen')
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

    if ALLOWED_SENDERS and ALLOWED_SENDERS[0]:
        print(f"   Whitelist: {', '.join(ALLOWED_SENDERS)}")
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
