#!/usr/bin/env bash
# Smoke no Steam Deck: instala o zip, reinicia o Decky e mostra o log.
# Uso: bash tools/deck_smoke.sh [store|sideload]
set -euo pipefail

EDITION="${1:-sideload}"
DECK="${DECK_HOST:-steamdeck.local}"
ZIP="out/${EDITION}.zip"
REMOTE="/home/deck/homebrew/plugins/translate-deck"

if [[ ! -f "$ZIP" ]]; then
  echo "erro: $ZIP nao existe; rode plugin/scripts/build.py --edition $EDITION" >&2
  exit 1
fi

echo "== enviando $ZIP para $DECK"
ssh "$DECK" "rm -rf '$REMOTE' && mkdir -p '$REMOTE'"
scp "$ZIP" "$DECK:/tmp/translate-deck.zip"
ssh "$DECK" "command -v unzip >/dev/null || (echo 'unzip ausente no Deck' && exit 1)"
ssh "$DECK" "unzip -o -q /tmp/translate-deck.zip -d '$REMOTE' && rm /tmp/translate-deck.zip"

echo "== reiniciando o Decky"
ssh "$DECK" "sudo systemctl restart plugin_loader.service"
sleep 4
ssh "$DECK" "systemctl is-active plugin_loader.service"

echo "== log do plugin (Ctrl+C para sair)"
ssh -t "$DECK" "journalctl -u plugin_loader.service -f -n 120 | grep -iE 'translate|tdeck|decky'"
