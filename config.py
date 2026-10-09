import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

# На Vercel файловая система только для чтения, писать можно лишь в /tmp.
# Данные там временные: живут, пока жив инстанс функции.
DATA_DIR = Path("/tmp/sportmarket") if os.environ.get("VERCEL") else BASE_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "SportMarket"
    database_url: str = f"sqlite:///{DATA_DIR / 'sportmarket.db'}"

    jwt_secret: str = "change-me-in-production-please-32b-min"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Локальное файловое хранилище (замена MinIO для MVP)
    storage_dir: Path = DATA_DIR / "storage"
    max_upload_mb: int = 20

    # Платёжный шлюз: в MVP используется тестовая заглушка ЮKassa
    payment_webhook_secret: str = "yookassa-test-secret"

    # Email: если ключ Resend не задан, письма пишутся в лог
    resend_api_key: str | None = None
    email_from: str = "SportMarket <noreply@sportmarket.ru>"

    admin_email: str = "admin@sportmarket.ru"
    admin_password: str = "admin12345"
    seed_demo_data: bool = True


settings = Settings()
