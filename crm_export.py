"""Подготовка к интеграции с CRM Битрикс24, бесплатный тариф (ПР-05, быстрый путь, вариант A).

Выгружает тестовые данные из sportmarket.db в CSV для импорта в Битрикс24
(«CRM → Контакты / Сделки → ⚙ → Импорт»). Названия столбцов совпадают с полями CRM
из отчёта ПР-05, поэтому в мастере импорта каждый столбец сопоставляется с одноимённым полем.

    python crm_export.py            # → crm/contacts.csv, crm/deals.csv
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

import models  # noqa: F401 — регистрирует таблицы в Base.metadata
from config import BASE_DIR
from database import SessionLocal
from models import DeliveryMethod, Order, OrderStatus, PaymentMethod, Review, Role, User

OUT_DIR = BASE_DIR / "crm"

# Маппинг значений SportMarket → значения полей и стадий Битрикс24 (таблица маппинга из отчёта).
# Первые три стадии — переименованные стандартные «Новая», «Подготовка документов», «В работе».
STAGES = {
    OrderStatus.new: "Новый заказ",
    OrderStatus.paid: "Оплачен",
    OrderStatus.shipped: "Отправлен",
    OrderStatus.delivered: "Сделка успешна",
    OrderStatus.cancelled: "Сделка провалена",
}
DELIVERY = {
    DeliveryMethod.pickpoint: "Пункт выдачи",
    DeliveryMethod.courier: "Курьер",
    DeliveryMethod.post: "Почта России",
}
PAYMENT = {PaymentMethod.card: "Банковская карта", PaymentMethod.sbp: "СБП", PaymentMethod.yoomoney: "ЮMoney"}
ROLES = {Role.customer: "Покупатель", Role.seller: "Продавец"}


def _date(value: datetime | None) -> str:
    if value is None:
        return ""
    # SQLite возвращает время без часового пояса, хранится оно в UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def _write(path: Path, rows: list[dict]) -> None:
    # UTF-8 с BOM и «;» — так файл без искажений открывается в Excel и читается мастером импорта
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    with SessionLocal() as db:
        users = db.scalars(
            select(User).where(User.role != Role.admin).options(selectinload(User.seller)).order_by(User.id)
        ).all()
        contacts = [
            {
                "Имя": u.first_name,
                "Фамилия": u.last_name or "",
                "Рабочий e-mail": u.email,
                "Роль в SportMarket": ROLES[u.role],
                "Магазин": u.seller.name if u.seller else "",
                "Дата создания": _date(u.created_at),
            }
            for u in users
        ]

        orders = db.scalars(
            select(Order).options(selectinload(Order.items), selectinload(Order.user)).order_by(Order.id)
        ).all()
        ratings = dict(
            db.execute(select(Review.order_id, func.avg(Review.rating)).group_by(Review.order_id)).all()
        )
        deals = [
            {
                "Название сделки": f"Заказ №{o.id}",
                "Сумма": int(o.total),
                "Стадия сделки": STAGES[o.status],
                "Дата начала": _date(o.created_at),
                "Контакт": " ".join(filter(None, [o.user.first_name, o.user.last_name])),
                "Рабочий e-mail": o.user.email,
                "Способ доставки": DELIVERY[o.delivery_method],
                "Адрес доставки": o.delivery_address,
                "Способ оплаты": PAYMENT[o.payment_method],
                "Трек-номер": o.tracking_number or "",
                "Состав заказа": "\n".join(
                    f"{i.product_name}{f' ({i.size})' if i.size else ''} × {i.amount} – {i.price:.0f} ₽"
                    for i in o.items
                ),
                "Дата оплаты": _date(o.paid_at),
                "Оценка покупателя": f"{ratings[o.id]:.1f}".replace(".", ",") if o.id in ratings else "",
            }
            for o in orders
        ]

    if not contacts or not deals:
        raise SystemExit("В базе нет покупателей или заказов — нечего выгружать")
    _write(OUT_DIR / "contacts.csv", contacts)
    _write(OUT_DIR / "deals.csv", deals)
    print(f"crm/contacts.csv: {len(contacts)} контактов, crm/deals.csv: {len(deals)} сделок")


if __name__ == "__main__":
    main()
