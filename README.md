# 📚 Wishlist Manager

Een webgebaseerde wishlist manager die automatisch boeken/ebooks zoekt in Spotweb en toevoegt aan SABnzbd.

## ✨ Nieuwe Features

- 🌐 **Web Interface** - Beheer je wishlist via een moderne webinterface
- 📧 **Email Integratie** - Voeg items toe via Gmail
- 🗄️ **Database** - SQLite database voor betere tracking en status management
- 📊 **Status Tracking** - Zie de status van elk item (pending, searching, found, failed)
- 📝 **Activity Logs** - Volg alle activiteit in real-time
- 🔐 **Beveiliging** - Basic authentication voor web toegang

## 🏗️ Architectuur

```
┌─────────────┐
│  Web UI     │ ← Beheer wishlist via browser
└──────┬──────┘
       │
┌──────▼──────┐
│  REST API   │ ← Flask applicatie
└──────┬──────┘
       │
   ┌───┴────┐
   ▼        ▼
┌──────┐ ┌──────────┐
│ DB   │ │  Email   │ ← Gmail IMAP monitoring
└───┬──┘ │  Monitor │
    │    └─────┬────┘
    │          │
    └────┬─────┘
         ▼
    ┌─────────┐
    │ Worker  │ ← Zoekt in Spotweb
    └────┬────┘
         │
    ┌────┴────┐
    ▼         ▼
┌─────────┐ ┌──────────┐
│Spotweb  │ │ SABnzbd  │
└─────────┘ └──────────┘
```

## 🚀 Snelstart (Synology)

### 1. Voorbereidingen

**Benodigde systemen:**
- Spotweb installatie met API toegang
- SABnzbd installatie
- (Optioneel) Gmail account voor email integratie

**Haal Spotweb API key op:**
1. Log in op Spotweb
2. Ga naar Settings → API
3. Kopieer je API key

**Haal SABnzbd API key op:**
1. Log in op SABnzbd
2. Ga naar Config → General
3. Kopieer je API Key

### 2. Installatie op Synology

**Via Docker (aanbevolen):**

1. Clone deze repository naar je Synology:
```bash
cd /volume1/docker/
git clone https://github.com/jouw-username/Wishlist.git
cd Wishlist
```

2. Maak een `data` directory:
```bash
mkdir data
```

3. Kopieer en bewerk de configuratie:
```bash
cp .env.example .env
nano .env
```

4. Pas minimaal deze waarden aan in `.env`:
```bash
SPOTWEB_BASE_URL=http://your-spotweb-url
SPOTWEB_APIKEY=your-spotweb-api-key
SAB_BASE_URL=http://your-sabnzbd-url:8080
SAB_APIKEY=your-sabnzbd-api-key
WEB_PASSWORD=kies-een-veilig-wachtwoord
```

5. Start de container:
```bash
docker-compose up -d
```

6. Check de logs:
```bash
docker-compose logs -f
```

7. Open de web interface:
```
http://synology-ip:5000
```
Login: `admin` / `<jouw-wachtwoord>`

### 3. Via Synology Docker GUI

1. Open **Docker** in DSM
2. Ga naar **Image** → **Add** → **Add from URL**
3. Bouw de image vanuit de Dockerfile
4. Maak een nieuwe container met deze instellingen:

**Poorten:**
- Lokale poort: `5000` → Container poort: `5000`

**Volume:**
- Map: `/volume1/docker/wishlist/data` → Mount path: `/data`

**Environment variables:**
```
SPOTWEB_BASE_URL=http://your-spotweb-url
SPOTWEB_APIKEY=your-api-key
SAB_BASE_URL=http://your-sabnzbd-url:8080
SAB_APIKEY=your-api-key
WEB_USERNAME=admin
WEB_PASSWORD=your-password
```

## 📧 Gmail Integratie Setup

### Stap 1: Gmail voorbereiden

1. **Schakel IMAP in:**
   - Ga naar Gmail Settings → "Forwarding and POP/IMAP"
   - Schakel "Enable IMAP" in

2. **Schakel 2-Factor Authentication in:**
   - Ga naar [Google Account Security](https://myaccount.google.com/security)
   - Schakel "2-Step Verification" in

3. **Maak App Password aan:**
   - Ga naar [App Passwords](https://myaccount.google.com/apppasswords)
   - Selecteer "Mail" en je device
   - Kopieer het gegenereerde wachtwoord (16 karakters)

### Stap 2: Configureer Wishlist

Voeg toe aan je `.env` of docker-compose.yml:

```bash
EMAIL_ADDRESS=jouw-email@gmail.com
EMAIL_PASSWORD=jouw-app-password-hier
EMAIL_ALLOWED_SENDERS=jouw-email@gmail.com,vriend@gmail.com
```

### Stap 3: Items toevoegen via email

Stuur een email naar jezelf met:

**Subject of body:**
```
Lapidus - "Grande finale"
```

Of meerdere items:
```
Mikkelsen - "Vrijstaat"
Horst - "Droog land"
Jonasson - "Het eiland"
```

**Formaat:** `auteur - "titel"`

De email monitor checkt elke 5 minuten je mailbox en voegt nieuwe items automatisch toe!

## 🌐 Web Interface Gebruik

### Items Toevoegen

1. Open `http://synology-ip:5000`
2. Vul auteur en titel in
3. Klik "Toevoegen"

### Status Betekenis

- **Pending** 🟡 - Wacht op verwerking
- **Searching** 🔵 - Wordt gezocht in Spotweb
- **Found** 🟢 - Gevonden en toegevoegd aan SABnzbd
- **Failed** 🔴 - Niet gevonden of fout opgetreden

### Items Verwijderen

Klik op "Verwijder" bij een item.

**Tip:** Items met status "Found" kun je veilig verwijderen - ze staan al in SABnzbd!

## 🔧 Configuratie Opties

### Environment Variables

| Variable | Default | Beschrijving |
|----------|---------|--------------|
| `SPOTWEB_BASE_URL` | - | **VERPLICHT** - URL van Spotweb |
| `SPOTWEB_APIKEY` | - | **VERPLICHT** - Spotweb API key |
| `SPOTWEB_CAT` | 7020 | Spotweb categorie (7020 = Ebook) |
| `SAB_BASE_URL` | - | **VERPLICHT** - URL van SABnzbd |
| `SAB_APIKEY` | - | **VERPLICHT** - SABnzbd API key |
| `SAB_CATEGORY` | books | SABnzbd categorie |
| `WEB_USERNAME` | admin | Web UI gebruikersnaam |
| `WEB_PASSWORD` | wishlist | Web UI wachtwoord |
| `EMAIL_ADDRESS` | - | Gmail adres (optioneel) |
| `EMAIL_PASSWORD` | - | Gmail app password (optioneel) |
| `EMAIL_ALLOWED_SENDERS` | - | Whitelist van senders (optioneel) |
| `EMAIL_CHECK_INTERVAL` | 300 | Check interval in seconden |
| `INTERVAL_SECONDS` | 900 | Worker interval (15 minuten) |
| `DB_PATH` | /data/wishlist.db | Database pad |

## 📊 API Endpoints

De REST API is beschikbaar voor custom integratie:

```bash
# Haal alle items op
curl -u admin:password http://localhost:5000/api/wishlist

# Voeg item toe
curl -u admin:password -X POST http://localhost:5000/api/wishlist \
  -H "Content-Type: application/json" \
  -d '{"author": "Lapidus", "title": "Grande finale"}'

# Verwijder item
curl -u admin:password -X DELETE http://localhost:5000/api/wishlist/1

# Haal logs op
curl -u admin:password http://localhost:5000/api/logs

# Statistics
curl -u admin:password http://localhost:5000/api/stats
```

## 🔄 Migratie van Oude Setup

Als je al een `wishlist.txt` had:

1. Plaats `wishlist.txt` in de `data` directory
2. Start de container
3. Items worden automatisch gemigreerd naar database
4. Een backup wordt gemaakt als `wishlist.txt.backup`

De oude `wishlist.txt` workflow blijft compatibel!

## 🐛 Troubleshooting

### Container start niet

**Check logs:**
```bash
docker-compose logs
```

**Veel voorkomende problemen:**
- Missende environment variables
- Verkeerde Spotweb/SABnzbd URLs
- Poort 5000 al in gebruik

### Email monitoring werkt niet

**Check:**
1. IMAP enabled in Gmail?
2. App Password gebruikt (niet normaal wachtwoord)?
3. Juiste email formaat: `auteur - "titel"`?

**Debug:**
```bash
docker-compose logs email
```

### Items worden niet gevonden

**Check:**
1. Is Spotweb bereikbaar?
2. Juiste categorie ingesteld?
3. Item bestaat in Spotweb?

**Tip:** Check de logs in de web interface voor details.

### Web UI niet bereikbaar

**Check:**
1. Container draait?
   ```bash
   docker ps
   ```
2. Poort 5000 open in firewall?
3. Juiste IP/hostname gebruikt?

## 🔒 Beveiliging

### Productie Deployment

1. **Verander standaard wachtwoord:**
   ```bash
   WEB_PASSWORD=sterker-wachtwoord-hier
   ```

2. **Gebruik HTTPS:**
   - Plaats achter reverse proxy (nginx/Traefik)
   - Gebruik Let's Encrypt certificaat

3. **Email whitelist:**
   ```bash
   EMAIL_ALLOWED_SENDERS=alleen-jouw-email@gmail.com
   ```

4. **Firewall:**
   - Limiteer toegang tot poort 5000
   - Of bind alleen op localhost: `FLASK_HOST=127.0.0.1`

## 📝 Changelog

### v2.0.0 (2026-01-24)

- ✨ Web interface toegevoegd
- ✨ Gmail email integratie
- ✨ SQLite database voor tracking
- ✨ Status management (pending/searching/found/failed)
- ✨ Activity logs
- ✨ REST API
- 🔐 Basic authentication
- 🐳 Verbeterde Docker setup
- 📚 Uitgebreide documentatie

### v1.0.0

- 🎯 Basis functionaliteit: wishlist.txt → Spotweb → SABnzbd

## 🤝 Bijdragen

Issues en pull requests zijn welkom!

## 📄 Licentie

MIT License - zie [LICENSE](LICENSE) bestand.

## 💡 Tips

- Items met status "Found" kun je veilig verwijderen
- Check logs regelmatig voor problemen
- Email subject werkt ook: "Wishlist: auteur - \"titel\""
- Meerdere items per email mogelijk (1 per regel)
- Worker draait elke 15 minuten (configureerbaar)

## 🆘 Support

Problemen? Maak een issue aan op GitHub!
