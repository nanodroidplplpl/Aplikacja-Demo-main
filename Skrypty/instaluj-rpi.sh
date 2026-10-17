#!/bin/bash
# Jednorazowa instalacja na Raspberry Pi (Raspberry Pi OS Bookworm).
# Użycie:  sudo bash instaluj-rpi.sh <ID_SIECI_ZEROTIER>
set -e
NETWORK_ID="$1"
USER_NAME="${SUDO_USER:-pi}"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/../Aplikacja Dron" && pwd)"

echo "== Pakiety systemowe (libiio do Pluto, numpy)"
apt-get update
apt-get install -y python3-venv python3-numpy python3-libiio libiio-utils curl

echo "== Środowisko Python w $APP/.venv"
sudo -u "$USER_NAME" python3 -m venv --system-site-packages "$APP/.venv"
sudo -u "$USER_NAME" "$APP/.venv/bin/pip" install "paho-mqtt>=2.0" pymavlink
sudo -u "$USER_NAME" "$APP/.venv/bin/pip" install --no-deps pyadi-iio  # libiio jest z apt

echo "== Dostęp do portu szeregowego autopilota"
usermod -aG dialout "$USER_NAME"

if [ -n "$NETWORK_ID" ]; then
  echo "== ZeroTier"
  command -v zerotier-cli >/dev/null || curl -s https://install.zerotier.com | bash
  zerotier-cli join "$NETWORK_ID"
  echo "Autoryzuj w my.zerotier.com urządzenie o ID: $(zerotier-cli info | cut -d' ' -f3)"
fi

echo "== Autostart (dron.service)"
sed -i 's/\r$//' "$HERE/start-dron.sh"  # końce linii z Windows psują skrypty bash
sed -e 's/\r$//' -e "s|UZYTKOWNIK|$USER_NAME|" -e "s|SKRYPT|$HERE/start-dron.sh|" \
  "$HERE/dron.service" > /etc/systemd/system/dron.service
systemctl daemon-reload
systemctl enable dron.service

echo
echo "Gotowe. Ustaw DRONE_ID w: $APP/config.py"
echo "Potem: sudo reboot   (podgląd pracy: journalctl -fu dron)"
