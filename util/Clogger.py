"""Logging setup — console (color) + optional file, configurable level."""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    """Configure root logger once at startup.

    Args:
        level: Console log level (DEBUG / INFO / WARNING / ERROR / CRITICAL).
               File output always records at DEBUG when enabled.
        log_file: Optional path for persistent debug log.
    """
    root = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # ── root always DEBUG — handlers decide their own threshold ──
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # ── console handler ──────────────────────────────────────────
    try:
        import colorlog

        console = colorlog.StreamHandler(sys.stderr)
        console.setFormatter(colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)-7s] %(name)-22s %(message)s%(reset)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG":    "cyan",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            },
        ))
    except ImportError:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)-22s %(message)s",
            datefmt="%H:%M:%S",
        ))
    console.setLevel(numeric_level)
    root.addHandler(console)

    # ── file handler (always DEBUG) ──────────────────────────────
    if log_file:
        fp = Path(log_file)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(fp), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)-22s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(fh)

    # ── silence noisy third-party loggers ────────────────────────
    for name in ("chardet", "urllib3", "bs4", "lxml", "colorlog"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger(__name__).debug(
        "logging ready (console=%s, file=%s)", level, log_file or "disabled"
    )
