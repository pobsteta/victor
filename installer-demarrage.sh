#!/usr/bin/env bash
# Lance VICTOR automatiquement à l'ouverture de ta session (Linux, systemd).
#
#   ./installer-demarrage.sh                 installe et démarre tout de suite
#   ./installer-demarrage.sh --desinstaller  retire le démarrage automatique
#
# Ce que ça crée :
#   ~/.config/systemd/user/victor.service   le serveur, relancé s'il plante
#   ~/.config/autostart/victor.desktop      ouvre la page dans ton navigateur
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONF/systemd/user"
AUTO_DIR="$CONF/autostart"
UNIT="$UNIT_DIR/victor.service"
DESKTOP="$AUTO_DIR/victor.desktop"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v systemctl >/dev/null || die "systemd introuvable : ce script est prévu pour Linux avec systemd."

# ------------------------------------------------------------------ désinstallation
if [ "${1:-}" = "--desinstaller" ] || [ "${1:-}" = "--uninstall" ]; then
  systemctl --user disable --now victor.service 2>/dev/null || true
  rm -f "$UNIT" "$DESKTOP"
  systemctl --user daemon-reload
  ok "VICTOR ne démarrera plus automatiquement (tes fichiers et ton .env sont intacts)."
  exit 0
fi

echo
echo "Installation du démarrage automatique de VICTOR"
echo "  dossier : $DIR"
echo

# ------------------------------------------------------------------ vérifications
[ -f "$DIR/server.py" ] || die "server.py introuvable : lance ce script depuis le dossier victor-local."

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do [ -x "$c" ] && UV="$c" && break; done
fi
[ -n "$UV" ] || die "uv introuvable. Installe-le d'abord (voir README, étape 0)."
ok "uv : $UV"

PATH_DIRS="$(dirname "$UV")"
CLAUDE="$(command -v claude || true)"
if [ -n "$CLAUDE" ]; then
  ok "claude : $CLAUDE"
  PATH_DIRS="$PATH_DIRS:$(dirname "$CLAUDE")"
else
  warn "commande 'claude' introuvable : VICTOR démarrera, mais les tâches Claude Code échoueront."
fi
NODE="$(command -v node || true)"   # claude est un script Node : node doit être dans le PATH du service
[ -n "$NODE" ] && PATH_DIRS="$PATH_DIRS:$(dirname "$NODE")"
PATH_DIRS="$PATH_DIRS:/usr/local/bin:/usr/bin:/bin"
PATH_DIRS="$(printf '%s' "$PATH_DIRS" | tr ':' '\n' | awk '!seen[$0]++' | paste -sd: -)"

if [ -f "$DIR/.env" ]; then
  ok ".env présent"
  grep -qE '^GRADIUM_API_KEY=.+' "$DIR/.env" || warn "GRADIUM_API_KEY vide dans .env"
  grep -qE '^ANTHROPIC_API_KEY=.+' "$DIR/.env" || warn "ANTHROPIC_API_KEY vide dans .env"
else
  warn ".env absent : copie .env.example vers .env et mets tes clés, puis : systemctl --user restart victor"
fi

PORT="$(grep -E '^VICTOR_PORT=' "$DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' "'"'" || true)"
PORT="${PORT:-8788}"

# Rattacher le service à la session graphique quand elle est gérée par systemd :
# VICTOR peut alors ouvrir tes applications et ton navigateur.
if systemctl --user is-active --quiet graphical-session.target 2>/dev/null; then
  TARGET="graphical-session.target"
  AFTER="graphical-session.target network-online.target"
  PARTOF="PartOf=graphical-session.target"
else
  TARGET="default.target"
  AFTER="network-online.target"
  PARTOF=""
  warn "session graphique non gérée par systemd : VICTOR démarrera avec ta session,"
  warn "mais l'ouverture d'applications pourrait ne pas fonctionner."
fi

# ------------------------------------------------------------------ fichiers
mkdir -p "$UNIT_DIR" "$AUTO_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=VICTOR - assistant vocal local
After=$AFTER
$PARTOF

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart="$UV" run server.py
Restart=on-failure
RestartSec=5
Environment="PATH=$PATH_DIRS"
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=$TARGET
EOF
ok "service créé : $UNIT"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=VICTOR
Comment=Ouvre l'interface de VICTOR
Exec=sh -c "sleep 6 && xdg-open http://127.0.0.1:$PORT"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
ok "ouverture automatique de la page : $DESKTOP"

# ------------------------------------------------------------------ activation
systemctl --user daemon-reload
systemctl --user enable --now victor.service >/dev/null 2>&1 || systemctl --user enable --now victor.service
ok "service activé"

printf '  … démarrage (le premier lancement installe les dépendances)'
for _ in $(seq 1 60); do
  if command -v curl >/dev/null && curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
    echo; ok "VICTOR répond sur http://127.0.0.1:$PORT"; break
  fi
  if ! systemctl --user is-active --quiet victor.service; then
    echo; die "le service s'est arrêté. Regarde : journalctl --user -u victor -n 50"
  fi
  printf '.'; sleep 1
done
echo

cat <<EOF

Terminé. À chaque ouverture de session, VICTOR démarre et sa page s'ouvre.
Il te restera à cliquer sur l'orbe (le navigateur l'exige pour le micro).

  État       : systemctl --user status victor
  Messages   : journalctl --user -u victor -f
  Redémarrer : systemctl --user restart victor   (après une modif de .env)
  Retirer    : ./installer-demarrage.sh --desinstaller

EOF
