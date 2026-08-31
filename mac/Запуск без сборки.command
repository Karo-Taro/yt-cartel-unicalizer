#!/bin/bash
# Запускает программу прямо из исходников, без сборки .app.
# Удобно, чтобы просто попробовать.
set -e
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
    echo "Не найден python3. Установите: brew install python"
    read -n 1 -s -r -p "Нажмите любую клавишу…"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Первый запуск: готовлю окружение, это займёт пару минут…"
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip >/dev/null
    python -m pip install PySide6 pillow
else
    source .venv/bin/activate
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ВНИМАНИЕ: не найден ffmpeg. Поставьте его:  brew install ffmpeg"
    echo
fi

exec python app.py
