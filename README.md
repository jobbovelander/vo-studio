# VO Studio v4

## Installatie op Synology DS920+

```bash
# 1. Upload map naar NAS via File Station
# 2. SSH naar NAS
ssh admin@[NAS-IP]
cd ~/vo_studio_final
sudo bash install.sh
```

## Structuur

```
Serie → Aflevering → Script → Inzetten → Opnames
```

## Studio

- Dropdown: Serie → Aflevering → Script
- **R** starten (3-2-1 countdown) · **S** stoppen · **X** overslaan
- **F** vrije modus (negeert tijdcodes en auto-stop)
- Zoekbalk: zoek door alle scripts, spring direct naar inzet

## Admin

- Series en afleveringen aanmaken en beheren
- Scripts koppelen aan afleveringen
- Inzetten verplaatsen tussen scripts (scriptbestanden worden automatisch aangepast)
- Aflevering afronden en archiveren
- Gearchiveerde afleveringen terughalen

## Per script losse WAV export

Elke script heeft zijn eigen opnames en eigen export.
Export knop rechtsboven in de studio.
Vereist ffmpeg (zit in de Docker container).

## Data

```
/volume1/vo_studio/
├── vo_studio.db     ← SQLite database
├── videos/          ← videobestanden
├── scripts/         ← .txt scriptbestanden
└── outputs/
    └── [episode_id]/
        └── [script_id]/
            ├── take_001_00-00-02-00.webm
            └── scriptnaam_48k_24bit.wav
```
