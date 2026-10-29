"""全局配置：全部通过环境变量注入，默认值保证「无 API Key 也能跑通全流程」。"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 必须在读取环境变量之前加载 backend/.env
load_dotenv(BASE_DIR / ".env", override=False)


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip() or default
    p = Path(raw)
    return p if p.is_absolute() else (BASE_DIR / p)


@dataclass
class Settings:
    # --- DeepSeek ---
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.35"))
    request_timeout: float = float(os.getenv("LLM_TIMEOUT", "120"))
    llm_retries: int = int(os.getenv("LLM_RETRIES", "2"))
    llm_backoff: float = float(os.getenv("LLM_BACKOFF", "0.8"))
    # 连续失败多少次后整体降级（401/402 立即降级）
    degrade_after_failures: int = int(os.getenv("LLM_DEGRADE_AFTER", "3"))

    # --- 运行模式 ---
    # MOCK_LLM=auto 时：有 Key 走真实模型，无 Key 自动降级到内置演示引擎
    mock_mode_raw: str = os.getenv("MOCK_LLM", "auto")
    mock_delay: float = float(os.getenv("MOCK_STREAM_DELAY", "0.012"))

    # --- 上传限制 ---
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    max_resume_chars: int = int(os.getenv("MAX_RESUME_CHARS", "30000"))

    # --- OCR（扫描件） ---
    ocr_enabled: bool = _flag("OCR_ENABLED", True)
    ocr_min_chars: int = int(os.getenv("OCR_MIN_CHARS", "50"))
    ocr_dpi: int = int(os.getenv("OCR_DPI", "200"))
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "8"))
    ocr_lang: str = os.getenv("OCR_LANG", "chi_sim+eng")
    ocr_banding: bool = _flag("OCR_BANDING", True)

    # --- RAG ---
    chroma_dir: str = os.getenv("CHROMA_DIR", str(BASE_DIR / "data" / "chroma"))
    rag_enabled: bool = _flag("RAG_ENABLED", True)

    # --- 持久化 ---
    db_path: Path = field(default_factory=lambda: _path("DB_PATH", "data/resumepilot.db"))

    # --- 用户体系（JWT） ---
    jwt_secret_raw: str = os.getenv("JWT_SECRET", "").strip()
    jwt_ttl_hours: int = int(os.getenv("JWT_TTL_HOURS", "168"))  # 7 天
    jwt_cookie: str = "rp_token"

    # --- 邮件（模拟投递） ---
    smtp_host: str = os.getenv("SMTP_HOST", "").strip()
    smtp_port: int = int(os.getenv("SMTP_PORT", "465"))
    smtp_user: str = os.getenv("SMTP_USER", "").strip()
    smtp_password: str = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "ResumePilot Pro").strip()
    smtp_ssl: bool = _flag("SMTP_SSL", True)

    # --- 杂项 ---
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    @property
    def jwt_secret(self) -> str:
        """未显式配置时持久化到 data/.jwt_secret，避免重启把所有人踢下线。"""
        if self.jwt_secret_raw:
            return self.jwt_secret_raw
        path = self.data_dir / ".jwt_secret"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        secret = secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret, encoding="utf-8")
        return secret

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def mock(self) -> bool:
        raw = self.mock_mode_raw.strip().lower()
        if raw in {"1", "true", "on", "yes", "mock"}:
            return True
        if raw in {"0", "false", "off", "no"}:
            return False
        return not bool(self.deepseek_api_key)

    @property
    def llm_label(self) -> str:
        return "内置演示引擎 (MOCK)" if self.mock else f"DeepSeek · {self.deepseek_model}"


settings = Settings()
