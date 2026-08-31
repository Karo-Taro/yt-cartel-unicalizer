#!/bin/bash
# Собирает "Video Unicalizer.app" из исходников. Запускать двойным кликом.
set -e
cd "$(dirname "$0")/.."

echo "=============================================="
echo "  Video Unicalizer — сборка приложения для Mac"
echo "=============================================="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Не найден python3."
    echo "Установите его: brew install python   (или скачайте с python.org)"
    read -n 1 -s -r -p "Нажмите любую клавишу…"
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ВНИМАНИЕ: не найден ffmpeg — без него программа не сможет обрабатывать видео."
    echo "Поставьте его командой:  brew install ffmpeg"
    echo
fi

echo "[1/3] Готовлю окружение…"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null

echo "[2/3] Ставлю зависимости (первый раз это несколько минут)…"
python -m pip install PySide6 pillow pyinstaller

echo "[3/3] Собираю приложение…"
python -m PyInstaller --noconfirm --clean unicalizer.spec

echo
echo "Готово. Приложение здесь:"
echo "   $(pwd)/dist/Video Unicalizer.app"
echo
echo "Перетащите его в папку «Программы»."
echo
echo "Если macOS скажет, что приложение от неизвестного разработчика:"
echo "  правый клик по нему → «Открыть» → «Открыть» ещё раз."
echo
read -n 1 -s -r -p "Нажмите любую клавишу…"
