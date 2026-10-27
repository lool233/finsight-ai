# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 大语言模型（LLM）调用封装
=====================================================================
1. 采用 OpenAI 兼容的 /chat/completions 协议，可对接 DeepSeek、通义千问、
   智谱 GLM、Kimi、OpenAI 等任意兼容服务，只需在 .env 中配置三个参数。
2. 仅依赖 Python 标准库 urllib，避免额外第三方依赖。
3. 未配置 API Key 或调用失败时抛出 LLMUnavailable，由业务层自动降级到
   内置规则引擎，保证系统在无网络 / 无密钥环境下依然完整可用。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from config import config


class LLMUnavailable(RuntimeError):
    """LLM 不可用（未配置密钥 / 网络异常 / 服务报错）"""


class LLMClient:
    """OpenAI 兼容协议的最小客户端"""

    def __init__(self) -> None:
        self.base_url = config.LLM_BASE_URL.rstrip("/")
        self.api_key = config.LLM_API_KEY
        self.model = config.LLM_MODEL
        self.timeout = config.LLM_TIMEOUT
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "fallback": config.LLM_FALLBACK_ENABLED,
            "last_error": self.last_error,
            "mode": "LLM 大模型" if self.enabled else "内置规则引擎（未配置 LLM_API_KEY）",
        }

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> tuple:
        """调用对话补全接口，返回 (模型输出文本, 耗时毫秒)。"""
        if not self.enabled:
            raise LLMUnavailable("未配置 LLM_API_KEY，无法调用大模型")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": config.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )

        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            detail = exc.read().decode("utf-8", "ignore")[:500]
            self.last_error = f"HTTP {exc.code}: {detail}"
            raise LLMUnavailable(f"大模型接口返回错误：{self.last_error}") from exc
        except Exception as exc:  # 网络/超时
            self.last_error = str(exc)
            raise LLMUnavailable(f"大模型接口调用失败：{exc}") from exc

        elapsed = int((time.time() - started) * 1000)
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            self.last_error = body[:300]
            raise LLMUnavailable("大模型返回内容不是合法 JSON") from exc

        if isinstance(result, dict) and result.get("error"):
            message = str(result["error"])[:300]
            self.last_error = message
            raise LLMUnavailable(f"大模型服务返回错误：{message}")

        choices = result.get("choices") or []
        if not choices:
            raise LLMUnavailable("大模型返回结果为空")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content.strip():
            raise LLMUnavailable("大模型返回内容为空")
        self.last_error = None
        return content.strip(), elapsed

    # ------------------------------------------------------------------
    def chat_text(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        content, _ = self.chat(messages, **kwargs)
        return content

    def chat_json(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        """要求模型输出 JSON 并解析为字典。"""
        kwargs.setdefault("json_mode", True)
        content = self.chat_text(messages, **kwargs)
        return parse_json_block(content)


def parse_json_block(text: str) -> Dict[str, Any]:
    """从模型输出中稳健地提取 JSON 对象（兼容 ```json 代码块包裹）。"""
    if not text:
        raise LLMUnavailable("模型输出为空，无法解析 JSON")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"无法解析模型输出的 JSON：{exc}") from exc
    raise LLMUnavailable("模型输出中未找到 JSON 结构")


llm_client = LLMClient()

__all__ = ["LLMClient", "LLMUnavailable", "llm_client", "parse_json_block"]
