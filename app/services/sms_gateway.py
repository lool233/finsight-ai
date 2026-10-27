# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 短信网关适配器
=====================================================================
需求允许：若具备短信平台则真实下发，否则在催还记录中做标识。
本模块通过 SMS_PROVIDER 配置切换三种工作模式：

  none  —— 未接入短信平台（默认）。不做真实下发，催还记录标记为
           “无短信平台”，并置 need_manual_send = 1，提示人工补发。
  mock  —— 模拟发送成功，用于课堂演示完整的“生成 → 下发 → 已发送”闭环。
  http  —— 通用 HTTP 短信网关（POST JSON）。可在 .env 中配置
           SMS_ENDPOINT / SMS_ACCESS_KEY_ID / SMS_ACCESS_KEY_SECRET。
           阿里云、腾讯云等平台均可在此基础上按官方签名规则扩展。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

from config import config


class SmsGateway:
    """短信发送统一入口"""

    def __init__(self) -> None:
        self.provider = config.SMS_PROVIDER or "none"

    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        labels = {
            "none": "未接入短信平台（催还记录中做标识，需人工补发）",
            "mock": "模拟短信网关（演示模式，直接标记为已发送）",
            "http": f"HTTP 短信网关（{config.SMS_ENDPOINT or '未配置 SMS_ENDPOINT'}）",
        }
        return {
            "provider": self.provider,
            "description": labels.get(self.provider, f"未知模式：{self.provider}"),
            "sign_name": config.SMS_SIGN_NAME,
            "template_code": config.SMS_TEMPLATE_CODE,
            "available": self.provider != "none",
        }

    # ------------------------------------------------------------------
    def send(self, phone: str, content: str) -> Dict[str, Any]:
        """
        发送催还短信。
        返回：{success: bool, provider: str, send_status: str, detail: str}
        send_status 取值：已发送 / 发送失败 / 无短信平台 / 待发送
        """
        if not phone:
            return self._result(False, "发送失败", "接收号码为空，无法下发")

        if self.provider == "none":
            return self._result(False, "无短信平台",
                                "系统未接入短信平台，已在催还记录中标识，请人工通过短信/电话催还")

        if self.provider == "mock":
            return self._result(True, "已发送", f"模拟下发成功（{config.SMS_SIGN_NAME} → {phone}）")

        if self.provider == "http":
            return self._send_http(phone, content)

        return self._result(False, "发送失败", f"不支持的短信模式：{self.provider}")

    # ------------------------------------------------------------------
    def _send_http(self, phone: str, content: str) -> Dict[str, Any]:
        if not config.SMS_ENDPOINT:
            return self._result(False, "发送失败", "未配置 SMS_ENDPOINT，无法调用短信网关")

        payload = {
            "phone": phone,
            "content": f"{config.SMS_SIGN_NAME}{content}",
            "sign_name": config.SMS_SIGN_NAME,
            "template_code": config.SMS_TEMPLATE_CODE,
        }
        request = urllib.request.Request(
            config.SMS_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json;charset=utf-8",
                "X-Access-Key-Id": config.SMS_ACCESS_KEY_ID,
                "X-Access-Key-Secret": config.SMS_ACCESS_KEY_SECRET,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8", "ignore")
        except Exception as exc:
            return self._result(False, "发送失败", f"短信网关调用异常：{exc}")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._result(True, "已发送", f"网关返回非 JSON 内容，按成功处理：{body[:120]}")

        code = str(data.get("code", data.get("Code", "0")))
        if code in ("0", "OK", "ok", "200", "Success", "success"):
            return self._result(True, "已发送", f"短信网关返回：{body[:120]}")
        return self._result(False, "发送失败", f"短信网关返回失败：{body[:200]}")

    # ------------------------------------------------------------------
    def _result(self, success: bool, send_status: str, detail: str) -> Dict[str, Any]:
        return {
            "success": success,
            "provider": self.provider,
            "send_status": send_status,
            "detail": detail,
        }


sms_gateway = SmsGateway()

__all__ = ["SmsGateway", "sms_gateway"]
