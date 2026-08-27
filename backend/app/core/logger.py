"""
统一日志封装模块 (Loguru Logger Integration)
负责整个数据抓取、文本清洗、Data Agent 初筛及 Analyst Agent 研报生成的流转日志记录

【稳定性说明 / 死锁修复】
此前 console & file 两个 sink 均使用 enqueue=True，Loguru 会额外创建后台队列线程与
跨线程内部锁；而 InterceptHandler 又把根 logger 级别设为 0（=全部），使 httpx/motor 等
所有标准库日志在 ThreadPoolExecutor 多线程高并发（如 LLM 批量打标）下密集重入
「logging → InterceptHandler → Loguru 队列」链路，触发
`Could not acquire internal lock because it was already in use (deadlock avoided)`，
把 asyncio 事件循环线程一并堵死（进程存活、端口在听、CPU 0%、请求全部超时）。

修复：
1. 撤销两个 sink 的 enqueue=True，改为同步写 —— 不引入后台队列线程，直接消除该重入源；
2. 将高并发噪声库（httpx / motor / uvicorn.access）完全移出 Loguru 并降到 WARNING，
   走原生 logging（lastResort -> stderr），在多次 LLM 调用期间不再灌入 Loguru；
3. uvicorn / fastapi 仍接 Loguru 统一格式，但显式 propagate=False，避免被根 handler 二次拦截。
"""
import sys
import logging
from pathlib import Path
from loguru import logger

# 确保日志输出目录存在
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app_pipeline.log"

# 高并发下密集发日志、且会重入 Loguru 的第三方库：统一移出 Loguru 并降到 WARNING。
_NOISY_LIBS = ("httpx", "motor", "uvicorn.access")


class InterceptHandler(logging.Handler):
    """
    将 Python 标准 logging 模块的日志记录拦截并转发重定向给 Loguru
    以实现 FastAPI, Uvicorn 与应用自身模块 (FastAPIMain/FlashNewsFetcher 等) 日志风格的统一。
    注意：httpx / motor / uvicorn.access 等噪声库已被移出 Loguru（见 _NOISY_LIBS / setup_logger）。
    """
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logger():
    """初始化并配置全局 Loguru 日志输出风格与轮转策略"""
    # 移除默认 handler
    logger.remove()

    # 1. 控制台彩化输出配置（同步写。enqueue=True 会引入后台队列线程 + 内部锁，
    #    是高并发 LLM 打标时卡死事件循环的根因之一，故不启用。）
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # 2. 文件日志输出配置 (带按天/文件大小自动切割轮转与保存，同步写)
    logger.add(
        str(LOG_FILE),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    # 3. 拦截应用自身模块的标准 logging 日志 -> Loguru 统一格式。
    #    根 logger 设 level=INFO：让应用自身 INFO 级日志进入 Loguru，同时过滤掉第三方库的 DEBUG 噪声。
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)

    # 4. 低噪声应用服务日志 (uvicorn / fastapi)：接 Loguru，但显式禁止冒泡到根，
    #    避免被根 handler 再次拦截造成重复输出。
    for logger_name in ("uvicorn", "fastapi"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.setLevel(logging.INFO)
        mod_logger.propagate = False

    # 5. 高并发噪声库 (httpx / motor / uvicorn.access)：完全移出 Loguru，仅保留 WARNING 及以上，
    #    走原生 logging（无 handler 时 stdlib lastResort -> stderr），消除 LLM 调用期间的密集灌入。
    for logger_name in _NOISY_LIBS:
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = []
        mod_logger.setLevel(logging.WARNING)
        mod_logger.propagate = False

    logging.getLogger("matplotlib").setLevel(logging.ERROR)
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

    logger.info("[Loguru Logger] 统一流转日志引擎初始化完成 (终端控制台 + 本地日志文件 `logs/app_pipeline.log`)")
    return logger


def log_data_pipeline(action: str, source: str, count: int, extra_info: str = ""):
    """数据采集与清洗流转专用日志记录器"""
    msg = f"[Data Pipeline] Action: {action} | Source: {source} | Count: {count}"
    if extra_info:
        msg += f" | Info: {extra_info}"
    logger.info(msg)


def log_agent_action(agent_name: str, status: str, details: str):
    """Agent 运行逻辑专用日志记录器"""
    logger.info(f"[{agent_name}] Status: {status} | Details: {details}")


# 暴露单例 logger 供全局直接使用
app_logger = setup_logger()
