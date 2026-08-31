"""Память последней сессии: настройки не сбрасываются между запусками.

Для того, кто заливает пачками каждый день, это важнее любой отдельной кнопки:
выставил один раз пресет, папку, число копий — и они остаются.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _path() -> Path:
    """Где хранить настройки.

    Рядом с исходниками — удобно: папку можно перенести вместе с настройками.
    Но у собранного приложения та же папка лежит внутри самой сборки, куда
    писать нельзя (переустановка сотрёт, а в Program Files не хватит прав),
    поэтому там уходим в пользовательский профиль.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # На macOS настройки приложений живут здесь, а не в домашней папке.
            base = Path.home() / "Library" / "Application Support" / "VideoUnicalizer"
        else:
            base = Path(os.environ.get("APPDATA") or Path.home()) / "VideoUnicalizer"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path.home() / ".video_unicalizer.json"
        return base / "last_session.json"
    return Path(__file__).resolve().parent.parent / "last_session.json"


def load() -> dict[str, Any]:
    """Читает сохранённую сессию. При любой ошибке — пустой словарь, не падаем."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(session: dict[str, Any]) -> None:
    """Пишет сессию. Ошибки записи глотаем: не смогли сохранить — не беда."""
    try:
        _path().write_text(
            json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
