"""Внешние сервисы из архитектуры ПР-03 в упрощённом для MVP виде.

- FileStorage — локальная замена MinIO (тот же интерфейс put/open/delete по object_key).
- PaymentGateway — тестовая заглушка ЮKassa: ссылка на оплату + подписанный webhook.
- EmailSender — Resend, если задан RESEND_API_KEY, иначе вывод письма в лог.
Celery заменён на BackgroundTasks FastAPI (см. router.py).
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile, status

from config import settings

logger = logging.getLogger("sportmarket")


class FileStorage:
    def __init__(self, root: Path):
        self.root = root

    def put(self, prefix: str, upload: UploadFile, allowed: set[str]) -> tuple[str, str]:
        """Сохраняет файл, возвращает (object_key, sha256)."""
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in allowed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Недопустимый формат файла. Разрешены: {', '.join(sorted(allowed))}",
            )
        data = upload.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"Файл больше {settings.max_upload_mb} МБ",
            )
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Пустой файл")
        object_key = f"{prefix}/{uuid.uuid4().hex}{suffix}"
        path = self.path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return object_key, hashlib.sha256(data).hexdigest()

    def path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный путь")
        return path

    def delete(self, object_key: str) -> None:
        self.path(object_key).unlink(missing_ok=True)


storage = FileStorage(settings.storage_dir)

PUBLIC_MEDIA_PREFIX = "public"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}
DOC_EXT = {".pdf", ".jpg", ".jpeg", ".png"}


def media_url(object_key: str) -> str:
    return f"/media/{object_key.removeprefix(PUBLIC_MEDIA_PREFIX + '/')}"


class MockYooKassa:
    """Имитация ЮKassa: создаёт платёж и подписывает webhook HMAC-ом."""

    def create_payment(self, order_id: int, amount: Decimal) -> tuple[str, str]:
        payment_id = f"pay_{secrets.token_hex(8)}"
        payment_url = f"/#/pay/{order_id}?payment_id={payment_id}"
        logger.info("ЮKassa(test): создан платёж %s на %s ₽ для заказа %s", payment_id, amount, order_id)
        return payment_id, payment_url

    @staticmethod
    def sign(payment_id: str, order_id: int, amount: Decimal) -> str:
        message = f"{payment_id}:{order_id}:{Decimal(amount):.2f}".encode()
        return hmac.new(settings.payment_webhook_secret.encode(), message, hashlib.sha256).hexdigest()

    def verify(self, payment_id: str, order_id: int, amount: Decimal, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payment_id, order_id, amount), signature)


payment_gateway = MockYooKassa()


def generate_tracking_number() -> str:
    return f"SM{secrets.randbelow(10**10):010d}RU"


def send_email(to: str, subject: str, html: str) -> None:
    if not settings.resend_api_key:
        logger.info("EMAIL → %s | %s\n%s", to, subject, html)
        return
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Не удалось отправить письмо %s", to)
