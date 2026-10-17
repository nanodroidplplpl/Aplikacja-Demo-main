# Ustawienia aplikacji drona. Na każdym Raspberry zmieniasz zwykle tylko
# DRONE_ID i PHASE_CAL_DEG (po kalibracji).

# --- Identyfikacja i łączność ------------------------------------------------
DRONE_ID = 1                  # 1, 2, 3 ... (musi być inny na każdym dronie)
BROKER = "10.243.176.155"     # adres ZeroTier komputera z brokerem MQTT (host)
BROKER_PORT = 1883

# --- Autopilot (MAVLink) -----------------------------------------------------
# "auto" = sprawdza wszystkie porty szeregowe (/dev/ttyACM*, ttyUSB*, ttyAMA*, ttyS*, serial*)
# i wybiera port, z którego przychodzi heartbeat. Znaleziony port widać w logu.
# Można wpisać port na stałe, np. "/dev/ttyACM0" (USB) albo "/dev/serial0" (TELEM na GPIO).
# Pusty napis = bez autopilota, używana jest stała pozycja poniżej (test na ziemi).
MAVLINK_DEVICE = "auto"
MAVLINK_BAUDS = [115200, 921600, 57600]  # sprawdzane po kolei (dla USB bez znaczenia)
FIXED_LAT = 52.2520
FIXED_LON = 20.9050
FIXED_HEADING_DEG = 0.0

# --- Radio ADALM Pluto (tryb 2r2t: dwa kanały RX) ----------------------------
PLUTO_URI = "ip:192.168.2.1"  # albo "usb:"
CENTER_FREQ_HZ = 2.300e9      # LO odbiornika (środek widma)
SAMPLE_RATE_HZ = 4e6          # szerokość podglądanego widma (max ~20e6 przy 2 kanałach)
RF_BANDWIDTH_HZ = 4e6         # filtr analogowy, zwykle = SAMPLE_RATE_HZ
GAIN_MODE = "manual"          # "manual", "slow_attack" albo "fast_attack"
GAIN_RX0_DB = 40              # wzmocnienie kanału RX1 (0..71 dB, tylko w "manual")
GAIN_RX1_DB = 40              # wzmocnienie kanału RX2
SAMPLES = 16384               # próbek na odczyt (na kanał)
NFFT = 1024                   # punktów widma; SAMPLES/NFFT ramek jest uśrednianych
RATE_HZ = 2.0                 # ile razy na sekundę wysyłać widmo i namiar

# --- Namiar DOA (kąt nadejścia z dwóch anten) --------------------------------
TARGET_FREQ_HZ = 2.3002e9     # częstotliwość emitera (musi leżeć w podglądanym widmie)
TARGET_BW_HZ = 100e3          # szerokość okna wokół TARGET_FREQ_HZ, w którym szukamy sygnału
SNR_MIN_DB = 10.0             # poniżej tego namiar jest odrzucany
ANTENNA_SPACING_M = 0.065     # rozstaw anten RX1-RX2; nie więcej niż pół długości fali
# Opóźnienie fazy RX2 względem RX1 wnoszone przez kable i płytkę. Kalibracja:
# emiter na wprost (prostopadle do linii anten) -> wpisz tu "faza surowa".
PHASE_CAL_DEG = 0.0
# Kierunek od anteny RX1 do RX2 względem nosa drona, zgodnie ze wskazówkami
# zegara (90 = RX2 po prawej). Gdy namiary wychodzą odbite, dodaj 180.
BASELINE_OFFSET_DEG = 90.0
