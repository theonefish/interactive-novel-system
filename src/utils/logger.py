"""日志工具 - 在此文件中配置日志记录器"""
import logging
import os
from logging.handlers import RotatingFileHandler

# 日志目录：优先读环境变量 LOG_DIR，否则用项目根目录下的 logs/
_LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"))
# 日志级别：优先读环境变量 LOG_LEVEL（如 DEBUG/INFO/WARNING），否则 DEBUG
_LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)


def setup_logger(
    name: str = "rag_agent",
    log_dir: str = _LOG_DIR,
    level: int = _LOG_LEVEL,
    max_bytes: int = 10 * 1024 * 1024,  # 单个日志文件最大 10MB
    backup_count: int = 5,              # 保留 5 个历史文件
) -> logging.Logger:
    """创建/获取一个同时输出到控制台和文件的 logger（文件按大小轮转）。

    - 同一个 name 只注册一次 handler，避免重复日志
    - propagate=False，避免向上传播到根 logger 造成重复
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # 文件输出（带轮转）
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, f"{name}.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception as e:  # 文件不可写时退化为仅控制台
        logger.warning(f"日志文件初始化失败，仅输出到控制台: {e}")

    return logger
