"""Peru timezone (America/Lima, UTC-5, no DST)."""
from zoneinfo import ZoneInfo
from datetime import datetime

LIMA = ZoneInfo("America/Lima")


def now() -> datetime:
    """Current datetime in Lima time."""
    return datetime.now(tz=LIMA)
