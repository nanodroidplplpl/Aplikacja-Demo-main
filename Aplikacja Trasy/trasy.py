#!/usr/bin/env python3
"""Kliknij mapę: dodaj punkt trasy wybranego drona. Zapisz do Aplikacja Sterowanie/trasy.json."""

import json
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QImage, QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsPixmapItem
from pyqtgraph.Qt import QtCore, QtWidgets
import pyqtgraph as pg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Aplikacja Host"))
import osm
from host import to_en, to_latlon

START_LAT, START_LON = 52.2520, 20.9050
HALF_M = 200.0
ALT_M = 20.0
JSON_PATH = Path(__file__).resolve().parents[1] / "Aplikacja Sterowanie" / "trasy.json"
COLORS = {1: "#3b82f6", 2: "#22c55e", 3: "#f97316"}


class Win(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trasy GUIDED")
        self.resize(900, 800)
        self.routes = {1: [], 2: [], 3: []}
        if JSON_PATH.is_file():
            raw = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            self.routes = {int(k): list(v) for k, v in raw.items()}

        bar = QtWidgets.QHBoxLayout()
        self.drone = QtWidgets.QComboBox()
        for d in (1, 2, 3):
            self.drone.addItem("Dron {}".format(d), d)
        undo = QtWidgets.QPushButton("Cofnij")
        save = QtWidgets.QPushButton("Zapisz JSON")
        undo.clicked.connect(self.undo)
        save.clicked.connect(self.save)
        bar.addWidget(QtWidgets.QLabel("Klik = punkt, PPM = cofnij"))
        bar.addWidget(self.drone)
        bar.addWidget(undo)
        bar.addWidget(save)

        self.map = pg.PlotWidget(title="© OpenStreetMap  —  zapis: {}".format(JSON_PATH))
        self.map.setAspectLocked(True)
        self.map.setXRange(-HALF_M, HALF_M, padding=0)
        self.map.setYRange(-HALF_M, HALF_M, padding=0)
        self.map.scene().sigMouseClicked.connect(self.on_click)

        box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(box)
        col.addLayout(bar)
        col.addWidget(self.map, 1)
        self.setCentralWidget(box)

        got = osm.mosaic(START_LAT, START_LON, 0, 0, HALF_M, to_en, to_latlon)
        if got:
            rgb, west, north, w_m, h_m = got
            rgb = np.ascontiguousarray(rgb)
            h, w = rgb.shape[:2]
            item = QGraphicsPixmapItem(QPixmap.fromImage(
                QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()))
            item.setZValue(-1)
            item.setTransform(QTransform().scale(w_m / w, h_m / h))
            item.setPos(west, north)
            self.map.addItem(item)
        self.draw()

    def on_click(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.RightButton:
            self.undo()
            return
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        p = self.map.plotItem.vb.mapSceneToView(ev.scenePos())
        lat, lon = to_latlon(p.x(), p.y(), START_LAT, START_LON)
        self.routes[self.drone.currentData()].append({"lat": lat, "lon": lon, "alt": ALT_M})
        self.draw()

    def undo(self):
        route = self.routes[self.drone.currentData()]
        if route:
            route.pop()
            self.draw()

    def save(self):
        JSON_PATH.write_text(json.dumps(self.routes, indent=2), encoding="utf-8")
        print("zapisano", JSON_PATH)

    def draw(self):
        for item in list(self.map.listDataItems()):
            self.map.removeItem(item)
        for did, wps in self.routes.items():
            if not wps:
                continue
            pts = [to_en(w["lat"], w["lon"], START_LAT, START_LON) for w in wps]
            self.map.plot([e for e, n in pts], [n for e, n in pts],
                          pen=pg.mkPen(COLORS[did], width=2), symbol="o",
                          symbolBrush=COLORS[did], symbolSize=10)


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    w = Win()
    w.show()
    app.exec()
