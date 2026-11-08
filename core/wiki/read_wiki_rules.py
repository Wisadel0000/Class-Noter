from pathlib import Path
from loguru import logger

path = "./core/wiki/rules_.md"
ROOT_DIR = Path(path).resolve()

def get_wiki_rule():
    try:
        raw = ROOT_DIR.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        # 应在此处为用户做出提示，如日志报错
        logger.warning("配置文件不存在，正在使用默认设置")
        raise e
    return raw