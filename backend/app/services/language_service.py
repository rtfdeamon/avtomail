from __future__ import annotations

from langdetect import DetectorFactory, LangDetectException, detect

from app.core.config import Settings, get_settings

DetectorFactory.seed = 0  # ensure deterministic results


class LanguageDetector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def detect(self, text: str | None) -> str | None:
        if not text:
            return None
        cleaned = text.strip()
        if len(cleaned) < self.settings.language_detection_min_chars:
            return None
        try:
            language = detect(cleaned)
        except LangDetectException:
            return None
        return language
