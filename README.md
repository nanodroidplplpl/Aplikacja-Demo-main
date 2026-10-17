# Monitoring widma i lokalizacja emitera (3 drony + host)

```
Aplikacja Dron/   Raspberry Pi + ADALM Pluto (2 kanały RX) + autopilot
  dron.py         start -> w pętli: widmo + namiar DOA + pozycja z autopilota -> MQTT
  config.py       WSZYSTKIE ustawienia drona (radio, kalibracja, broker, autopilot)
  kalibracja.py   pomiar opóźnienia fazy RX2-RX1 (wartość do PHASE_CAL_DEG)
Aplikacja Host/   komputer z Windows
  host.py         widmo + spektrogram z 3 dronów, mapa namiarów, pozycja emitera
  start.cmd       uruchomienie
Skrypty/
  instaluj-rpi.sh   jednorazowa instalacja RPi (pakiety, ZeroTier, autostart)
  start-dron.sh     skrypt startowy uruchamiany automatycznie przy starcie RPi
  dron.service      usługa systemd (autostart, restart po awarii)
  pluto-2r2t.sh     jednorazowe włączenie drugiego kanału RX w Pluto
  instaluj-host.ps1 jednorazowa instalacja hosta (ZeroTier, Mosquitto, zapora, Python)
  mosquitto.conf    konfiguracja brokera MQTT
```

Każdy dron co 0,5 s wysyła jeden JSON na temat `drony/<ID>/dane`: pozycję i kurs
z autopilota, widmo (1024 punkty, dBFS) i namiar. Host liczy pozycję emitera jako
przecięcie namiarów. Para anten nie rozróżnia, z której strony swojej linii
przychodzi sygnał, więc każdy dron daje dwa możliwe azymuty. Host wybiera zestaw,
w którym proste przecinają się najlepiej. Dlatego potrzebne są 3 drony (przy 2
wynik bywa niejednoznaczny).

## 1. Sieć ZeroTier (raz)

1. Na [my.zerotier.com](https://my.zerotier.com) utwórz sieć prywatną i zapisz jej ID.
2. Po dołączeniu urządzeń (kroki 2 i 3) autoryzuj je.
3. Host (komputer z brokerem) ma stały adres `10.243.176.155`. Jeśli się zmieni,
   popraw `BROKER` w `Aplikacja Dron/config.py` na każdym dronie.

Drony łączą się tylko z adresem hosta (`BROKER` w `config.py`), więc ich adresy są
wyłącznie do logowania przez SSH.

## 2. Host (Windows, raz)

PowerShell jako Administrator, w folderze projektu:

```powershell
powershell -ExecutionPolicy Bypass -File Skrypty\instaluj-host.ps1 -NetworkId <ID_SIECI>
```

Skrypt instaluje ZeroTier i Mosquitto (usługa Windows startująca z systemem), otwiera
port 1883 w zaporze i tworzy środowisko Python. Uruchomienie: `Aplikacja Host\start.cmd`.

## 3. Raspberry Pi (raz na każdy dron)

Skopiuj foldery `Aplikacja Dron` i `Skrypty` na Pi (np. do `~/projekt`), potem:

```bash
cd ~/projekt/Skrypty
sudo bash instaluj-rpi.sh <ID_SIECI>   # pakiety, ZeroTier, autostart
bash pluto-2r2t.sh                    # tylko raz na każde Pluto, hasło: analog
nano "../Aplikacja Dron/config.py"    # ustaw DRONE_ID = 1, 2 albo 3
sudo reboot
```

Po starcie program uruchamia się sam. Podgląd jego pracy: `journalctl -fu dron`.
Jeśli program się zatrzyma (np. odłączone Pluto), system uruchomi go ponownie po 5 s.
Gdy bash zgłasza `$'\r': command not found`, pliki mają końce linii z Windows:
`sed -i 's/\r$//' *.sh`.

## 4. Parametry radia (`Aplikacja Dron/config.py`)

| Parametr | Znaczenie |
|---|---|
| `CENTER_FREQ_HZ`, `SAMPLE_RATE_HZ` | środek i szerokość podglądanego widma |
| `RF_BANDWIDTH_HZ` | filtr analogowy Pluto |
| `GAIN_MODE`, `GAIN_RX0_DB`, `GAIN_RX1_DB` | wzmocnienie: ręczne osobno na każdy kanał albo AGC |
| `TARGET_FREQ_HZ`, `TARGET_BW_HZ` | gdzie szukać emitera (czerwone pole na widmie hosta) |
| `PHASE_CAL_DEG` | opóźnienie fazy RX2 względem RX1 (kalibracja) |
| `ANTENNA_SPACING_M` | rozstaw anten, najwyżej pół długości fali (65 mm przy 2,3 GHz) |
| `BASELINE_OFFSET_DEG` | kierunek RX1 -> RX2 względem nosa drona |

Dla namiaru najlepiej ustawić `GAIN_MODE = "manual"`: AGC zmienia wzmocnienie
każdego kanału osobno.

## 5. Kalibracja fazy (na ziemi, na każdym dronie)

1. Ustaw emiter kilka metrów od drona, dokładnie na wprost anten (prostopadle do
   linii RX1-RX2).
2. `sudo systemctl stop dron`, potem w `Aplikacja Dron`: `.venv/bin/python3 kalibracja.py`.
3. Wpisz podaną wartość do `PHASE_CAL_DEG` i uruchom usługę: `sudo systemctl start dron`.
4. Sprawdzenie: na hoście w tytule widma drona „kąt” powinien wynosić około 0°,
   a po przeniesieniu emitera w stronę anteny RX2 rosnąć do około +90°. Jeśli maleje
   (np. zamienione kable), dodaj 180 do `BASELINE_OFFSET_DEG`. Kąt na ekranie dalej
   będzie ujemny, ale azymuty na mapie będą poprawne.

Przesunięcie fazy między kanałami może się zmienić po zmianie częstotliwości albo
restarcie Pluto. Po takiej zmianie sprawdź kalibrację ponownie.

Do testu bez autopilota ustaw `MAVLINK_DEVICE = ""`. Wtedy używana jest stała
pozycja `FIXED_LAT`, `FIXED_LON`, `FIXED_HEADING_DEG`.
