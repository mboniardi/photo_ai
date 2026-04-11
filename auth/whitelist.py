"""Lettura whitelist email autorizzate da file."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_whitelist(path: str) -> frozenset:
    p = Path(path)
    if not p.exists():
        logger.error("Whitelist non trovata: %s — nessun accesso consentito", path)
        return frozenset()
    emails = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        emails.add(line.lower())
    return frozenset(emails)