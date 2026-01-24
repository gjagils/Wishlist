# 🔐 .ENV Bestand Setup - Veilige Configuratie

## Waarom .env Bestand Gebruiken?

✅ **Voordelen:**
- API keys staan NIET in git repository
- Geen gevoelige data in docker-compose.yml
- Makkelijk verschillende configuraties per omgeving
- Betere beveiliging met file permissions

❌ **Zonder .env:**
- API keys zichtbaar in Portainer UI
- Moeilijk om geheimen veilig te delen
- Configuratie zit vast in compose file

---

## 📋 Setup Instructies

### Stap 1: Maak .env Bestand op Synology

**Via File Station:**

1. Download `.env.template` van GitHub
2. Hernoem naar `.env`
3. Open in tekst editor (Notepad++, VSCode, etc.)
4. **Vul IN jouw configuratie:**

```bash
# Vul in met jouw gegevens:
SPOTWEB_BASE_URL=http://192.168.68.120:8085
SPOTWEB_APIKEY=jouw-spotweb-api-key
SAB_BASE_URL=http://192.168.68.120:8080/sabnzbd
SAB_APIKEY=jouw-sabnzbd-api-key

# Verander dit!
WEB_PASSWORD=kies-een-veilig-wachtwoord-hier
SECRET_KEY=genereer-random-string-hier

# Optioneel: Gmail
EMAIL_ADDRESS=jouw@gmail.com
EMAIL_PASSWORD=jouw-gmail-app-password
```

5. Save het bestand
6. Upload naar: `/volume1/docker/wishlist/.env`

---

### Stap 2: Beveilig .env Bestand (Belangrijk!)

**Via SSH (aanbevolen):**

```bash
cd /volume1/docker/wishlist
chmod 600 .env
chown root:root .env
```

**Wat doet dit:**
- `600` = Alleen eigenaar kan lezen/schrijven
- Niemand anders kan je API keys zien

**Zonder SSH:**
- File Station → Rechtsklik `.env` → Properties → Permissions
- Zet alleen "Read" en "Write" voor Owner
- Verwijder alle andere permissions

---

### Stap 3: Update Docker Compose in Portainer

**In Portainer Stack Editor, vervang met:**

```yaml
version: '3.8'

services:
  wishlist:
    image: python:3.12-slim
    container_name: wishlist
    restart: unless-stopped

    ports:
      - "6754:5000"

    volumes:
      - /volume1/docker/wishlist/app:/app
      - /volume1/docker/wishlist/data:/data

    working_dir: /app

    # 🔐 Laad alle variabelen uit .env bestand
    env_file:
      - /volume1/docker/wishlist/.env

    command: >
      sh -c "
      apt-get update -qq &&
      apt-get install -y -qq git curl &&
      rm -rf /app/* &&
      git clone -b claude/wishlist-web-interface-80kID https://github.com/gjagils/Wishlist.git /tmp/repo &&
      cp -r /tmp/repo/* /app/ &&
      chmod -R 777 /data &&
      rm -rf __pycache__ &&
      pip install --no-cache-dir -r requirements.txt &&
      python run_all.py
      "

    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:5000/api/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

**Let op:** Geen `environment:` sectie meer!

---

### Stap 4: Deploy

1. Klik **Update the stack**
2. Check: "Re-pull image and redeploy"
3. Deploy

---

## 🔍 Verificatie

**Check of .env wordt geladen:**

In Portainer Console:
```bash
echo $SPOTWEB_APIKEY
```

Moet je API key tonen (als het werkt).

**Check permissions:**
```bash
ls -la /volume1/docker/wishlist/.env
```

Moet tonen: `-rw------- 1 root root`

---

## 🔐 Veiligheids Checklist

- [ ] `.env` bestand aangemaakt
- [ ] `WEB_PASSWORD` gewijzigd naar veilig wachtwoord
- [ ] `SECRET_KEY` gegenereerd (min 32 random karakters)
- [ ] File permissions gezet op 600
- [ ] `.env` staat NIET in git (staat al in .gitignore)
- [ ] Backup van `.env` op veilige plek (buiten server)
- [ ] Docker compose aangepast naar `env_file:`
- [ ] Container herstart en werkt

---

## 🆘 Troubleshooting

### Error: "env_file not found"

**Probleem:** Pad naar .env klopt niet

**Oplossing:**
```bash
# Check of bestand bestaat
ls -la /volume1/docker/wishlist/.env

# Als niet: maak het aan
cd /volume1/docker/wishlist
touch .env
nano .env  # plak configuratie
```

### Environment variables worden niet geladen

**Check 1:** Bestand naam klopt exact?
```bash
# Moet heten: .env (met punt, zonder extensie)
# NIET: env.txt, .env.production, etc.
```

**Check 2:** Docker compose syntax?
```yaml
env_file:
  - /volume1/docker/wishlist/.env  # Let op: streepje voor pad!
```

**Check 3:** Container herstart na wijziging?
```bash
docker restart wishlist
```

### Wil terug naar oude manier (env in compose)

**Verwijder deze regel:**
```yaml
env_file:
  - /volume1/docker/wishlist/.env
```

**Voeg terug:**
```yaml
environment:
  SPOTWEB_BASE_URL: "..."
  SPOTWEB_APIKEY: "..."
  # etc.
```

---

## 💡 Best Practices

### 1. Secret Key Genereren

**Via online tool:**
```
https://randomkeygen.com/
```

**Of in terminal:**
```bash
openssl rand -hex 32
```

### 2. Verschillende .env per Omgeving

```
.env.production  → Productie (echte API keys)
.env.development → Development (test keys)
.env.local       → Lokale tests
```

Upload de juiste als `.env` op je Synology.

### 3. Backup Strategie

**Bewaar encrypted backup:**
```bash
# Encrypten
gpg -c /volume1/docker/wishlist/.env
# Maakt: .env.gpg

# Decrypten (als nodig)
gpg /volume1/docker/wishlist/.env.gpg
```

**Bewaar .env.gpg:**
- In je password manager
- Op encrypted USB stick
- In encrypted cloud backup

**NOOIT:**
- In git repository committen
- Per email versturen (unencrypted)
- In Discord/Slack delen

### 4. Roteer Secrets Regelmatig

Elke 3-6 maanden:
1. Nieuwe SABnzbd API key genereren
2. Nieuwe Spotweb API key
3. Nieuwe WEB_PASSWORD
4. Nieuwe SECRET_KEY
5. Update .env
6. Restart container

---

## 📝 Template .env Bestand

```bash
# SPOTWEB
SPOTWEB_BASE_URL=http://192.168.68.120:8085
SPOTWEB_APIKEY=your-key-here
SPOTWEB_CAT=7020

# SABNZBD
SAB_BASE_URL=http://192.168.68.120:8080/sabnzbd
SAB_APIKEY=your-key-here
SAB_CATEGORY=wishlist

# WEB UI
WEB_USERNAME=admin
WEB_PASSWORD=change-this-password
SECRET_KEY=generate-32-random-chars-here

# WORKER
INTERVAL_SECONDS=3600

# DATABASE
DB_PATH=/data/wishlist.db
WISHLIST_FILE=/data/wishlist.txt

# FLASK
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=false
PYTHONUNBUFFERED=1

# EMAIL (optioneel)
EMAIL_ADDRESS=
EMAIL_PASSWORD=
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_CHECK_INTERVAL=300
EMAIL_ALLOWED_SENDERS=
```

---

## ✅ Na Setup

Je docker-compose.yml is nu veel cleaner:
- Geen hardcoded secrets
- Herbruikbaar voor andere projecten
- Makkelijk te delen zonder gevoelige data

Je `.env` bestand is beveiligd:
- Alleen root kan lezen
- Staat niet in git
- Encrypted backup gemaakt

🎉 **Je Wishlist Manager is nu veilig geconfigureerd!**
