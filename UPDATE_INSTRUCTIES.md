# 🔄 Auto-Update Instructies

## Setup: Maak /app een Git Repository

**Eenmalig uitvoeren in Portainer Console:**

1. Ga naar **Containers** → `wishlist`
2. Klik op **Console**
3. Kies `/bin/sh`
4. Klik **Connect**

Voer uit in de console:

```bash
cd /app

# Backup huidige bestanden
mkdir -p /tmp/backup
cp -r * /tmp/backup/

# Clone de repository
rm -rf .git
git init
git remote add origin https://github.com/gjagils/Wishlist.git
git fetch origin claude/wishlist-web-interface-80kID
git checkout -b claude/wishlist-web-interface-80kID origin/claude/wishlist-web-interface-80kID

# Restore data files (als je wijzigingen had)
# cp /tmp/backup/.env . 2>/dev/null || true

echo "✓ Git setup compleet!"
```

**Check:**
```bash
git status
git log --oneline -5
```

---

## Optie 1: Via Web UI (Toekomstig)

⚠️ **Nog niet geïmplementeerd in de UI**

Later kun je via de web interface op een "Update" knop klikken.

---

## Optie 2: Via API Call

**Update via curl:**

```bash
curl -u admin:jouw-wachtwoord \
  -X POST \
  http://192.168.68.120:6754/api/update
```

**Response als succesvol:**
```json
{
  "message": "Update succesvol",
  "output": "Already up to date.",
  "restart_required": true
}
```

**Na update:**
- Herstart container in Portainer
- Of in console: `docker restart wishlist`

---

## Optie 3: Via Portainer Console

1. **Containers** → `wishlist` → **Console** → `/bin/sh`
2. Voer uit:

```bash
cd /app
git pull origin claude/wishlist-web-interface-80kID
```

3. Herstart container via Portainer UI

---

## Optie 4: Automatisch bij Container Start

⚠️ **Let op:** Dit doet ALTIJD een git pull bij elke herstart!

Wijzig docker-compose.yml command naar:

```yaml
command: >
  sh -c "
  apt-get update -qq &&
  apt-get install -y -qq git &&
  cd /app &&
  git pull origin claude/wishlist-web-interface-80kID || true &&
  chmod -R 777 /data &&
  pip install --no-cache-dir -r requirements.txt &&
  python run_all.py
  "
```

**Voordeel:**
- Altijd laatste versie na herstart

**Nadeel:**
- Langere startup tijd
- Overschrijft lokale wijzigingen

---

## Troubleshooting

### "Not a git repository"

Je hebt de setup nog niet gedaan. Volg "Setup" stappen hierboven.

### "Permission denied"

In console:
```bash
cd /app
chmod -R 755 .git
```

### "Local changes would be overwritten"

Als je lokale wijzigingen hebt:
```bash
cd /app
git stash           # Bewaar lokale wijzigingen
git pull            # Update
git stash pop       # Herstel lokale wijzigingen
```

### Container start niet na update

1. Check logs: `docker logs wishlist`
2. Rollback:
   ```bash
   cd /app
   git reset --hard HEAD~1
   docker restart wishlist
   ```

---

## Beste Werkwijze

**Voor productiee:**
1. Setup git repository eenmalig
2. Update via API call: `/api/update`
3. Bekijk logs in web UI of Portainer
4. Herstart container alleen als nodig

**Voor development:**
1. Gebruik Optie 4 (auto-update bij start)
2. Test nieuwe versies direct na herstart

---

## Database Locking Fix

✅ **Opgelost in nieuwste versie!**

Wijzigingen:
- WAL mode enabled (Write-Ahead Logging)
- Timeout verhoogd naar 30 seconden
- Database file permissions automatisch gefixed
- Betere concurrent access voor meerdere processen

Als je nog steeds "database locked" errors ziet:
1. Herstart de container
2. Check permissions: `ls -la /data/`
3. Check of oude database file verwijderd is

---

## Handmatige File Upload (Zonder Git)

Als je liever handmatig update zonder git:

1. Download ZIP van GitHub
2. Pak uit
3. Upload naar `/volume1/docker/wishlist/app` via File Station
4. Overschrijf bestanden
5. Herstart container in Portainer

⚠️ **Nadeel:** `/api/update` werkt niet zonder git setup
