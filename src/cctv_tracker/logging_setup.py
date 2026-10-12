from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import re


def redact(value: str) -> str:
    value = re.sub(r"(?i)\b(?:rtsp|rtsps|https?)://[^\s\"']+", "[REDACTED_ENDPOINT]", value)
    return re.sub(r"(?i)(password|token|authorization|secret)([\s\"':=]+)[^\s,}\"]+", r"\1\2[REDACTED]", value)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def configure_logging(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cctv_tracker")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    handler = RotatingFileHandler(directory / "engine.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
