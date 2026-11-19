# -*- coding: utf-8 -*-
"""
gmtrade sidecar 客户端。

Python 3.11 无法加载 gmtrade 3.0.6（只有 cp36-cp310 wheel），因此网关用
Python 3.10 的 `.venv310` 启动 `tools/gmtrade_bridge.py`，通过 JSON Lines 调用。
"""

import json
import logging
import os
import queue
import subprocess
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class GMTradeBridgeError(RuntimeError):
    """gmtrade sidecar 调用失败。"""


class GMTradeProxy:
    """把 gmtrade sidecar 包装成与 gm.api 类似的可调用对象。"""

    def __init__(
        self,
        python_path: str,
        bridge_script: str,
        token: str,
        account_id: str,
        endpoint: str = "api.myquant.cn:9000",
        timeout: float = 30.0,
    ):
        self._python_path = python_path
        self._bridge_script = bridge_script
        self._token = token
        self._account_id = account_id
        self._endpoint = endpoint
        self._timeout = timeout

        self._process: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def available(self) -> bool:
        return bool(self._python_path and os.path.exists(self._python_path) and os.path.exists(self._bridge_script))

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if not self.available:
            raise GMTradeBridgeError("gmtrade sidecar 不可用：Python 或 bridge 脚本不存在")

        env = os.environ.copy()
        env["JINGNI_GM_TOKEN"] = self._token
        env["JINGNI_GM_ACCOUNT_ID"] = self._account_id
        env["JINGNI_GMTRADE_ENDPOINT"] = self._endpoint
        env["PYTHONIOENCODING"] = "utf-8"

        self._process = subprocess.Popen(
            [self._python_path, "-u", self._bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        self._queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

        ready = self._read_response(timeout=max(self._timeout, 30.0))
        if not ready.get("ok") or not (ready.get("data") or {}).get("ready"):
            self.close()
            raise GMTradeBridgeError(f"gmtrade sidecar 启动失败: {ready.get('error')}")

    def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            self._queue.put(line)

    def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        for line in self._process.stderr:
            text = line.rstrip()
            if text:
                logger.debug("gmtrade sidecar: %s", text)

    def _read_response(self, timeout: float) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GMTradeBridgeError("gmtrade sidecar 响应超时")
            try:
                line = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise GMTradeBridgeError("gmtrade sidecar 响应超时")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                logger.warning("忽略 gmtrade sidecar 非 JSON 输出: %s", line[:200])

    def _request(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        with self._lock:
            self._start()
            assert self._process and self._process.stdin
            self._seq += 1
            req_id = str(self._seq)
            payload = {"id": req_id, "action": action, "params": params or {}}
            try:
                self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise GMTradeBridgeError(f"gmtrade sidecar 写入失败: {exc}") from exc

            response = self._read_response(timeout=self._timeout)
            if response.get("id") != req_id:
                raise GMTradeBridgeError(f"gmtrade sidecar 响应 id 不匹配: {response}")
            if not response.get("ok"):
                raise GMTradeBridgeError(str(response.get("error") or "gmtrade 调用失败"))
            return response.get("data")

    # 供 GMTradeService 通过 getattr(api, function) 调用
    def get_cash(self, **kwargs):
        return self._request("cash", kwargs)

    def get_position(self, **kwargs):
        return self._request("positions", kwargs)

    def get_orders(self, **kwargs):
        return self._request("orders", kwargs)

    def order_volume(self, **kwargs):
        return self._request("place", kwargs)

    def order_cancel(self, **kwargs):
        return self._request("cancel", kwargs)

    def close(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write(json.dumps({"id": "shutdown", "action": "shutdown"}) + "\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
