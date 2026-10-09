"""ORM-модели по ER-диаграмме из ПР-03.

Отличия от диаграммы, необходимые для работающего MVP:
- Order ссылается на User и хранит позиции в OrderItem (снимок цены), а не на Cart:
  у пользователя одна корзина, но много заказов.
- Review привязан к товару (product_id) — связь Product : Review 1:N из таблицы связей.
- Product хранит состав, размерную таблицу и срок доставки (User Stories MVP).
- Instruction имеет вид: technology / care — вкладки «Технологии» и «Уход» в карточке.
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    customer = "customer"
    seller = "seller"
    admin = "admin"


class VerificationStatus(str, enum.Enum):
    draft = "draft"  # профиль создан, документы ещё не отправлены
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class DocumentType(str, enum.Enum):
    inn = "inn"
    ogrn = "ogrn"
    passport = "passport"


class Category(str, enum.Enum):
    running = "running"
    strength = "strength"
    hybrid = "hybrid"


class MediaType(str, enum.Enum):
    photo = "photo"
    video = "video"


class InstructionKind(str, enum.Enum):
    technology = "technology"
    care = "care"


class OrderStatus(str, enum.Enum):
    new = "new"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class DeliveryMethod(str, enum.Enum):
    pickpoint = "pickpoint"
    courier = "courier"
    post = "post"


class PaymentMethod(str, enum.Enum):
    card = "card"
    sbp = "sbp"
    yoomoney = "yoomoney"


def _enum(cls):
    return Enum(cls, native_enum=False, length=20)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.customer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow)

    seller: Mapped["Seller | None"] = relationship(back_populates="user", uselist=False)
    cart: Mapped["Cart | None"] = relationship(back_populates="user", uselist=False)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(1000))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus), default=VerificationStatus.draft
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="seller")
    documents: Mapped[list["VerificationDoc"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )
    products: Mapped[list["Product"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )


class VerificationDoc(Base):
    __tablename__ = "verification_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    document_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType))
    original_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seller: Mapped[Seller] = relationship(back_populates="documents")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[Category] = mapped_column(_enum(Category))
    composition: Mapped[str | None] = mapped_column(String(500))
    # {"headers": ["Размер", "Обхват талии"], "rows": [["M", "76-80"], ...]}
    size_table: Mapped[dict | None] = mapped_column(JSON)
    delivery_days: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow)

    seller: Mapped[Seller] = relationship(back_populates="products")
    media: Mapped[list["ProductMedia"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by=lambda: [ProductMedia.is_main.desc(), ProductMedia.id],
    )
    instructions: Mapped[list["Instruction"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(back_populates="product")


class ProductMedia(Base):
    __tablename__ = "product_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    media_type: Mapped[MediaType] = mapped_column(_enum(MediaType), default=MediaType.photo)
    object_key: Mapped[str] = mapped_column(String(255))
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="media")


class Instruction(Base):
    __tablename__ = "instructions"
    __table_args__ = (UniqueConstraint("product_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    kind: Mapped[InstructionKind] = mapped_column(_enum(InstructionKind))
    name: Mapped[str] = mapped_column(String(100))

    product: Mapped[Product] = relationship(back_populates="instructions")
    steps: Mapped[list["InstructionStep"]] = relationship(
        back_populates="instruction",
        cascade="all, delete-orphan",
        order_by="InstructionStep.position",
    )


class InstructionStep(Base):
    __tablename__ = "instruction_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    instruction_id: Mapped[int] = mapped_column(ForeignKey("instructions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(1000))

    instruction: Mapped[Instruction] = relationship(back_populates="steps")


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    user: Mapped[User] = relationship(back_populates="cart")
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.id"
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id", "size"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    size: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer, default=1)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.new)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    delivery_address: Mapped[str] = mapped_column(String(255))
    delivery_method: Mapped[DeliveryMethod] = mapped_column(_enum(DeliveryMethod))
    payment_method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod))
    payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    estimated_delivery_days: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(100))
    size: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("order_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="reviews")
    user: Mapped[User] = relationship()
