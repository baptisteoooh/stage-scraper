#!/usr/bin/env bash
# Installe (ou met à jour) Stage Scraper sur un serveur Ubuntu 24.04 (Oracle Cloud « Always Free »).
#
#   sudo bash deploiement/installer_serveur.sh mon-site.duckdns.org
#
# À lancer depuis le dossier du code copié sur le serveur. Le script peut être relancé sans risque : il remet le
# nouveau code en place sans toucher aux données (bases, réglages, profils, comptes, .env).
#
# Ce qu'il fait :
#   1. heure de Paris, paquets (Python, SQLite, Caddy), mémoire d'appoint (swap) sur une petite machine ;
#   2. un utilisateur « stage » sans droits, le code dans /opt/stage-scraper, l'environnement Python (.venv) ;
#   3. le compte admin du site (si aucun compte n'existe encore) : tapé ici, jamais depuis le site ;
#   4. les services systemd : le site (toujours allumé, relancé s'il plante), le passage de 8 h et la sauvegarde
#      de 3 h 30 (rattrapés au démarrage si la machine était éteinte à l'heure prévue) ;
#   5. DuckDNS (le nom du site pointe vers l'adresse IP du serveur), Caddy (HTTPS automatique), pare-feu 80/443.
set -euo pipefail

DOMAINE="${1:-}"
APP=/opt/stage-scraper
UTILISATEUR=stage
PORT=8000
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

etape() { printf '\n==> %s\n' "$*"; }
arreter() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- vérifications
[[ $EUID -eq 0 ]] || arreter "à lancer avec sudo : sudo bash deploiement/installer_serveur.sh mon-site.duckdns.org"
[[ $DOMAINE =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
    || arreter "donne le nom du site, par exemple : sudo bash $0 mon-site.duckdns.org"
[[ -f $SOURCE/site_web.py && -f $SOURCE/requirements.txt ]] || arreter "lance le script depuis le dossier du code"
# shellcheck source=/dev/null
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || arreter "prévu pour Ubuntu (trouvé : ${PRETTY_NAME:-inconnu})"

# --------------------------------------------------------------------------- 1. système
etape "Heure de Paris (le passage de 8 h et la sauvegarde suivent cette heure)"
timedatectl set-timezone Europe/Paris

etape "Paquets : Python, SQLite, Caddy"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3 python3-venv python3-pip sqlite3 rsync curl caddy
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
    || echo "Attention : Python $(python3 -V) ; le projet est prévu pour Python 3.12."

if ! swapon --show | grep -q . && (( $(awk '/MemTotal/ {print $2}' /proc/meminfo) < 2000000 )); then
    etape "Petite machine (moins de 2 Go) : 2 Go de mémoire d'appoint (swap)"
    [[ -f /swapfile ]] || { fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile; }
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --------------------------------------------------------------------------- 2. code et Python
etape "Utilisateur « $UTILISATEUR » et code dans $APP"
id -u "$UTILISATEUR" &>/dev/null \
    || useradd --system --user-group --home-dir "$APP" --shell /usr/sbin/nologin "$UTILISATEUR"
mkdir -p "$APP"
if [[ $SOURCE != "$APP" ]]; then
    # Le code seulement : les données du serveur (bases, réglages, profils, comptes, clés) ne sont jamais écrasées.
    rsync -a \
        --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
        --exclude='/data/' --exclude='/comptes/' --exclude='/profil/' --exclude='/logs/' --exclude='/exports/' \
        --exclude='/.env' --exclude='/config.yaml' --exclude='/config.yaml.bak' --exclude='*.db' --exclude='*.db-*' \
        --exclude='/.impeccable/' --exclude='/.claude/' --exclude='/exemples sites/' \
        --exclude='/CV & lettre de motivation template/' \
        "$SOURCE/" "$APP/"
    [[ -f $APP/config.yaml ]] || cp "$SOURCE/config.yaml" "$APP/config.yaml"   # premier passage seulement
fi
chown -R "$UTILISATEUR:$UTILISATEUR" "$APP"
chmod 750 "$APP"
[[ -f $APP/.env ]] && chmod 600 "$APP/.env"
cd "$APP"   # la suite tourne sous l'utilisateur « stage », qui n'a pas accès au dossier d'origine

etape "Environnement Python (.venv) et bibliothèques (quelques minutes la première fois)"
en_stage() { sudo -u "$UTILISATEUR" -H "$@"; }
[[ -x $APP/.venv/bin/python ]] || en_stage python3 -m venv "$APP/.venv"
en_stage "$APP/.venv/bin/pip" install -q --no-cache-dir --upgrade pip
en_stage "$APP/.venv/bin/pip" install -q --no-cache-dir -r "$APP/requirements.txt"

# --------------------------------------------------------------------------- 3. compte admin
if (cd "$APP" && en_stage .venv/bin/python -c \
        'import sys; from stage_scraper import comptes; sys.exit(0 if comptes.aucun_compte() else 1)'); then
    etape "Ton compte admin sur le site (tape ton nom puis ton mot de passe, il ne s'affiche pas)"
    (cd "$APP" && en_stage .venv/bin/python site_web.py --creer-admin) </dev/tty \
        || arreter "compte admin pas créé : relance le script"
fi

# --------------------------------------------------------------------------- 4. services systemd
etape "Services : site, passage de 8 h, sauvegarde de 3 h 30"
PROTECTIONS="NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP"

cat > /etc/systemd/system/stage-scraper.service <<EOF
[Unit]
Description=Stage Scraper : le site
After=network-online.target
Wants=network-online.target

[Service]
User=$UTILISATEUR
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python site_web.py --en-ligne --port $PORT
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
$PROTECTIONS

[Install]
WantedBy=multi-user.target
EOF

ecrire_tache() {   # nom, description, commande run.py, heure
    cat > "/etc/systemd/system/stage-scraper-$1.service" <<EOF
[Unit]
Description=Stage Scraper : $2
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$UTILISATEUR
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python run.py $3
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=2h
$PROTECTIONS
EOF
    cat > "/etc/systemd/system/stage-scraper-$1.timer" <<EOF
[Unit]
Description=Stage Scraper : $2, chaque jour à $4

[Timer]
OnCalendar=*-*-* $4:00
# Machine éteinte à l'heure prévue : la tâche part dès le redémarrage.
Persistent=true

[Install]
WantedBy=timers.target
EOF
}
ecrire_tache auto "passage automatique (collecte, notes, mails)" "--auto" "08:00"
ecrire_tache sauvegarde "sauvegarde des données (14 jours gardés)" "--sauvegarder" "03:30"

# --------------------------------------------------------------------------- 5. DuckDNS, Caddy, pare-feu
if [[ $DOMAINE == *.duckdns.org ]]; then
    etape "DuckDNS : $DOMAINE pointe vers l'adresse IP de ce serveur"
    mkdir -p /etc/stage-scraper
    if [[ ! -f /etc/stage-scraper/duckdns.env ]]; then
        read -rsp "Jeton DuckDNS (en haut de la page duckdns.org, il ne s'affiche pas) : " JETON </dev/tty; echo
        [[ $JETON =~ ^[0-9a-f-]{36}$ ]] || arreter "ce jeton ne ressemble pas à un jeton DuckDNS"
        ( umask 077; printf 'DOMAINE=%s\nJETON=%s\n' "${DOMAINE%.duckdns.org}" "$JETON" > /etc/stage-scraper/duckdns.env )
    fi
    cat > /usr/local/bin/duckdns-maj <<'EOF'
#!/bin/sh
# Met à jour l'adresse IP du nom DuckDNS (la réponse est « OK » ou « KO »).
. /etc/stage-scraper/duckdns.env
reponse=$(curl -fsS --max-time 20 "https://www.duckdns.org/update?domains=$DOMAINE&token=$JETON&ip=")
[ "$reponse" = OK ] || { echo "DuckDNS a répondu : $reponse" >&2; exit 1; }
EOF
    chmod 755 /usr/local/bin/duckdns-maj
    cat > /etc/systemd/system/duckdns.service <<'EOF'
[Unit]
Description=DuckDNS : adresse IP du site
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/duckdns-maj
EOF
    cat > /etc/systemd/system/duckdns.timer <<'EOF'
[Unit]
Description=DuckDNS : vérifie l'adresse IP toutes les 30 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl start duckdns.service || arreter "DuckDNS refuse la mise à jour : vérifie le nom et le jeton
(pour en changer : sudo rm /etc/stage-scraper/duckdns.env, puis relance le script)"
    systemctl enable -q duckdns.timer
    systemctl start duckdns.timer
fi

etape "Caddy : HTTPS automatique (certificat Let's Encrypt) devant le site"
[[ -f /etc/caddy/Caddyfile && ! -f /etc/caddy/Caddyfile.origine ]] && cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.origine
cat > /etc/caddy/Caddyfile <<EOF
# Stage Scraper : Caddy reçoit les visites en HTTPS et les passe au site (127.0.0.1:$PORT).
$DOMAINE {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		# Les liens d'invitation ne partent jamais vers les sites des offres.
		Referrer-Policy "same-origin"
		-Server
	}
	reverse_proxy 127.0.0.1:$PORT
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

if command -v netfilter-persistent >/dev/null && [[ -f /etc/iptables/rules.v4 ]]; then
    etape "Pare-feu de la machine (images Oracle) : ports 80 et 443 ouverts"
    for port in 80 443; do
        if ! iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
            rejet=$(iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" {print $1; exit}')
            iptables -I INPUT "${rejet:-1}" -p tcp --dport "$port" -m state --state NEW -j ACCEPT
        fi
    done
    netfilter-persistent save >/dev/null
fi

# --------------------------------------------------------------------------- démarrage
etape "Démarrage"
systemctl daemon-reload
systemctl enable -q stage-scraper.service stage-scraper-auto.timer stage-scraper-sauvegarde.timer caddy
systemctl restart stage-scraper.service
systemctl start stage-scraper-auto.timer stage-scraper-sauvegarde.timer
systemctl reload-or-restart caddy

sleep 3
if systemctl is-active -q stage-scraper.service && curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then
    echo "Le site répond sur le serveur."
else
    echo "Le site ne répond pas : sudo journalctl -u stage-scraper -n 50" >&2
fi
[[ -f $APP/.env ]] || echo "Rappel : pas encore de .env dans $APP (clés Gemini, SerpApi, Careerjet, Gmail)."

cat <<EOF

C'est installé. Adresse du site : https://$DOMAINE
(le premier certificat HTTPS peut prendre une minute ; dans la console Oracle, les ports 80 et 443 doivent
être ouverts dans la « security list » du réseau).

Commandes utiles :
  sudo systemctl status stage-scraper                 état du site
  sudo journalctl -u stage-scraper -f                 journal du site en direct
  sudo journalctl -u stage-scraper-auto -n 100        journal du dernier passage de 8 h
  sudo systemctl start stage-scraper-auto             lancer un passage tout de suite
  sudo systemctl start stage-scraper-sauvegarde       sauvegarder tout de suite ($APP/data/sauvegardes/auto)
  systemctl list-timers 'stage-scraper-*'             prochaines exécutions
EOF
