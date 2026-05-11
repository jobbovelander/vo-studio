#!/bin/bash
# VO Studio – eenmalige fix voor Docker-rechten
# Uitvoeren via SSH: sudo bash fix_docker_perms.sh

echo ""
echo "Docker rechten fixen voor $(logname 2>/dev/null || echo ${SUDO_USER:-$(whoami)})"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TARGET_USER="${SUDO_USER:-$(whoami)}"

# Voeg gebruiker toe aan docker-groep (Synology én standaard Linux)
synogroup --adduser docker "$TARGET_USER" 2>/dev/null || usermod -aG docker "$TARGET_USER"

echo "OK: $TARGET_USER toegevoegd aan docker-groep"
echo ""
echo "Start een nieuwe SSH-sessie — daarna werkt docker zonder sudo."
echo ""
echo "Update VO Studio direct:"
echo "  cd /volume1/docker/vo_studio"
echo "  docker compose pull vo-studio && docker compose up -d --force-recreate vo-studio"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
