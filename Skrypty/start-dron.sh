#!/bin/bash
# Start aplikacji drona. Przy starcie Raspberry uruchamia go usługa dron.service.
cd "$(dirname "$0")/../Aplikacja Dron" || exit 1
exec .venv/bin/python3 -u dron.py
