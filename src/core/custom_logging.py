import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional
from pathlib import Path
from colorlog import ColoredFormatter
from src.core.settings import Settings


def setup_logging(settings: Settings) -> None:
    """Khởi tạo hệ thống logging với console và file handlers."""
    # Tạo thư mục log nếu chưa tồn tại
    log_directory = Path(settings.log_directory)
    log_directory.mkdir(parents=True, exist_ok=True)

    # Định dạng log
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s"
    colored_format = "%(log_color)s" + log_format

    # Console handler với màu
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

    # File handler với rotation
    log_file = log_directory / "app.log"
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
    except Exception as e:
        print(f"Failed to create file handler: {e}. Falling back to console only.")
        file_handler = None

    # Cấu hình logger gốc
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.handlers = []  # Xóa handlers mặc định
    logger.addHandler(console_handler)
    if file_handler:
        logger.addHandler(file_handler)

    logging.info("Logging initialized: level=%s, directory=%s, rotation_size=%dMB",
                 settings.log_level, settings.log_directory, settings.log_rotation_size // (1024 * 1024))


def get_logger(name: str) -> logging.Logger:
    """Lấy logger với tên cụ thể."""
    return logging.getLogger(name)