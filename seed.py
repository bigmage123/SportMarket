"""Администратор и демо-данные по персонам из ПР-02 (Алексей и «Siberian Core»)."""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import (
    Category,
    Instruction,
    InstructionKind,
    InstructionStep,
    MediaType,
    Product,
    ProductMedia,
    Role,
    Seller,
    User,
    VerificationStatus,
)
from security import hash_password
from services import PUBLIC_MEDIA_PREFIX, storage

logger = logging.getLogger("sportmarket")

DEMO_PASSWORD = "password123"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 450">
<rect width="600" height="450" fill="{bg}"/>
<text x="300" y="215" font-family="Arial, sans-serif" font-size="44" font-weight="700"
 fill="#fff" text-anchor="middle">{title}</text>
<text x="300" y="265" font-family="Arial, sans-serif" font-size="22" fill="#ffffffcc"
 text-anchor="middle">Siberian Core</text></svg>"""

DEMO_PRODUCTS = [
    {
        "name": "Гибридные шорты Core Flex",
        "description": "Шорты для бега и приседаний со штангой. Протестированы на 10 атлетах "
        "в Новосибирске: не сползают в глубоком приседе и не натирают на длинной дистанции.",
        "price": Decimal("2200"),
        "category": Category.hybrid,
        "composition": "88% полиэстер (влагоотводящий), 12% эластан",
        "delivery_days": 4,
        "size_table": {
            "headers": ["Размер", "Обхват талии, см", "Обхват бёдер, см"],
            "rows": [["S", "70–76", "88–94"], ["M", "76–82", "94–100"], ["L", "82–88", "100–106"],
                     ["XL", "88–94", "106–112"]],
        },
        "tech": ["Плоские швы|Не натирают при беге и выпадах",
                 "Влагоотвод|Ткань выводит влагу наружу и сохнет за 20 минут",
                 "Антибактериальная пропитка|Сдерживает запах после интенсивных тренировок"],
        "care": ["Стирка при 30°|Деликатный режим, наизнанку",
                 "Без кондиционера|Кондиционер забивает поры ткани и убивает влагоотвод",
                 "Сушка без машины|Сушить в расправленном виде — сохранит свойства на 80 стирок"],
        "color": "#2f6f4f",
        "title": "Core Flex",
    },
    {
        "name": "Футболка Taiga Dry",
        "description": "Влагоотводящая футболка с плоскими швами для силовых и кардио.",
        "price": Decimal("2900"),
        "category": Category.strength,
        "composition": "92% полиамид, 8% эластан",
        "delivery_days": 5,
        "size_table": {
            "headers": ["Размер", "Обхват груди, см", "Длина, см"],
            "rows": [["S", "88–94", "68"], ["M", "94–100", "70"], ["L", "100–106", "72"]],
        },
        "tech": ["Сетчатые вставки|Вентиляция в зонах сильного потоотделения",
                 "Плоские швы|Не натирают под лямками рюкзака и штангой"],
        "care": ["Стирка при 30°|Без отбеливателей", "Не гладить|Ткань не мнётся"],
        "color": "#34506b",
        "title": "Taiga Dry",
    },
    {
        "name": "Беговые тайтсы Ob River",
        "description": "Утеплённые тайтсы для бега в межсезонье, с карманом под телефон.",
        "price": Decimal("3400"),
        "category": Category.running,
        "composition": "80% полиэстер, 20% эластан, начёс",
        "delivery_days": 7,
        "size_table": {
            "headers": ["Размер", "Обхват талии, см", "Рост, см"],
            "rows": [["M", "76–82", "170–180"], ["L", "82–88", "175–185"]],
        },
        "tech": ["Начёс|Держит тепло до −5 °C", "Светоотражатели|Видно в темноте с 150 м"],
        "care": ["Стирка при 30°|В мешке для стирки"],
        "color": "#7a4b2a",
        "title": "Ob River",
    },
]


def _steps(raw: list[str]) -> list[InstructionStep]:
    return [
        InstructionStep(position=i, name=s.split("|")[0], description=s.split("|")[1])
        for i, s in enumerate(raw)
    ]


def _placeholder(product_key: str, title: str, color: str) -> str:
    object_key = f"{PUBLIC_MEDIA_PREFIX}/products/demo/{product_key}.svg"
    path = storage.path(object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SVG.format(bg=color, title=title), encoding="utf-8")
    return object_key


def _user(db: Session, email: str, first_name: str, role: Role, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, first_name=first_name, role=role, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    return user


def seed(db: Session) -> None:
    # Картинки демо-товаров лежат в storage/ и пересоздаются, если папку очистили
    for idx, data in enumerate(DEMO_PRODUCTS):
        _placeholder(f"p{idx}", data["title"], data["color"])
    _user(db, settings.admin_email.lower(), "Администратор", Role.admin, settings.admin_password)

    if settings.seed_demo_data and db.scalar(select(Seller.id).limit(1)) is None:
        _user(db, "alexey@demo.ru", "Алексей", Role.customer, DEMO_PASSWORD)
        owner = _user(db, "kaban@siberiancore.ru", "Кабан Кабаныч", Role.seller, DEMO_PASSWORD)
        shop = Seller(
            user_id=owner.id,
            name="Siberian Core",
            description="Локальное производство гибридной спортивной экипировки. Новосибирск.",
            verification_status=VerificationStatus.verified,
        )
        db.add(shop)
        for idx, data in enumerate(DEMO_PRODUCTS):
            product = Product(
                seller=shop,
                name=data["name"],
                description=data["description"],
                price=data["price"],
                category=data["category"],
                composition=data["composition"],
                delivery_days=data["delivery_days"],
                size_table=data["size_table"],
                instructions=[
                    Instruction(kind=InstructionKind.technology, name="Технологии", steps=_steps(data["tech"])),
                    Instruction(kind=InstructionKind.care, name="Уход", steps=_steps(data["care"])),
                ],
                media=[
                    ProductMedia(
                        media_type=MediaType.photo,
                        object_key=_placeholder(f"p{idx}", data["title"], data["color"]),
                        is_main=True,
                    )
                ],
            )
            db.add(product)
        logger.info("Созданы демо-данные: alexey@demo.ru / kaban@siberiancore.ru, пароль %s", DEMO_PASSWORD)
    db.commit()
