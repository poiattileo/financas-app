#!/bin/bash
# ============================================================
#  Atualiza o app no servidor a partir do git (rode AQUI).
#  Uso: sudo bash atualizar.sh
#  Faz: git pull + copia frontend + backend (se mudou) +
#       migrations do banco + restart (se backend mudou).
# ============================================================
set -e
[ "$EUID" -ne 0 ] && { echo "Rode como root: sudo bash atualizar.sh"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "→ git pull..."
sudo -u "${SUDO_USER:-$USER}" git pull 2>/dev/null || git pull

echo "→ copiando frontend para /opt/financas/frontend..."
cp frontend/index.html frontend/manifest.json /opt/financas/frontend/

if ! cmp -s backend/main.py /opt/financas/backend/main.py; then
  echo "→ backend mudou, copiando e reiniciando..."
  cp backend/main.py /opt/financas/backend/
  chown -R www-data:www-data /opt/financas
  systemctl restart financas
  sleep 2
  systemctl is-active financas
else
  echo "→ backend sem mudanças (sem restart)"
  chown -R www-data:www-data /opt/financas/frontend
fi

echo "→ aplicando migrations do banco..."
mysql financas < atualizar_banco.sql

echo ""
echo "OK! Agora limpe o cache do navegador (Ctrl+Shift+R) e teste."
