# logging_config.py
import logging
import os
import sys


def setup_logging():
    if logging.getLogger().hasHandlers():
        return
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Tạo formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Tạo StreamHandler với mã hóa UTF-8
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG)
    # Đặt mã hóa UTF-8 cho console (Windows)
    if sys.platform.startswith('win'):
        stream_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

    # Tạo FileHandler với mã hóa UTF-8
    file_handler = logging.FileHandler(os.path.join(log_dir, 'app.log'), encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Cấu hình logging
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[stream_handler, file_handler]
    )