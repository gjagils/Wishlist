# 🚀 Snelle Installatie Gids

## Synology NAS - Docker

### Stap 1: Download

```bash
cd /volume1/docker/
git clone <your-repo-url> Wishlist
cd Wishlist
mkdir data
```

### Stap 2: Configureer

Kopieer `.env.example` naar `.env`:
```bash
cp .env.example .env
```

Bewerk `.env` met je favoriete editor:
```bash
nano .env
```

**Minimaal vereist:**
```bash
SPOTWEB_BASE_URL=http://your-spotweb
SPOTWEB_APIKEY=abc123
SAB_BASE_URL=http://your-sab:8080
SAB_APIKEY=xyz789
WEB_PASSWORD=veilig-wachtwoord
```

**Voor Gmail:**
```bash
EMAIL_ADDRESS=jou@gmail.com
EMAIL_PASSWORD=app-password-van-gmail
```

### Stap 3: Start

```bash
docker-compose up -d
```

### Stap 4: Check

```bash
docker-compose logs -f
```

Open browser: `http://synology-ip:5000`

Login: `admin` / `<jouw-wachtwoord>`

## Testen

1. Voeg een item toe via web UI
2. Check de logs tab
3. Wacht 15 min of herstart worker: `docker-compose restart`
4. (Optioneel) Stuur test email

## Problemen?

```bash
# Check of container draait
docker ps

# Bekijk logs
docker-compose logs webapp
docker-compose logs worker
docker-compose logs email

# Herstart alles
docker-compose restart

# Rebuild
docker-compose up -d --build
```

## Gmail App Password maken

1. Ga naar: https://myaccount.google.com/apppasswords
2. Selecteer "Mail" + "Other"
3. Kopieer het 16-karakter wachtwoord
4. Plak in `.env` als `EMAIL_PASSWORD`

Klaar! 🎉
