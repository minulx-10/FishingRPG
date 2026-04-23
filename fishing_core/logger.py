import logging
import logging.handlers
import os
import sys

# 로그 파일 저장 경로 설정
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOG_FILE = os.path.join(LOG_DIR, "fishing_bot.log")

class BotLogger:
    """봇의 로깅을 담당하는 클래스입니다."""
    
    def __init__(self, name: str = "FishingBot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # 포맷터 설정
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 콘솔 핸들러 (표준 출력)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # 파일 핸들러 (날짜별 로테이션)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def info(self, msg: str) -> None:
        self.logger.info(msg)

    def warning(self, msg: str) -> None:
        self.logger.warning(msg)

    def error(self, msg: str, exc_info: bool = True) -> None:
        self.logger.error(msg, exc_info=exc_info)

    def critical(self, msg: str) -> None:
        self.logger.critical(msg)

    def debug(self, msg: str) -> None:
        self.logger.debug(msg)

# 전역 로거 인스턴스 생성
logger = BotLogger()
