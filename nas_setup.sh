#!/bin/bash
# VO Studio – NAS Setup
# Eenmalig uitvoeren na eerste installatie
# Stelt Watchtower in voor automatische updates vanuit GitHub

echo ""
echo "VO Studio – NAS Setup"
echo "━━━━━━━━━━━━━━━━━━━━━"
echo ""

# GitHub inloggegevens voor private registry
echo "Stap 1: Inloggen bij GitHub Container Registry"
echo "Gebruik je GitHub gebruikersnaam en een Personal Access Token"
echo "(Token aanmaken: github.com → Settings → Developer settings → Personal access tokens → Classic)"
echo "Benodigde scope: read:packages"
echo ""

read -p "GitHub gebruikersnaam: " GITHUB_USER
read -s -p "GitHub Personal Access Token: " GITHUB_TOKEN
echo ""

# Inloggen bij ghcr.io
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

if [ $? -ne 0 ]; then
  echo "Login mislukt. Controleer je gebruikersnaam en token."
  exit 1
fi

echo ""
echo "Stap 2: Data mappen aanmaken"
mkdir -p /volume1/vo_studio/{videos,scripts,outputs}
chmod -R 775 /volume1/vo_studio
echo "OK: /volume1/vo_studio aangemaakt"

echo ""
echo "Stap 3: Watchtower en VO Studio starten"
cd "$(dirname "$0")"
docker compose pull vo-studio
docker compose up -d --force-recreate vo-studio
docker compose up -d watchtower

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Klaar!"
echo ""
echo "Studio:  http://$(hostname -I | awk '{print $1}'):5080"
echo "Admin:   http://$(hostname -I | awk '{print $1}'):5080/admin"
echo ""
echo "Watchtower checkt elke 5 minuten op updates."
echo "Als je iets pusht naar GitHub wordt het automatisch bijgewerkt."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
