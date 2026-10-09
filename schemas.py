from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models import (
    Category,
    DeliveryMethod,
    DocumentType,
    InstructionKind,
    MediaType,
    OrderStatus,
    PaymentMethod,
    Role,
    VerificationStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth / User ----------


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    role: Role = Role.customer

    @field_validator("role")
    @classmethod
    def no_self_admin(cls, v: Role) -> Role:
        if v == Role.admin:
            raise ValueError("Нельзя зарегистрироваться администратором")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)


class UserOut(ORMModel):
    id: int
    email: str
    first_name: str
    last_name: str | None
    role: Role
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Seller / Verification ----------


class SellerUpsert(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=1000)


class VerificationDocOut(ORMModel):
    id: int
    document_type: DocumentType
    original_name: str
    file_hash: str | None
    uploaded_at: datetime
    reviewed_at: datetime | None


class SellerOut(ORMModel):
    id: int
    name: str
    description: str | None
    verification_status: VerificationStatus
    rejection_reason: str | None
    created_at: datetime


class SellerAdminOut(SellerOut):
    user: UserOut
    documents: list[VerificationDocOut]


class SellerPublic(ORMModel):
    id: int
    name: str
    description: str | None
    is_verified: bool


class VerificationDecision(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


# ---------- Product ----------


class SizeTable(BaseModel):
    headers: list[str] = Field(default_factory=list, max_length=10)
    rows: list[list[str]] = Field(default_factory=list, max_length=50)


class InstructionStepIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class InstructionIn(BaseModel):
    kind: InstructionKind
    name: str = Field(min_length=1, max_length=100)
    steps: list[InstructionStepIn] = Field(default_factory=list, max_length=30)


class InstructionStepOut(ORMModel):
    id: int
    name: str
    description: str | None


class InstructionOut(ORMModel):
    id: int
    kind: InstructionKind
    name: str
    steps: list[InstructionStepOut]


class ProductBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category: Category
    composition: str | None = Field(default=None, max_length=500)
    size_table: SizeTable | None = None
    delivery_days: int = Field(default=5, ge=1, le=60)


class ProductCreate(ProductBase):
    instructions: list[InstructionIn] = Field(default_factory=list, max_length=2)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    category: Category | None = None
    composition: str | None = Field(default=None, max_length=500)
    size_table: SizeTable | None = None
    delivery_days: int | None = Field(default=None, ge=1, le=60)
    is_active: bool | None = None
    instructions: list[InstructionIn] | None = Field(default=None, max_length=2)


class MediaOut(ORMModel):
    id: int
    media_type: MediaType
    url: str
    is_main: bool


class ReviewOut(ORMModel):
    id: int
    rating: int
    comment: str | None
    author: str
    created_at: datetime


class ProductListItem(BaseModel):
    id: int
    name: str
    price: Decimal
    category: Category
    delivery_days: int
    image_url: str | None
    rating: float | None
    reviews_count: int
    seller: SellerPublic


class ProductDetail(ProductListItem):
    description: str | None
    composition: str | None
    size_table: SizeTable | None
    is_active: bool
    media: list[MediaOut]
    instructions: list[InstructionOut]
    reviews: list[ReviewOut]


# ---------- Cart / Order ----------


class CartItemIn(BaseModel):
    product_id: int
    size: str | None = Field(default=None, max_length=20)
    amount: int = Field(default=1, ge=1, le=99)


class CartItemUpdate(BaseModel):
    amount: int = Field(ge=1, le=99)


class CartItemOut(BaseModel):
    id: int
    product_id: int
    name: str
    image_url: str | None
    size: str | None
    amount: int
    price: Decimal
    delivery_days: int


class CartOut(BaseModel):
    items: list[CartItemOut]
    total: Decimal
    max_delivery_days: int


class OrderCreate(BaseModel):
    delivery_address: str = Field(min_length=5, max_length=255)
    delivery_method: DeliveryMethod
    payment_method: PaymentMethod


class OrderItemOut(ORMModel):
    product_id: int
    product_name: str
    size: str | None
    amount: int
    price: Decimal


class OrderOut(ORMModel):
    id: int
    status: OrderStatus
    total: Decimal
    delivery_address: str
    delivery_method: DeliveryMethod
    payment_method: PaymentMethod
    tracking_number: str | None
    estimated_delivery_days: int
    created_at: datetime
    paid_at: datetime | None
    items: list[OrderItemOut]
    rated_product_ids: list[int] = []


class OrderCreated(BaseModel):
    order: OrderOut
    payment_url: str


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class PaymentWebhook(BaseModel):
    """Упрощённый формат уведомления ЮKassa (event + object)."""

    event: str
    payment_id: str
    order_id: int
    amount: Decimal
    signature: str


class ReviewCreate(BaseModel):
    order_id: int
    product_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


# ---------- Analytics ----------


class ProductStats(BaseModel):
    product_id: int
    name: str
    units_sold: int
    revenue: Decimal
    rating: float | None
    reviews_count: int


class SellerAnalytics(BaseModel):
    orders_count: int
    units_sold: int
    revenue: Decimal
    products_total: int
    products_with_sales: int
    average_rating: float | None
    products: list[ProductStats]
