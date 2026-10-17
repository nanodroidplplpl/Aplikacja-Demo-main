#!/usr/bin/env python3
"""Dron: Pluto (2 kanały RX) -> widmo + namiar DOA -> MQTT.

Pozycja i kurs drona pochodzą z autopilota (MAVLink). Wszystkie ustawienia są
w config.py. Na brokerze publikowany jest jeden JSON na temacie drony/<ID>/dane.
"""

import glob
import json
import math
import os
import stat
import time

import adi
import numpy as np
import paho.mqtt.client as mqtt
from pymavlink import mavutil

import config as cfg

C = 299792458.0


def open_pluto():
    sdr = adi.ad9361(uri=cfg.PLUTO_URI)
    sdr.rx_enabled_channels = [0, 1]
    sdr.sample_rate = int(cfg.SAMPLE_RATE_HZ)
    sdr.rx_rf_bandwidth = int(cfg.RF_BANDWIDTH_HZ)
    sdr.rx_lo = int(cfg.CENTER_FREQ_HZ)
    sdr.gain_control_mode_chan0 = cfg.GAIN_MODE
    sdr.gain_control_mode_chan1 = cfg.GAIN_MODE
    if cfg.GAIN_MODE == "manual":
        sdr.rx_hardwaregain_chan0 = int(cfg.GAIN_RX0_DB)
        sdr.rx_hardwaregain_chan1 = int(cfg.GAIN_RX1_DB)
    sdr.tx_hardwaregain_chan0 = -89
    sdr.tx_hardwaregain_chan1 = -89
    sdr.rx_buffer_size = int(cfg.SAMPLES)
    sdr._rxadc.set_kernel_buffers_count(1)
    for _ in range(10):
        data = sdr.rx()
    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError("Pluto daje jeden kanał RX - uruchom Skrypty/pluto-2r2t.sh")
    return sdr


def read_pair(sdr):
    sdr.rx()  # bufor z poprzedniego obiegu pętli jest nieaktualny
    rx0, rx1 = sdr.rx()
    return rx0, rx1


def usb_vendor(port):
    """idVendor z sysfs, albo pusty napis gdy port nie jest USB."""
    path = os.path.realpath("/sys/class/tty/{}/device".format(os.path.basename(port)))
    for _ in range(6):
        vendor = os.path.join(path, "idVendor")
        if os.path.isfile(vendor):
            with open(vendor) as f:
                return f.read().strip().lower()
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return ""


def list_serial_ports():
    """Prawdziwe porty szeregowe. Konsola Pluto (USB 0456) odpada, Pixhawk na początku."""
    ports, seen = [], set()
    for path in sorted(
        p for pat in ("ttyACM*", "ttyUSB*", "ttyAMA*", "ttyS[0-9]*", "ttyTHS*", "serial[0-9]*")
        for p in glob.glob("/dev/" + pat)
    ):
        try:
            mode = os.stat(path).st_mode
        except OSError:
            continue
        if not stat.S_ISCHR(mode):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        name = ""
        for link in glob.glob("/dev/serial/by-id/*"):
            if os.path.realpath(link) == real:
                name = os.path.basename(link).lower()
        vendor = usb_vendor(path)
        if vendor == "0456" or "pluto" in name or "analog" in name:
            print("[dron {}] pomijam {} (konsola Pluto)".format(cfg.DRONE_ID, path))
            continue
        seen.add(real)
        ports.append(path)
    ports.sort(key=lambda p: 0 if usb_vendor(p) in ("26ac", "2dae", "3162", "1209") else 1)
    return ports


def _close(mav):
    if mav is None:
        return
    try:
        mav.close()
    except Exception:
        pass


def probe_autopilot(port, baud):
    """Otwiera port i czeka na HEARTBEAT pojazdu (nie GCS). None = cisza, wyjątek = USB."""
    mav = mavutil.mavlink_connection(port, baud=baud, source_system=255, autoreconnect=False)
    try:
        mav.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        deadline = time.time() + 4
        while time.time() < deadline:
            msg = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if msg is None:
                continue
            if msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_INVALID:
                continue
            if msg.type == mavutil.mavlink.MAV_TYPE_GCS:
                continue
            return mav
    except Exception:
        _close(mav)
        raise
    _close(mav)
    return None


def open_autopilot():
    """Szuka HEARTBEAT pojazdu. Błąd USB na porcie = ponowienie, nie rezygnacja."""
    if not cfg.MAVLINK_DEVICE:
        return None
    ports = [cfg.MAVLINK_DEVICE] if cfg.MAVLINK_DEVICE != "auto" else list_serial_ports()
    print("[dron {}] szukam autopilota na: {}".format(cfg.DRONE_ID, ", ".join(ports) or "brak"))
    for port in ports:
        for baud in cfg.MAVLINK_BAUDS:
            for attempt in range(1, 4):
                try:
                    mav = probe_autopilot(port, baud)
                except Exception as exc:
                    print("[dron {}] {} {} bd próba {}: {} — ponawiam".format(
                        cfg.DRONE_ID, port, baud, attempt, exc))
                    time.sleep(1)
                    continue
                if mav is not None:
                    print("[dron {}] autopilot na {} ({} bd)".format(cfg.DRONE_ID, port, baud))
                    return mav
                print("[dron {}] {} {} bd: brak heartbeat pojazdu".format(cfg.DRONE_ID, port, baud))
                break
    raise RuntimeError("Nie znaleziono autopilota na portach: {}".format(", ".join(ports) or "brak"))


def read_autopilot(mav, pos):
    """Odbiera zaległe wiadomości MAVLink i aktualizuje pozycję."""
    if mav is None:
        pos.update(lat=cfg.FIXED_LAT, lon=cfg.FIXED_LON, alt=0.0,
                   heading=cfg.FIXED_HEADING_DEG, t=time.time())
        return
    while True:
        msg = mav.recv_match(type=["HEARTBEAT", "GLOBAL_POSITION_INT"], blocking=False)
        if msg is None:
            return
        if msg.get_type() == "GLOBAL_POSITION_INT":
            pos.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt=msg.relative_alt / 1000.0,
                       heading=None if msg.hdg == 65535 else msg.hdg / 100.0, t=time.time())
        elif msg.get_srcComponent() == 1 and time.time() - pos["t"] > 3.0:
            # Autopilot nie przysyła pozycji - prosimy o GLOBAL_POSITION_INT co 0.2 s.
            mav.mav.command_long_send(
                msg.get_srcSystem(), 1, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 200000, 0, 0, 0, 0, 0)


def measure(rx0, rx1):
    """Widmo kanału RX1 [dBFS] i różnica fazy RX2-RX1 w oknie emitera."""
    n = cfg.NFFT
    frames = len(rx0) // n
    win = np.hanning(n)
    x0 = np.fft.fft(rx0[:frames * n].reshape(frames, n) * win, axis=1)
    x1 = np.fft.fft(rx1[:frames * n].reshape(frames, n) * win, axis=1)
    power = np.fft.fftshift(np.mean(np.abs(x0) ** 2, axis=0))
    cross = np.fft.fftshift(np.mean(x1 * np.conj(x0), axis=0))
    psd_db = 10 * np.log10(power / (2048.0 * np.sum(win)) ** 2 + 1e-20)
    freqs = cfg.CENTER_FREQ_HZ + np.fft.fftshift(np.fft.fftfreq(n, 1.0 / cfg.SAMPLE_RATE_HZ))

    band = np.abs(freqs - cfg.TARGET_FREQ_HZ) <= cfg.TARGET_BW_HZ / 2
    if not band.any():
        return psd_db, None
    snr_db = float(np.max(psd_db[band]) - np.median(psd_db))
    phase_raw = float(np.degrees(np.angle(np.sum(cross[band]))))
    return psd_db, {"snr_db": snr_db, "phase_raw_deg": phase_raw}


def bearing(doa, heading):
    """Dwa możliwe azymuty emitera (para anten nie rozróżnia stron swojej linii)."""
    phase = (doa["phase_raw_deg"] - cfg.PHASE_CAL_DEG + 180.0) % 360.0 - 180.0
    wavelength = C / cfg.TARGET_FREQ_HZ
    cos_rel = math.radians(phase) * wavelength / (2 * math.pi * cfg.ANTENNA_SPACING_M)
    rel = math.degrees(math.acos(max(-1.0, min(1.0, cos_rel))))
    doa["phase_deg"] = phase
    doa["angle_deg"] = 90.0 - rel  # kąt od kierunku "na wprost" anten
    doa["valid"] = heading is not None and doa["snr_db"] >= cfg.SNR_MIN_DB
    if heading is not None:
        baseline = heading + cfg.BASELINE_OFFSET_DEG
        doa["azimuths"] = [(baseline + rel) % 360.0, (baseline - rel) % 360.0]
    return doa


def send_guided(mav, lat, lon, alt):
    mav.set_mode_apm("GUIDED")
    mav.mav.set_position_target_global_int_send(
        0, mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        0b0000111111111000,
        int(round(lat * 1e7)), int(round(lon * 1e7)), float(alt),
        0, 0, 0, 0, 0, 0, 0, 0)


def main():
    print("[dron {}] start, broker {}:{}".format(cfg.DRONE_ID, cfg.BROKER, cfg.BROKER_PORT))
    mav = open_autopilot()
    sdr = open_pluto()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dron-{}".format(cfg.DRONE_ID))
    client.max_queued_messages_set(10)
    guided = {"pt": None}
    last_guided = None

    def on_connect(c, *_):
        c.subscribe("drony/{}/guided".format(cfg.DRONE_ID))

    def on_message(c, u, m):
        try:
            d = json.loads(m.payload)
            guided["pt"] = (float(d["lat"]), float(d["lon"]), float(d.get("alt", 20)))
        except (ValueError, KeyError, TypeError):
            pass

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(cfg.BROKER, cfg.BROKER_PORT, keepalive=30)
    client.loop_start()  # łączy się i wznawia połączenie samo, w tle
    topic = "drony/{}/dane".format(cfg.DRONE_ID)
    pos = {"lat": None, "lon": None, "alt": None, "heading": None, "t": 0.0}

    while True:
        t0 = time.monotonic()
        rx0, rx1 = read_pair(sdr)
        read_autopilot(mav, pos)
        pt = guided["pt"]
        if mav is not None and pt is not None and pt != last_guided:
            send_guided(mav, *pt)
            last_guided = pt
            print("[dron {}] GUIDED {:.6f} {:.6f} {:.0f} m".format(cfg.DRONE_ID, *pt))
        fresh = time.time() - pos["t"] < 3.0
        psd_db, doa = measure(rx0, rx1)
        if doa is not None:
            doa = bearing(doa, pos["heading"] if fresh else None)

        client.publish(topic, json.dumps({
            "id": cfg.DRONE_ID,
            "t": time.time(),
            "lat": pos["lat"] if fresh else None,
            "lon": pos["lon"] if fresh else None,
            "alt": pos["alt"] if fresh else None,
            "heading": pos["heading"] if fresh else None,
            "fc": cfg.CENTER_FREQ_HZ,
            "fs": cfg.SAMPLE_RATE_HZ,
            "target": cfg.TARGET_FREQ_HZ,
            "target_bw": cfg.TARGET_BW_HZ,
            "gain": [cfg.GAIN_RX0_DB, cfg.GAIN_RX1_DB],
            "psd": np.round(psd_db).astype(int).tolist(),
            "doa": doa,
        }))

        status = "brak pozycji" if not fresh else "{:.6f} {:.6f} kurs {}".format(
            pos["lat"], pos["lon"], pos["heading"])
        if doa is not None:
            status += " | SNR {:.0f} dB faza surowa {:+.1f} po kal. {:+.1f} kąt {:+.1f}".format(
                doa["snr_db"], doa["phase_raw_deg"], doa["phase_deg"], doa["angle_deg"])
        print("[dron {}] {}{}".format(cfg.DRONE_ID, status, "" if client.is_connected() else " | MQTT rozłączony"))

        time.sleep(max(0.0, 1.0 / cfg.RATE_HZ - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
