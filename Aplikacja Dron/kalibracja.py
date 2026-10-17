#!/usr/bin/env python3
"""Kalibracja fazy RX2-RX1. Emiter ustaw na wprost anten (prostopadle do ich linii).

Najpierw zatrzymaj usługę: sudo systemctl stop dron
"""

import numpy as np

import config as cfg
from dron import measure, open_pluto, read_pair

sdr = open_pluto()
phases = []
while len(phases) < 40:
    psd_db, doa = measure(*read_pair(sdr))
    if doa is None:
        raise SystemExit("TARGET_FREQ_HZ leży poza podglądanym widmem - popraw config.py")
    print("SNR {:5.1f} dB   faza surowa {:+7.1f}°".format(doa["snr_db"], doa["phase_raw_deg"]))
    if doa["snr_db"] >= cfg.SNR_MIN_DB:
        phases.append(np.radians(doa["phase_raw_deg"]))

vector = np.mean(np.exp(1j * np.array(phases)))
spread = np.degrees(np.sqrt(-2 * np.log(min(abs(vector), 1.0))))
print("\nWpisz do config.py:  PHASE_CAL_DEG = {:.1f}   (rozrzut ±{:.1f}°)".format(
    np.degrees(np.angle(vector)), spread))
