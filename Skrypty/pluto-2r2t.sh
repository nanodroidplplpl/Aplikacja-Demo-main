#!/bin/bash
# Jednorazowo na każde Pluto: włącza drugi kanał RX (AD9361, tryb 2r2t). Hasło: analog
# Pluto zapamiętuje ustawienie i restartuje się. Sprawdzenie: iio_attr -u ip:192.168.2.1 -C
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.2.1 \
  "fw_setenv attr_name compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361; fw_setenv mode 2r2t; reboot"
