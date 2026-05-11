#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  VO Studio – Automatische installatie voor Synology DS920+
#  Versie 1.2
# ═══════════════════════════════════════════════════════════════

# Noot: compose draait de app op hostpoort 5080 (containerpoort 5000).
set -euo pipefail

# ── Kleuren ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ── Configuratie ─────────────────────────────────────────────────
APP_NAME="vo-studio"
APP_DIR="/volume1/docker/vo_studio"
DATA_DIR="/volume1/vo_studio"
HTTPS_PORT=5443
HTTP_PORT=5080
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Functies ─────────────────────────────────────────────────────
header() {
  echo ""
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}${BOLD}  VO Studio – Installatie${NC}"
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
}

step() { echo -e "\n${BOLD}${CYAN}▸ $1${NC}"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${DIM}$1${NC}"; }

die() {
  err "$1"
  echo ""
  echo -e "${RED}Installatie afgebroken.${NC}"
  exit 1
}

confirm() {
  printf "\n${YELLOW}%s${NC} [j/n] " "$1"
  read -r ans
  [[ "$ans" =~ ^[jJyY] ]]
}

# ── Controleer root ───────────────────────────────────────────────
check_root() {
  step "Rechten controleren"
  if [[ $EUID -ne 0 ]]; then
    die "Dit script moet als root worden uitgevoerd: sudo bash install.sh"
  fi
  ok "Root-rechten aanwezig"
}

# ── Controleer Synology ───────────────────────────────────────────
check_synology() {
  step "Synology omgeving controleren"
  if [[ ! -f /etc/synoinfo.conf ]]; then
    warn "Dit lijkt geen Synology NAS te zijn."
    warn "Het script is ontworpen voor DSM 7. Doorgaan op eigen risico."
    confirm "Toch doorgaan?" || exit 0
  else
    local model
    model=$(grep "upnpmodelname" /etc/synoinfo.conf | cut -d'"' -f2 2>/dev/null || echo "onbekend")
    ok "Synology NAS gevonden: $model"
  fi

  if [[ -f /etc.defaults/VERSION ]]; then
    local dsm_ver
    dsm_ver=$(grep "majorversion" /etc.defaults/VERSION | cut -d'"' -f2 2>/dev/null || echo "0")
    if [[ "$dsm_ver" -lt 7 ]] 2>/dev/null; then
      die "DSM 7 of hoger vereist. Gevonden: DSM $dsm_ver"
    fi
    ok "DSM versie: $dsm_ver"
  fi
}

# ── Controleer Docker ─────────────────────────────────────────────
check_docker() {
  step "Docker controleren"
  if ! command -v docker &>/dev/null; then
    die "Docker niet gevonden. Installeer 'Container Manager' via Package Center in DSM."
  fi
  ok "Docker gevonden: $(docker --version | cut -d' ' -f3 | tr -d ',')"

  # Bepaal welk compose-commando beschikbaar is
  if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
  elif docker-compose --version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
  else
    die "Docker Compose niet gevonden. Update Container Manager naar de laatste versie."
  fi
  ok "Docker Compose: $COMPOSE_CMD"
  export COMPOSE_CMD
}

# ── Mappen aanmaken ───────────────────────────────────────────────
setup_folders() {
  step "Mappen aanmaken"

  for dir in "$DATA_DIR" "$DATA_DIR/videos" "$DATA_DIR/scripts" "$DATA_DIR/outputs"; do
    if [[ -d "$dir" ]]; then
      ok "Bestaat al: $dir"
    else
      mkdir -p "$dir"
      ok "Aangemaakt: $dir"
    fi
  done

  mkdir -p "$APP_DIR"
  ok "App-map: $APP_DIR"

  chown -R root:users "$DATA_DIR" 2>/dev/null || true
  chmod -R 775 "$DATA_DIR" 2>/dev/null || true
}

# ── App-bestanden kopiëren ────────────────────────────────────────
copy_app_files() {
  step "App-bestanden installeren"

  # FIX #4: verwijder bestaande app-submap zodat cp deterministisch is
  rm -rf "${APP_DIR:?}/app"
  cp -r "$SCRIPT_DIR/app"              "$APP_DIR/app"
  cp    "$SCRIPT_DIR/Dockerfile"       "$APP_DIR/Dockerfile"
  cp    "$SCRIPT_DIR/docker-compose.yml" "$APP_DIR/docker-compose.yml"
  cp    "$SCRIPT_DIR/requirements.txt" "$APP_DIR/requirements.txt"

  ok "Bestanden gekopieerd naar $APP_DIR"
  info "$(find "$APP_DIR" -type f | wc -l) bestanden geïnstalleerd"
}

# ── Poorten controleren ───────────────────────────────────────────
check_ports() {
  step "Poorten controleren"

  port_in_use() {
    ss -tlnp 2>/dev/null | grep -q ":$1 " || \
    netstat -tlnp 2>/dev/null | grep -q ":$1 " || \
    false
  }

  if port_in_use "$HTTP_PORT"; then
    # Stop bestaande VO Studio container als die de oorzaak is
    if docker ps -q -f "name=${APP_NAME}" 2>/dev/null | grep -q .; then
      info "Bestaande VO Studio container stoppen…"
      docker stop "$APP_NAME" 2>/dev/null || true
      docker rm   "$APP_NAME" 2>/dev/null || true
      ok "Bestaande container verwijderd"
    else
      warn "Poort ${HTTP_PORT} in gebruik door een ander proces"
    fi
  else
    ok "Poort ${HTTP_PORT} (HTTP) beschikbaar"
  fi

  if port_in_use "$HTTPS_PORT"; then
    warn "Poort ${HTTPS_PORT} in gebruik — HTTPS proxy mogelijk al actief"
  else
    ok "Poort ${HTTPS_PORT} (HTTPS) beschikbaar"
  fi
}

# ── Docker image updaten en starten ───────────────────────────────
build_and_start() {
  step "Docker image ophalen en container (her)starten"

  cd "$APP_DIR"

  $COMPOSE_CMD down 2>/dev/null || true

  local pull_log
  pull_log=$(mktemp)
  if $COMPOSE_CMD pull vo-studio >"$pull_log" 2>&1; then
    ok "Docker image opgehaald"
  else
    echo ""
    cat "$pull_log"
    rm -f "$pull_log"
    die "Docker pull mislukt. Controleer netwerk of GHCR-login."
  fi
  rm -f "$pull_log"

  local start_log
  start_log=$(mktemp)
  if $COMPOSE_CMD up -d --force-recreate vo-studio >"$start_log" 2>&1; then
    ok "Container gestart (force-recreate)"
  else
    cat "$start_log"
    rm -f "$start_log"
    die "Container starten mislukt."
  fi
  rm -f "$start_log"

  info "Wachten tot app reageert…"
  local i=0
  while [[ $i -lt 30 ]]; do
    if curl -sf "http://localhost:${HTTP_PORT}" &>/dev/null; then
      ok "App reageert op poort ${HTTP_PORT}"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  warn "App reageert nog niet na 60s — check: sudo docker logs ${APP_NAME}"
}

# ── HTTPS via Synology nginx ──────────────────────────────────────
setup_https() {
  step "HTTPS reverse proxy instellen"

  # Op DSM 7 is het juiste nginx-conf pad:
  local nginx_conf_dir="/etc/nginx/conf.d"
  local custom_conf="${nginx_conf_dir}/vo_studio.conf"

  # Zoek Synology SSL-certificaat
  local cert_pem key_pem
  cert_pem=$(find /usr/syno/etc/certificate -name "cert.pem" 2>/dev/null | head -1 || echo "")
  key_pem=$(find /usr/syno/etc/certificate -name "privkey.pem" 2>/dev/null | head -1 || echo "")

  # Fallback naar system default
  if [[ -z "$cert_pem" ]]; then
    cert_pem="/usr/syno/etc/certificate/system/default/cert.pem"
    key_pem="/usr/syno/etc/certificate/system/default/privkey.pem"
  fi

  if [[ ! -f "$cert_pem" ]]; then
    warn "SSL-certificaat niet gevonden. HTTPS overgeslagen."
    setup_https_manual
    return
  fi

  mkdir -p "$nginx_conf_dir"
  cat > "$custom_conf" << NGINXCONF
server {
    listen ${HTTPS_PORT} ssl;
    server_name _;

    ssl_certificate     ${cert_pem};
    ssl_certificate_key ${key_pem};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    add_header Permissions-Policy "microphone=*";
    add_header Cross-Origin-Opener-Policy  "same-origin";
    add_header Cross-Origin-Embedder-Policy "require-corp";

    location / {
        proxy_pass          http://127.0.0.1:${HTTP_PORT};
        proxy_http_version  1.1;
        proxy_set_header    Upgrade \$http_upgrade;
        proxy_set_header    Connection "upgrade";
        proxy_set_header    Host \$host;
        proxy_set_header    X-Real-IP \$remote_addr;
        proxy_set_header    X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto \$scheme;
        proxy_read_timeout  300s;
        proxy_send_timeout  300s;
        client_max_body_size 8192m;
    }
}
NGINXCONF

  ok "nginx-configuratie aangemaakt: $custom_conf"

  # FIX #5: correcte nginx reload op Synology DSM 7
  reload_nginx
}

reload_nginx() {
  # DSM 7: nginx wordt beheerd door synoservice
  if synoservice --restart nginx 2>/dev/null; then
    ok "Nginx herladen via synoservice"
    return 0
  fi
  # Fallback: nginx binary direct
  if nginx -t 2>/dev/null && nginx -s reload 2>/dev/null; then
    ok "Nginx herladen via nginx -s reload"
    return 0
  fi
  warn "Nginx kon niet automatisch worden herladen."
  warn "Voer uit: sudo synoservice --restart nginx"
}

setup_https_manual() {
  warn "Stel HTTPS handmatig in via DSM:"
  info "  Configuratiescherm → Aanmeldingsportaal → Geavanceerd → Reverse Proxy"
  info "  Nieuw → Bron: HTTPS :${HTTPS_PORT} → Doel: HTTP localhost:${HTTP_PORT}"
}

# ── Autostart ────────────────────────────────────────────────────
setup_autostart() {
  step "Automatisch starten instellen"

  # FIX #3: DSM 7 gebruikt /usr/local/etc/rc.d/ voor autostart scripts
  local rc_dir="/usr/local/etc/rc.d"
  local rc_script="${rc_dir}/vo_studio.sh"

  mkdir -p "$rc_dir"
  cat > "$rc_script" << RCEOF
#!/bin/sh
# VO Studio autostart – DSM 7
case "\$1" in
  start)
    sleep 20
    cd "${APP_DIR}"
    ${COMPOSE_CMD} up -d 2>/dev/null || true
    ;;
  stop)
    cd "${APP_DIR}"
    ${COMPOSE_CMD} down 2>/dev/null || true
    ;;
esac
RCEOF
  chmod +x "$rc_script"
  ok "Autostart ingesteld: $rc_script"
  info "Container herstart ook automatisch via Docker 'unless-stopped' policy"
}

# ── NAS IP ophalen ────────────────────────────────────────────────
get_nas_ip() {
  local ip=""

  # FIX #6: probeer meerdere methodes, neem alleen het eerste IP
  # Methode 1: ip route (werkt ook zonder internet via default gateway)
  ip=$(ip route 2>/dev/null | grep default | awk '{print $NF}' | head -1)
  if [[ -n "$ip" ]]; then
    # Haal het IP van die interface op
    ip=$(ip addr show "$ip" 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1 | head -1)
  fi

  # Methode 2: alle niet-loopback IPs
  if [[ -z "$ip" ]]; then
    ip=$(ip addr show 2>/dev/null | grep 'inet ' | grep -v '127\.0\.0\.' | awk '{print $2}' | cut -d/ -f1 | head -1)
  fi

  echo "${ip:-[NAS-IP]}"
}

# ── Samenvatting ──────────────────────────────────────────────────
print_summary() {
  local nas_ip
  nas_ip=$(get_nas_ip)

  # Bepaal of HTTPS actief is
  local https_active=false
  if [[ -f "/etc/nginx/conf.d/vo_studio.conf" ]]; then
    https_active=true
  fi

  echo ""
  echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}${BOLD}  VO Studio geïnstalleerd!${NC}"
  echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""

  if [[ "$https_active" == true ]]; then
    echo -e "  ${BOLD}Studio (microfoon werkt):${NC}"
    echo -e "  ${CYAN}https://${nas_ip}:${HTTPS_PORT}${NC}"
    echo ""
    echo -e "  ${BOLD}Admin:${NC}"
    echo -e "  ${CYAN}https://${nas_ip}:${HTTPS_PORT}/admin${NC}"
    echo ""
    echo -e "  ${DIM}HTTP (microfoon werkt niet op andere computers):${NC}"
    echo -e "  ${DIM}http://${nas_ip}:${HTTP_PORT}${NC}"
  else
    echo -e "  ${BOLD}Studio:${NC}"
    echo -e "  ${CYAN}http://${nas_ip}:${HTTP_PORT}${NC}"
    echo ""
    echo -e "  ${BOLD}Admin:${NC}"
    echo -e "  ${CYAN}http://${nas_ip}:${HTTP_PORT}/admin${NC}"
    echo ""
    echo -e "  ${YELLOW}⚠  HTTPS niet actief — microfoon werkt alleen op deze NAS zelf${NC}"
    echo -e "  ${YELLOW}   Stel handmatig in via DSM Reverse Proxy (zie README.md)${NC}"
  fi

  echo ""
  echo -e "  ${BOLD}Bestanden:${NC}"
  echo -e "  ${DIM}${DATA_DIR}/videos/    ← video's${NC}"
  echo -e "  ${DIM}${DATA_DIR}/scripts/   ← scripts${NC}"
  echo -e "  ${DIM}${DATA_DIR}/outputs/   ← opnames & exports${NC}"
  echo ""
  echo -e "  ${BOLD}Beheer:${NC}"
  echo -e "  ${DIM}sudo docker logs ${APP_NAME}      logs${NC}"
  echo -e "  ${DIM}sudo docker restart ${APP_NAME}   herstarten${NC}"
  echo -e "  ${DIM}cd ${APP_DIR} && sudo ${COMPOSE_CMD} down   stoppen${NC}"

  if [[ "$https_active" == true ]]; then
    echo ""
    echo -e "  ${YELLOW}⚠  Accepteer het SSL-certificaat eenmalig in je browser${NC}"
    echo -e "  ${YELLOW}   (klik 'Geavanceerd' → 'Doorgaan naar site')${NC}"
  fi

  echo ""
  echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
}

# ── Hoofd ─────────────────────────────────────────────────────────
main() {
  header
  check_root
  check_synology
  check_docker
  setup_folders
  copy_app_files
  check_ports
  build_and_start
  setup_https
  setup_autostart
  print_summary
}

main "$@"
