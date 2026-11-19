"""
RPC 线程执行器模块。

为每个模块维护一个**串行、有界**的线程池，并把它交给 asyncio 调度：
- 同步 SDK 调用不再直接跑在事件循环里，避免卡死整个网关；
- 同一模块的调用串行执行，满足掘金/迅投 SDK 的非线程安全约束；
- 超时由 asyncio.wait_for 控制，超时后协程立即返回，不等待线程结束。

注意：
    线程无法被强制终止。超时后底层调用可能仍在后台运行，
    因此对下单、撤单等写操作必须配合幂等与状态对账，不能盲目重试。
"""

import asyncio
import concurrent.futures
import functools
import logging
import threading
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_executors: Dict[Tuple[str, str], concurrent.futures.ThreadPoolExecutor] = {}
_lock = threading.Lock()

VALID_LANES = ("data", "trade", "bulk")


def _executor_key(module: str, lane: str) -> Tuple[str, str]:
    """
    计算执行器键。

    tdxquant 的 tqcenter 是进程级单客户端、同步 C API，不允许多线程并发调用；
    因此无论 data/trade lane，都收敛到同一个串行执行器。其他 SDK 按 lane 隔离。
    """
    if module == "tdxquant":
        return (module, "serial")
    return (module, lane if lane in VALID_LANES else "data")


def get_executor(
    module: str, lane: str = "data"
) -> concurrent.futures.ThreadPoolExecutor:
    """获取（或创建）某模块 + lane 的串行执行器。"""
    key = _executor_key(module, lane)
    with _lock:
        executor = _executors.get(key)
        if executor is None:
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"rpc-{key[0]}-{key[1]}",
            )
            _executors[key] = executor
            logger.debug("已创建执行器: %s/%s", key[0], key[1])
        return executor


async def run_module_call(
    module: str,
    func: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Optional[Dict[str, Any]] = None,
    timeout: float = 30,
    lane: str = "data",
) -> Any:
    """
    在模块专属线程池中执行同步函数，并施加超时。

    参数：
        module: 模块名（xtdata/xttrader/gm/tdxquant）
        func: 同步可调用对象
        args: 位置参数序列
        kwargs: 关键字参数字典
        timeout: 超时秒数
        lane: data / trade / bulk；用于隔离读写队列。
              tdxquant 会忽略 lane，统一走单串行执行器。

    返回：
        func 的返回值

    异常：
        asyncio.TimeoutError: 超时；底层线程可能仍在运行
    """
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **(kwargs or {}))
    future = loop.run_in_executor(get_executor(module, lane), call)
    return await asyncio.wait_for(future, timeout=timeout)


def shutdown_executors(wait: bool = False) -> None:
    """
    关闭所有模块执行器。

    参数：
        wait: 是否等待正在执行的线程结束。默认 False，
              避免一个卡死的 SDK 调用拖住进程退出。
    """
    with _lock:
        for (module, lane), executor in _executors.items():
            try:
                executor.shutdown(wait=wait, cancel_futures=True)
                logger.debug("已关闭执行器: %s/%s", module, lane)
            except Exception as exc:  # pragma: no cover - 极端兜底
                logger.warning("关闭执行器 %s/%s 失败: %s", module, lane, exc)
        _executors.clear()
