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

# Sync docker-compose.yml
rsync -avz docker-compose.yml "$NAS_USER@$NAS:$NAS_PATH/docker-compose.yml"

echo ""
echo "Sync klaar. HTML/CSS/JS wijzigingen zijn direct actief."
echo "Voor Python-wijzigingen: container herstarten."
echo ""
echo "Herstarten (alleen nodig na server.py / database.py wijzigingen):"
echo "  ssh $NAS_USER@$NAS 'cd $NAS_PATH && docker compose restart vo-studio'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
