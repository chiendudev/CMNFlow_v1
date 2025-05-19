import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional
from pathlib import Path
from colorlog import ColoredFormatter
from src.core.settings import Settings
import time


class ContextFilter(logging.Filter):
    """Thêm context như symbol, timeframe vào log."""

    def __init__(self):
        super().__init__()
        self.context = {"symbol": "-", "timeframe": "-"}

    def set_context(self, **kwargs):
        self.context.update(kwargs)

    def filter(self, record):
        # Đảm bảo luôn có các field mặc định
        for key in ["symbol", "timeframe"]:
            setattr(record, key, self.context.get(key, "-"))
        return True



context_filter = ContextFilter()


def setup_logging(settings: Settings) -> None:
    """Khởi tạo hệ thống logging với console và file handlers."""
    log_directory = Path(settings.log_directory)
    log_directory.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(module)s:%(lineno)d | symbol:%(symbol)s | timeframe:%(timeframe)s | %(message)s"
    colored_format = "%(log_color)s" + log_format

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter(
        colored_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        }
    ))
    console_handler.addFilter(context_filter)

    log_file = log_directory / "app.log"
    file_handler = None
    for _ in range(3):  # Retry 3 lần
        try:
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=settings.log_rotation_size,
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(
                log_format,
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            file_handler.addFilter(context_filter)
            break
        except Exception as e:
            print(f"Failed to create file handler: {e}. Retrying...")
            time.sleep(1)
    if not file_handler:
        print("Failed to create file handler after retries. Falling back to console only.")

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.handlers = []
    logger.addHandler(console_handler)
    if file_handler:
        logger.addHandler(file_handler)

    logging.info("Logging initialized: level=%s, directory=%s, rotation_size=%dMB",
                 settings.log_level, settings.log_directory, settings.log_rotation_size // (1024 * 1024))


def get_logger(name: str) -> logging.Logger:
    """Lấy logger với tên cụ thể."""
    return logging.getLogger(name)


def set_log_context(**kwargs) -> None:
    """Đặt context cho log (symbol, timeframe, v.v.)."""
    context_filter.set_context(**kwargs)