"""Kafelki OpenStreetMap. Pobiera tylko to, co widać, i trzyma na dysku."""

import math
import os
import urllib.request
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QImage

TILE = 256
UA = "SpectrumDoA/1.0 (podglad lokalny, nie masowe pobieranie)"
CACHE = Path(__file__).resolve().parent / "osm-cache"
MAX = 2 ** 18 - 1


def zoom_for(lat, half_m):
    span = max(float(half_m) * 2, 40.0)
    for z in range(18, 6, -1):
        if span / (40075016.686 * math.cos(math.radians(lat)) / (2 ** z)) <= 4.0:
            return z
    return 7


def tile_nw(tx, ty, z):
    n = 2 ** z
    lon = tx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n))))
    return lat, lon


def latlon_tile(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = min(0.9999, max(-0.9999, math.sin(math.radians(lat))))
    y = (0.5 - math.log((1.0 + s) / (1.0 - s)) / (4.0 * math.pi)) * n
    return x, y


def _png(data):
    q = QImage.fromData(data).convertToFormat(QImage.Format.Format_RGB888)
    h, w, bpl = q.height(), q.width(), q.bytesPerLine()
    ptr = q.constBits()
    ptr.setsize(bpl * h)
    raw = np.frombuffer(ptr, np.uint8, bpl * h)
    return raw.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3).copy()


def _tile(z, x, y):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "{}-{}-{}.png".format(z, x, y)
    if path.is_file() and path.stat().st_size > 0:
        return _png(path.read_bytes())
    url = "https://tile.openstreetmap.org/{}/{}/{}.png".format(z, x, y)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=6).read()
    path.write_bytes(data)
    return _png(data)


def mosaic(lat0, lon0, cx, cy, half, to_en, to_latlon):
    """Zwraca (obraz RGB, prostokąt w metrach EN) albo None."""
    clat, clon = to_latlon(cx, cy, lat0, lon0)
    z = zoom_for(clat, half)
    xs, ys = [], []
    for e, n in ((cx - half, cy - half), (cx + half, cy - half), (cx - half, cy + half), (cx + half, cy + half)):
        lat, lon = to_latlon(e, n, lat0, lon0)
        x, y = latlon_tile(lat, lon, z)
        xs.append(x)
        ys.append(y)
    x0, x1 = int(math.floor(min(xs))), int(math.floor(max(xs)))
    y0, y1 = int(math.floor(min(ys))), int(math.floor(max(ys)))
    x0, x1 = max(0, x0), min(MAX, x1)
    y0, y1 = max(0, y0), min(MAX, y1)
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    if cols < 1 or rows < 1 or cols * rows > 16:
        return None
    rgb = np.zeros((rows * TILE, cols * TILE, 3), np.uint8)
    for iy, ty in enumerate(range(y0, y1 + 1)):
        for ix, tx in enumerate(range(x0, x1 + 1)):
            try:
                rgb[iy * TILE:(iy + 1) * TILE, ix * TILE:(ix + 1) * TILE] = _tile(z, tx, ty)
            except Exception:
                pass
    nw = tile_nw(x0, y0, z)
    se = tile_nw(x1 + 1, y1 + 1, z)
    west, north = to_en(nw[0], nw[1], lat0, lon0)
    east, south = to_en(se[0], se[1], lat0, lon0)
    return rgb, west, north, east - west, south - north
