# VO Studio

Voice-over opname systeem voor Synology NAS.

## Workflow

```
VS Code → GitHub → GitHub Actions → ghcr.io → Watchtower → NAS
```

Elke push naar `main`:
1. GitHub Actions bouwt automatisch een nieuw Docker image
2. Watchtower op de NAS pikt dit op binnen 5 minuten
3. Container herstart automatisch

---

## Eerste keer instellen

### 1. GitHub repo rechten instellen
github.com/jobbovelander/vo-studio
→ Settings → Actions → General
→ Workflow permissions → Read and write permissions → Save

### 2. NAS setup (eenmalig via SSH)
```bash
cd /volume1/docker/vo_studio
sudo bash nas_setup.sh
```

### 3. Personal Access Token aanmaken
github.com → Settings → Developer settings
→ Personal access tokens → Tokens (classic) → Generate new token
→ Scope: read:packages
→ Kopieer de token — die heb je nodig bij nas_setup.sh

---

## Updates uitrollen

In VS Code terminal:
```bash
git add .
git commit -m "Beschrijving van wijziging"
git push
```

NAS update automatisch binnen 5 minuten.

Direct forceren op NAS (zonder op Watchtower te wachten):
```bash
cd /volume1/docker/vo_studio
docker compose pull vo-studio
docker compose up -d --force-recreate vo-studio
```

---

## Data op NAS

```
/volume1/vo_studio/
├── videos/
├── scripts/
├── outputs/
└── vo_studio.db
```
