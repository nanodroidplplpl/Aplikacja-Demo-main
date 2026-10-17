#!/usr/bin/env python3
"""Czyta trasy.json i podaje ten sam numer punktu wszystkim dronom.

Kolejny punkt (2, 3, …) leci dopiero, gdy wszystkie drony dolecą do bieżącego.
"""

import json
import math
import time
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
BROKER_PORT = 1883
TRASY = Path(__file__).resolve().parent / "trasy.json"
ARRIVE_M = 8.0          # w tym promieniu uznajemy, że dron doleciał
EARTH_R = 6378137.0


def dist_m(lat1, lon1, lat2, lon2):
    north = math.radians(lat2 - lat1) * EARTH_R
    east = math.radians(lon2 - lon1) * EARTH_R * math.cos(math.radians(lat1))
    return math.hypot(east, north)


def main():
    routes = {int(k): v for k, v in json.loads(TRASY.read_text(encoding="utf-8")).items()}
    pos = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sterowanie")
    client.on_connect = lambda c, *_: c.subscribe("drony/+/dane")

    def on_message(c, u, m):
        try:
            d = json.loads(m.payload)
            if d.get("lat") is not None:
                pos[int(d["id"])] = (d["lat"], d["lon"])
        except (ValueError, KeyError, TypeError):
            pass

    client.on_message = on_message
    client.connect_async(BROKER, BROKER_PORT, keepalive=30)
    client.loop_start()
    print("[sterowanie] trasa z {}, przylot < {:.0f} m, czekamy na wszystkich".format(TRASY, ARRIVE_M))

    stage = 0
    while True:
        group = {did: wps[stage] for did, wps in routes.items() if stage < len(wps)}
        if not group:
            print("[sterowanie] koniec tras")
            return
        arrived = []
        for did, wp in group.items():
            client.publish("drony/{}/guided".format(did), json.dumps(wp))
            here = pos.get(did)
            ok = here is not None and dist_m(here[0], here[1], wp["lat"], wp["lon"]) <= ARRIVE_M
            arrived.append(ok)
            print("[sterowanie] pkt {}  D{} {}  {:.6f} {:.6f}".format(
                stage + 1, did, "OK" if ok else "leci", wp["lat"], wp["lon"]))
        if arrived and all(arrived):
            print("[sterowanie] wszyscy na pkt {} — następny".format(stage + 1))
            stage += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
