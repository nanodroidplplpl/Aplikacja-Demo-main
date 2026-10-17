#!/usr/bin/env python3
"""Host: podgląd widma z dronów i lokalizacja emitera z ich namiarów DOA.

Broker MQTT (Mosquitto) działa na tym komputerze, drony łączą się z nim przez ZeroTier.
"""

import itertools
import json
import math
import queue
import sys
import threading
import time

import numpy as np
import paho.mqtt.client as mqtt
import pyqtgraph as pg
from PyQt6.QtGui import QImage, QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsPixmapItem
from pyqtgraph.Qt import QtCore, QtWidgets

pg.setConfigOptions(imageAxisOrder="row-major")

import osm

BROKER = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"  # python host.py <IP_BROKERA>
BROKER_PORT = 1883
DRONES = [1, 2, 3]
HISTORY = 300           # wierszy spektrogramu (~2,5 min przy 2 Hz)
STALE_S = 3.0           # dane starsze niż to są pomijane
MAP_HALF_M = 75.0       # mapa: ±75 m od środka grupy dronów
TRACKING = True         # False = tylko bieżący namiar, bez śladu i uśredniania
TRACK_N = 25            # ile ostatnich namiarów uśredniać
TRACK_JUMP_M = 80.0     # skok większy niż to jest odrzucany jako pomyłka
DB_RANGE = (-80, -10)   # zakres osi widma i kolorów spektrogramu [dBFS]
COLORS = ["#3b82f6", "#22c55e", "#f97316"]
EARTH_R = 6378137.0


def to_en(lat, lon, lat0, lon0):
    """Metry na wschód i na północ od punktu odniesienia."""
    east = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    north = math.radians(lat - lat0) * EARTH_R
    return east, north


def to_latlon(east, north, lat0, lon0):
    lat = lat0 + math.degrees(north / EARTH_R)
    lon = lon0 + math.degrees(east / (EARTH_R * math.cos(math.radians(lat0))))
    return lat, lon


def intersect(rays):
    """Punkt najbliższy półprostym (wschód, północ, azymut) i błąd RMS w metrach.

    None, gdy proste są prawie równoległe albo punkt wypada za którymś dronem.
    """
    normals = np.array([[math.cos(math.radians(az)), -math.sin(math.radians(az))] for _, _, az in rays])
    offsets = np.array([nx * e + ny * n for (nx, ny), (e, n, _) in zip(normals, rays)])
    if np.linalg.svd(normals, compute_uv=False)[-1] < 0.05:
        return None
    x, y = np.linalg.lstsq(normals, offsets, rcond=None)[0]
    for e, n, az in rays:
        if (x - e) * math.sin(math.radians(az)) + (y - n) * math.cos(math.radians(az)) < 0:
            return None
    return (x, y), float(np.sqrt(np.mean((normals @ (x, y) - offsets) ** 2)))


def locate(fixes):
    """fixes: [(lat, lon, [azymut_a, azymut_b]), ...]. Wybiera zestaw azymutów o najmniejszym błędzie."""
    lat0, lon0 = fixes[0][0], fixes[0][1]
    points = [to_en(lat, lon, lat0, lon0) for lat, lon, _ in fixes]
    best = None
    for combo in itertools.product(*[azimuths for _, _, azimuths in fixes]):
        hit = intersect([(e, n, az) for (e, n), az in zip(points, combo)])
        if hit and (best is None or hit[1] < best[1]):
            best = (hit[0], hit[1], combo)
    if best is None:
        return None
    lat, lon = to_latlon(best[0][0], best[0][1], lat0, lon0)
    return {"lat": lat, "lon": lon, "rms_m": best[1], "azimuths": best[2]}


class DronePanel:
    """Widmo i spektrogram jednego drona."""

    def __init__(self, layout, row, drone_id, color):
        self.drone_id = drone_id
        self.last = None
        self.rx_time = 0.0
        self.image = None
        self._axis = None
        self._title = ""
        self.spec = layout.addPlot(row=2 * row, col=0, title="Dron {}: brak danych".format(drone_id))
        self.spec.setLabel("left", "dBFS")
        self.spec.setYRange(*DB_RANGE)
        self.spec.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.spec.plot(pen=pg.mkPen(color, width=1))
        self.band = pg.LinearRegionItem(movable=False, brush=(255, 0, 0, 50))
        self.spec.addItem(self.band)
        self.water = layout.addPlot(row=2 * row + 1, col=0)
        self.water.setLabel("bottom", "MHz")
        self.water.hideAxis("left")
        self.water.setXLink(self.spec)
        self.water.setYRange(0, HISTORY, padding=0)
        self.water.disableAutoRange(axis="y")
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setColorMap(pg.colormap.get("viridis"))
        self.water.addItem(self.img)
        layout.ci.layout.setRowStretchFactor(2 * row, 2)
        layout.ci.layout.setRowStretchFactor(2 * row + 1, 3)

    def update(self, msg):
        self.last = msg
        self.rx_time = time.time()
        psd = np.array(msg["psd"], dtype=float)
        mhz = (msg["fc"] + (np.arange(len(psd)) - len(psd) / 2) * msg["fs"] / len(psd)) / 1e6
        self.curve.setData(mhz, psd)
        half = msg["target_bw"] / 2
        self.band.setRegion(((msg["target"] - half) / 1e6, (msg["target"] + half) / 1e6))
        if self.image is None or self.image.shape[1] != len(psd):
            self.image = np.full((HISTORY, len(psd)), float(np.median(psd)), dtype=float)
        self.image = np.roll(self.image, -1, axis=0)
        self.image[-1] = psd
        self.img.setImage(self.image, autoLevels=False, levels=DB_RANGE)
        axis = (float(mhz[0]), float(mhz[-1]))
        if axis != self._axis:
            self._axis = axis
            self.img.setRect(QtCore.QRectF(mhz[0], 0, mhz[-1] - mhz[0], HISTORY))
            self.water.setYRange(0, HISTORY, padding=0)

    def live(self):
        return self.last is not None and time.time() - self.rx_time < STALE_S

    def refresh_title(self):
        if self.last is None:
            return
        msg = self.last
        text = "Dron {} | {:.3f} MHz | gain {}/{} dB | {:.1f} s temu".format(
            self.drone_id, msg["fc"] / 1e6, msg["gain"][0], msg["gain"][1], time.time() - self.rx_time)
        doa = msg["doa"]
        if doa:
            text += " | SNR {:.0f} dB | faza surowa {:+.1f}° | kąt {:+.1f}°".format(
                doa["snr_db"], doa["phase_raw_deg"], doa["angle_deg"])
        if msg["lat"] is None:
            text += " | BRAK POZYCJI"
        if text != self._title:
            self._title = text
            self.spec.setTitle(text)


class Window(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitoring widma i lokalizacja emitera")
        self.resize(1600, 950)
        self.inbox = queue.Queue()

        split = QtWidgets.QSplitter()
        self.setCentralWidget(split)
        spectra = pg.GraphicsLayoutWidget()
        split.addWidget(spectra)
        self.panels = {d: DronePanel(spectra, i, d, COLORS[i % 3]) for i, d in enumerate(DRONES)}

        right = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(right)
        self.map = pg.PlotWidget(title="Mapa [m]  © OpenStreetMap")
        self.map.setBackground("#d0d0d0")
        self.map.setAspectLocked(True)
        self.map.showGrid(x=True, y=True, alpha=0.15)
        self.map.disableAutoRange()
        self.osm_item = QGraphicsPixmapItem()
        self.osm_item.setZValue(-1)
        self.osm_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        self.map.addItem(self.osm_item)
        self._marks = []
        self._osm = None
        self._osm_shown = None
        self._osm_key = None
        self._osm_busy = False
        self.map_half = MAP_HALF_M
        self.scale_label = QtWidgets.QLabel("Skala ±{} m".format(int(self.map_half)))
        self.scale = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.scale.setRange(20, 2000)
        self.scale.setValue(int(self.map_half))
        self.scale.valueChanged.connect(self._on_scale)
        self.track = []
        self.tracked = None
        scale_row = QtWidgets.QHBoxLayout()
        scale_row.addWidget(self.scale_label)
        scale_row.addWidget(self.scale, 1)
        if TRACKING:
            self.track_clear = QtWidgets.QPushButton("Wyczyść ślad")
            self.track_clear.clicked.connect(self._clear_track)
            scale_row.addWidget(self.track_clear)
        self.result = QtWidgets.QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result.setStyleSheet("font-size: 16px; padding: 6px;")
        column.addWidget(self.map, 1)
        column.addLayout(scale_row)
        column.addWidget(self.result)
        split.addWidget(right)
        split.setSizes([950, 650])

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = lambda client, *_: client.subscribe("drony/+/dane")
        self.mqtt.on_message = lambda client, userdata, m: self.inbox.put(m.payload)
        self.mqtt.connect_async(BROKER, BROKER_PORT)
        self.mqtt.loop_start()  # łączy się i wznawia połączenie samo, w tle

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def _on_scale(self, meters):
        self.map_half = float(meters)
        self.scale_label.setText("Skala ±{} m".format(meters))

    def _clear_track(self):
        self.track = []
        self.tracked = None

    def _update_track(self, found):
        """Uśrednia ostatnie pozycje emitera. None, gdy tracking jest wyłączony."""
        if not TRACKING:
            return None
        if found is None:
            return self.tracked
        if self.track:
            e, n = to_en(found["lat"], found["lon"], self.track[-1][0], self.track[-1][1])
            if math.hypot(e, n) > TRACK_JUMP_M:
                return self.tracked
        self.track.append((found["lat"], found["lon"]))
        self.track = self.track[-TRACK_N:]
        lat0, lon0 = self.track[0]
        pts = [to_en(lat, lon, lat0, lon0) for lat, lon in self.track]
        east = sum(p[0] for p in pts) / len(pts)
        north = sum(p[1] for p in pts) / len(pts)
        lat, lon = to_latlon(east, north, lat0, lon0)
        self.tracked = {"lat": lat, "lon": lon}
        return self.tracked

    def _wipe_marks(self):
        for item in self._marks:
            self.map.removeItem(item)
        self._marks = []

    def _mark(self, item):
        self._marks.append(item)
        return item

    def _paint_osm(self):
        if self._osm is None or self._osm is self._osm_shown:
            return
        rgb, west, north, width_m, height_m = self._osm
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.osm_item.setPixmap(QPixmap.fromImage(qimg))
        self.osm_item.setTransform(QTransform().scale(width_m / w, height_m / h))
        self.osm_item.setPos(west, north)
        self._osm_shown = self._osm

    def _want_osm(self, lat0, lon0, cx, cy, half):
        step = max(15.0, half * 0.3)
        z = osm.zoom_for(to_latlon(cx, cy, lat0, lon0)[0], half)
        key = (round(lat0, 4), round(lon0, 4), round(cx / step), round(cy / step), z)
        if key == self._osm_key or self._osm_busy:
            return
        self._osm_busy = True
        threading.Thread(target=self._load_osm, args=(lat0, lon0, cx, cy, half, key), daemon=True).start()

    def _load_osm(self, lat0, lon0, cx, cy, half, key):
        try:
            got = osm.mosaic(lat0, lon0, cx, cy, half, to_en, to_latlon)
            if got is not None:
                self._osm = got
                self._osm_key = key
        except Exception:
            pass
        self._osm_busy = False

    def tick(self):
        latest = {}
        while not self.inbox.empty():
            try:
                msg = json.loads(self.inbox.get_nowait())
            except ValueError:
                continue
            if msg.get("id") in self.panels:
                latest[msg["id"]] = msg
        for msg in latest.values():
            self.panels[msg["id"]].update(msg)
        for panel in self.panels.values():
            panel.refresh_title()
        self.draw_map()

    def draw_map(self):
        self._wipe_marks()
        live = [p.last for p in self.panels.values() if p.live() and p.last["lat"] is not None]
        if not live:
            state = "połączony z brokerem" if self.mqtt.is_connected() else \
                "BRAK połączenia z brokerem {}:{}".format(BROKER, BROKER_PORT)
            self.result.setText("MQTT {} - czekam na pozycje dronów".format(state))
            return

        fixes = [m for m in live if m["doa"] and m["doa"]["valid"]]
        found = locate([(m["lat"], m["lon"], m["doa"]["azimuths"]) for m in fixes]) if len(fixes) >= 2 else None
        lat0, lon0 = live[0]["lat"], live[0]["lon"]
        placed = [(m, *to_en(m["lat"], m["lon"], lat0, lon0)) for m in live]
        cx = sum(e for _, e, _ in placed) / len(placed)
        cy = sum(n for _, _, n in placed) / len(placed)
        half = self.map_half
        self.map.setXRange(cx - half, cx + half, padding=0)
        self.map.setYRange(cy - half, cy + half, padding=0)
        self._paint_osm()
        self._want_osm(lat0, lon0, cx, cy, half)
        tracked = self._update_track(found)
        if found:
            e0, n0 = to_en(found["lat"], found["lon"], lat0, lon0)

        for m, e, n in placed:
            color = COLORS[DRONES.index(m["id"]) % 3]
            if m.get("heading") is not None:
                nose = max(8.0, 0.16 * half)
                he = e + nose * math.sin(math.radians(m["heading"]))
                hn = n + nose * math.cos(math.radians(m["heading"]))
                self._mark(self.map.plot([e, he], [n, hn], pen=pg.mkPen(color, width=4)))
            self._mark(self.map.plot([e], [n], pen=None, symbol="o", symbolBrush=color, symbolSize=12))
            label = pg.TextItem("D{}".format(m["id"]), color=color)
            label.setPos(e, n)
            self.map.addItem(label)
            self._mark(label)
            azimuths = (m.get("doa") or {}).get("azimuths") or []
            chosen = found["azimuths"][fixes.index(m)] if found and m in fixes else None
            for az in azimuths:
                style = QtCore.Qt.PenStyle.SolidLine if az == chosen else QtCore.Qt.PenStyle.DashLine
                end_e = e + 2 * half * math.sin(math.radians(az))
                end_n = n + 2 * half * math.cos(math.radians(az))
                self._mark(self.map.plot([e, end_e], [n, end_n], pen=pg.mkPen(color, width=2, style=style)))

        if TRACKING and self.track:
            trail = [to_en(lat, lon, lat0, lon0) for lat, lon in self.track]
            self._mark(self.map.plot(
                [p[0] for p in trail], [p[1] for p in trail],
                pen=pg.mkPen("#ef4444", width=2), symbol="o", symbolBrush="#fca5a5", symbolSize=6))
        if found:
            self._mark(self.map.plot([e0], [n0], pen=None, symbol="star", symbolBrush="#f97316", symbolSize=14))
        if tracked:
            te, tn = to_en(tracked["lat"], tracked["lon"], lat0, lon0)
            self._mark(self.map.plot([te], [tn], pen=None, symbol="star", symbolBrush="r", symbolSize=26))
            self.result.setText(
                "Tracking: {:.6f}, {:.6f}   ślad {} pkt   namiary: {}".format(
                    tracked["lat"], tracked["lon"], len(self.track), len(fixes)))
        elif found:
            note = "  (tylko 2 namiary - wynik niepewny)" if len(fixes) == 2 else ""
            self.result.setText("Emiter: {:.6f}, {:.6f}   błąd dopasowania {:.1f} m   namiary: {}{}".format(
                found["lat"], found["lon"], found["rms_m"], len(fixes), note))
        else:
            self.result.setText("Ważne namiary: {} - potrzeba co najmniej 2 (najlepiej 3)".format(len(fixes)))


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    window = Window()
    window.show()
    pg.exec()
