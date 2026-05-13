#!/bin/bash
# VO Studio – sync app-bestanden direct naar NAS
# Gebruik: bash sync_to_nas.sh [nas-ip]
# Voorbeeld: bash sync_to_nas.sh 192.168.2.17

NAS="${1:-192.168.2.17}"
NAS_USER="${2:-Jobbovelander}"
NAS_PATH="/volume1/docker/vo_studio"

echo ""
echo "VO Studio → NAS sync"
echo "━━━━━━━━━━━━━━━━━━━━━"
echo "Naar: $NAS_USER@$NAS:$NAS_PATH"
echo ""

# Sync app-bestanden (HTML, JS, CSS, Python)
rsync -avz --progress \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude=".DS_Store" \
  app/ "$NAS_USER@$NAS:$NAS_PATH/app/"

# Sync configuratie
rsync -avz docker-compose.yml Dockerfile requirements.txt "$NAS_USER@$NAS:$NAS_PATH/"

echo ""
echo "Sync klaar."
echo ""
echo "HTML/CSS/JS: direct actief (geen herstart nodig)"
echo "Python (server.py/database.py): herstart container:"
echo "  ssh $NAS_USER@$NAS 'cd $NAS_PATH && docker compose restart vo-studio'"
echo ""
echo "Na requirements.txt wijziging: image opnieuw bouwen:"
echo "  ssh $NAS_USER@$NAS 'cd $NAS_PATH && docker compose build && docker compose up -d --force-recreate vo-studio'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
