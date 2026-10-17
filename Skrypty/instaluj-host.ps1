# Jednorazowa instalacja na komputerze hosta (Windows). Uruchom PowerShell jako Administrator:
#   powershell -ExecutionPolicy Bypass -File Skrypty\instaluj-host.ps1 -NetworkId <ID_SIECI_ZEROTIER>
param([string]$NetworkId = "")
$ErrorActionPreference = "Stop"
$app = Join-Path $PSScriptRoot "..\Aplikacja Host"

Write-Host "== ZeroTier"
$zt = "C:\ProgramData\ZeroTier\One\zerotier-one_x64.exe"
if (-not (Test-Path $zt)) { winget install -e --id ZeroTier.ZeroTierOne --accept-source-agreements --accept-package-agreements }
if ($NetworkId) {
    & $zt -q join $NetworkId
    Write-Host "Autoryzuj ten komputer w my.zerotier.com i nadaj mu adres 10.243.176.155"
}

Write-Host "== Broker MQTT (Mosquitto, usluga Windows z autostartem)"
$mosq = "C:\Program Files\mosquitto"
if (-not (Test-Path $mosq)) { winget install -e --id EclipseFoundation.Mosquitto --accept-source-agreements --accept-package-agreements }
Copy-Item (Join-Path $PSScriptRoot "mosquitto.conf") (Join-Path $mosq "mosquitto.conf") -Force
Set-Service mosquitto -StartupType Automatic
Restart-Service mosquitto

Write-Host "== Zapora: wpuszczamy MQTT (TCP 1883)"
if (-not (Get-NetFirewallRule -DisplayName "MQTT 1883" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "MQTT 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow | Out-Null
}

Write-Host "== Python: srodowisko $app\.venv"
py -3 -m venv "$app\.venv"
& "$app\.venv\Scripts\python.exe" -m pip install -r "$app\requirements.txt"

Write-Host "`nGotowe. Start aplikacji: Aplikacja Host\start.cmd"
