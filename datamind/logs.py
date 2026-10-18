"""Local log file (logs/datamind.log, gitignored): poore tracebacks aur har question ka result.
Users ko saaf messages dikhte hain; engineers traces yahan padhte hain."""
import logging
import os
from pathlib import Path

from .config import ROOT


def get_logger() -> logging.Logger:
    logger = logging.getLogger("datamind")
    if not logger.handlers:
        log_dir = Path(os.getenv("DATAMIND_LOG_DIR") or ROOT / "logs")  # tests isko temp folder par point karte hain
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "datamind.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
