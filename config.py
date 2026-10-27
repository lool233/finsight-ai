# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 全局配置模块
=====================================================================
配置来源优先级（高 → 低）：
    1. 系统环境变量
    2. .env.local —— 本机私密配置（API 密钥等），**不随代码提交**
    3. .env       —— 随工程提交的公共配置
    4. 代码默认值
所有可变参数集中在本文件，便于部署时按环境调整。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# 轻量 .env 解析（不依赖 python-dotenv，保证最小依赖、开箱即用）
# ---------------------------------------------------------------------------
def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 环境变量优先，不覆盖已存在的值（先加载者优先）
        os.environ.setdefault(key, value)


# 先加载本机私密配置（优先级更高），再加载公共配置
_load_dotenv(BASE_DIR / ".env.local")
_load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key, "1" if default else "0").lower()
    return value in ("1", "true", "yes", "on", "y")


class Config:
    """应用配置对象"""

    # ---------------- Flask ----------------
    SECRET_KEY = _env("SECRET_KEY", "loan-collection-system-secret-key-2025")
    JSON_AS_ASCII = False
    SESSION_COOKIE_NAME = "loan_session"
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60  # 8 小时

    APP_NAME = "智析 FinSight AI"
    APP_SUBTITLE = "财务借支智能分析与催收助手"
    APP_VERSION = "1.0.0"
    HOST = _env("APP_HOST", "127.0.0.1")
    PORT = _env_int("APP_PORT", 5000)
    DEBUG = _env_bool("APP_DEBUG", True)

    # ---------------- 数据库 ----------------
    # DB_DIALECT = mysql  -> 生产/课程设计正式环境（MySQL 8.0）
    # DB_DIALECT = sqlite -> 本地零依赖演示环境
    DB_DIALECT = _env("DB_DIALECT", "mysql").lower()

    MYSQL_HOST = _env("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = _env_int("MYSQL_PORT", 3306)
    MYSQL_USER = _env("MYSQL_USER", "root")
    MYSQL_PASSWORD = _env("MYSQL_PASSWORD", "123456")
    MYSQL_DATABASE = _env("MYSQL_DATABASE", "loan_system")
    MYSQL_CHARSET = _env("MYSQL_CHARSET", "utf8mb4")

    SQLITE_PATH = _env("SQLITE_PATH", str(BASE_DIR / "data" / "loan_system.db"))

    # ---------------- 业务参数 ----------------
    # 借资超过 N 个月未还 => 逾期，进入催还流程（需求：3 个月）
    OVERDUE_MONTHS = _env_int("OVERDUE_MONTHS", 3)
    # 催还分级阈值（逾期天数）
    COLLECTION_LEVEL2_DAYS = _env_int("COLLECTION_LEVEL2_DAYS", 90)
    COLLECTION_LEVEL3_DAYS = _env_int("COLLECTION_LEVEL3_DAYS", 180)
    # 同一笔借资同一级别催还的最小间隔天数（防止重复催还）
    COLLECTION_INTERVAL_DAYS = _env_int("COLLECTION_INTERVAL_DAYS", 7)

    # ---------------- LLM（OpenAI 兼容接口） ----------------
    LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = _env("LLM_API_KEY", "")
    LLM_MODEL = _env("LLM_MODEL", "deepseek-chat")
    LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 60)
    LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.3") or 0.3)
    LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 1200)
    # 未配置 API Key 时自动降级为“内置规则引擎”，保证系统可独立运行演示
    LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)

    # ---------------- RAG（知识库检索增强） ----------------
    # 制度知识库目录（Markdown 文档，启动/初始化时自动切块入库）
    KNOWLEDGE_DIR = _env("KNOWLEDGE_DIR", str(BASE_DIR / "knowledge"))
    # 知识块长度上限（字符）
    RAG_CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 400)
    # 检索返回条数
    RAG_TOP_K = _env_int("RAG_TOP_K", 4)
    # 是否启用 LLM 重排（把 Top-8 候选交给大模型重排）
    RAG_RERANK = _env_bool("RAG_RERANK", True)

    # ---------------- Agent（多工具编排） ----------------
    # 单次提问最多调用工具步数
    AGENT_MAX_STEPS = _env_int("AGENT_MAX_STEPS", 3)

    # ---------------- 短信平台 ----------------
    # SMS_PROVIDER: none(未接入，仅生成记录并标识) / aliyun / tencent / custom
    SMS_PROVIDER = _env("SMS_PROVIDER", "none").lower()
    SMS_SIGN_NAME = _env("SMS_SIGN_NAME", "【示例公司】")
    SMS_TEMPLATE_CODE = _env("SMS_TEMPLATE_CODE", "")
    SMS_ACCESS_KEY_ID = _env("SMS_ACCESS_KEY_ID", "")
    SMS_ACCESS_KEY_SECRET = _env("SMS_ACCESS_KEY_SECRET", "")
    SMS_ENDPOINT = _env("SMS_ENDPOINT", "")
    SMS_MOCK = _env_bool("SMS_MOCK", True)

    # ---------------- 助手 / 安全 ----------------
    ASSISTANT_MAX_ROWS = _env_int("ASSISTANT_MAX_ROWS", 200)
    PASSWORD_SALT = _env("PASSWORD_SALT", "loan_system_salt")


config = Config()
