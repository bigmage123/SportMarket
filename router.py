from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import repository as repo
import schemas
from models import (
    CartItem,
    DocumentType,
    MediaType,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductMedia,
    Review,
    Role,
    Seller,
    User,
    VerificationDoc,
    VerificationStatus,
)
from security import (
    Admin,
    CurrentSeller,
    CurrentUser,
    Customer,
    DbSession,
    SellerUser,
    create_access_token,
    hash_password,
    verify_password,
)
from services import (
    DOC_EXT,
    PHOTO_EXT,
    PUBLIC_MEDIA_PREFIX,
    VIDEO_EXT,
    generate_tracking_number,
    payment_gateway,
    send_email,
    storage,
)

api = APIRouter(prefix="/api")


# ============================================================ Auth / профиль

auth = APIRouter(prefix="/auth", tags=["auth"])


@auth.post("/register", response_model=schemas.TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: schemas.UserRegister, db: DbSession):
    if repo.get_user_by_email(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким email уже существует")
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        first_name=data.first_name.strip(),
        last_name=data.last_name,
        role=data.role,
    )
    db.add(user)
    db.commit()
    return schemas.TokenOut(
        access_token=create_access_token(user), user=schemas.UserOut.model_validate(user)
    )


@auth.post("/login", response_model=schemas.TokenOut)
def login(data: schemas.UserLogin, db: DbSession):
    user = repo.get_user_by_email(db, data.email)
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    return schemas.TokenOut(
        access_token=create_access_token(user), user=schemas.UserOut.model_validate(user)
    )


users = APIRouter(prefix="/users", tags=["users"])


@users.get("/me", response_model=schemas.UserOut)
def me(user: CurrentUser):
    return user


@users.patch("/me", response_model=schemas.UserOut)
def update_me(data: schemas.UserUpdate, user: CurrentUser, db: DbSession):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    return user


# ============================================================ Продавец

seller = APIRouter(prefix="/seller", tags=["seller"])


@seller.get("/profile", response_model=schemas.SellerOut | None)
def get_seller_profile(user: SellerUser):
    return user.seller


@seller.put("/profile", response_model=schemas.SellerOut)
def upsert_seller_profile(data: schemas.SellerUpsert, user: SellerUser, db: DbSession):
    profile = user.seller or Seller(user_id=user.id)
    profile.name = data.name.strip()
    profile.description = data.description
    db.add(profile)
    db.commit()
    return profile


@seller.get("/documents", response_model=list[schemas.VerificationDocOut])
def list_documents(profile: CurrentSeller):
    return profile.documents


@seller.post(
    "/documents", response_model=schemas.VerificationDocOut, status_code=status.HTTP_201_CREATED
)
def upload_document(
    profile: CurrentSeller,
    db: DbSession,
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
):
    if profile.verification_status == VerificationStatus.verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Магазин уже верифицирован")
    object_key, file_hash = storage.put(f"private/docs/{profile.id}", file, DOC_EXT)
    doc = VerificationDoc(
        seller_id=profile.id,
        document_type=document_type,
        original_name=(file.filename or "document")[:255],
        object_key=object_key,
        file_hash=file_hash,
    )
    db.add(doc)
    # Загрузка документа отправляет заявку на проверку модератору
    profile.verification_status = VerificationStatus.pending
    profile.rejection_reason = None
    db.commit()
    return doc


@seller.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, profile: CurrentSeller, db: DbSession):
    doc = db.get(VerificationDoc, doc_id)
    if doc is None or doc.seller_id != profile.id:
        raise repo.not_found("Документ")
    if profile.verification_status == VerificationStatus.verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Документы верифицированного магазина не удаляются")
    storage.delete(doc.object_key)
    profile.documents.remove(doc)
    if not profile.documents:
        profile.verification_status = VerificationStatus.draft
    db.commit()


@seller.get("/products", response_model=list[schemas.ProductListItem])
def my_products(profile: CurrentSeller, db: DbSession):
    return repo.seller_products(db, profile)


def _own_product(db, profile: Seller, product_id: int) -> Product:
    product = repo.get_product(db, product_id)
    if product.seller_id != profile.id:
        raise repo.not_found("Товар")
    return product


@seller.get("/products/{product_id}", response_model=schemas.ProductDetail)
def my_product(product_id: int, profile: CurrentSeller, db: DbSession):
    return repo.to_detail(db, _own_product(db, profile, product_id))


@seller.post("/products", response_model=schemas.ProductDetail, status_code=status.HTTP_201_CREATED)
def create_product(data: schemas.ProductCreate, profile: CurrentSeller, db: DbSession):
    product = Product(
        seller_id=profile.id,
        **data.model_dump(exclude={"instructions", "size_table"}),
        size_table=data.size_table.model_dump() if data.size_table else None,
    )
    repo.set_instructions(product, data.instructions)
    db.add(product)
    db.commit()
    return repo.to_detail(db, repo.get_product(db, product.id))


@seller.patch("/products/{product_id}", response_model=schemas.ProductDetail)
def update_product(
    product_id: int, data: schemas.ProductUpdate, profile: CurrentSeller, db: DbSession
):
    product = _own_product(db, profile, product_id)
    fields = data.model_dump(exclude_unset=True, exclude={"instructions", "size_table"})
    for field, value in fields.items():
        if value is None and field in {"name", "price", "category", "delivery_days", "is_active"}:
            continue
        setattr(product, field, value)
    if "size_table" in data.model_fields_set:
        product.size_table = data.size_table.model_dump() if data.size_table else None
    if data.instructions is not None:
        repo.set_instructions(product, data.instructions)
    db.commit()
    return repo.to_detail(db, repo.get_product(db, product.id))


@seller.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, profile: CurrentSeller, db: DbSession):
    product = _own_product(db, profile, product_id)
    if db.scalar(select(exists().where(OrderItem.product_id == product.id))):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Товар уже есть в заказах — его можно только снять с продажи",
        )
    for m in product.media:
        storage.delete(m.object_key)
    db.delete(product)
    db.commit()


@seller.post(
    "/products/{product_id}/media",
    response_model=schemas.ProductDetail,
    status_code=status.HTTP_201_CREATED,
)
def upload_media(
    product_id: int,
    profile: CurrentSeller,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    is_main: Annotated[bool, Form()] = False,
):
    product = _own_product(db, profile, product_id)
    suffix = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
    media_type = MediaType.video if suffix in VIDEO_EXT else MediaType.photo
    object_key, _ = storage.put(
        f"{PUBLIC_MEDIA_PREFIX}/products/{product.id}", file, PHOTO_EXT | VIDEO_EXT
    )
    has_photos = any(m.media_type == MediaType.photo for m in product.media)
    make_main = media_type == MediaType.photo and (is_main or not has_photos)
    if make_main:
        for m in product.media:
            m.is_main = False
    product.media.append(ProductMedia(media_type=media_type, object_key=object_key, is_main=make_main))
    db.commit()
    db.expire(product)
    return repo.to_detail(db, repo.get_product(db, product.id))


@seller.delete("/products/{product_id}/media/{media_id}", response_model=schemas.ProductDetail)
def delete_media(product_id: int, media_id: int, profile: CurrentSeller, db: DbSession):
    product = _own_product(db, profile, product_id)
    media = next((m for m in product.media if m.id == media_id), None)
    if media is None:
        raise repo.not_found("Файл")
    storage.delete(media.object_key)
    product.media.remove(media)
    if media.is_main:
        next_photo = next((m for m in product.media if m.media_type == MediaType.photo), None)
        if next_photo:
            next_photo.is_main = True
    db.commit()
    db.expire(product)
    return repo.to_detail(db, repo.get_product(db, product.id))


@seller.get("/analytics", response_model=schemas.SellerAnalytics)
def analytics(profile: CurrentSeller, db: DbSession):
    return repo.seller_analytics(db, profile)


@seller.get("/orders", response_model=list[schemas.OrderOut])
def seller_orders(profile: CurrentSeller, db: DbSession):
    return [repo.order_out(db, o) for o in repo.seller_orders(db, profile)]


SELLER_TRANSITIONS = {
    OrderStatus.paid: {OrderStatus.shipped},
    OrderStatus.shipped: {OrderStatus.delivered},
}


@seller.patch("/orders/{order_id}/status", response_model=schemas.OrderOut)
def seller_update_order_status(
    order_id: int, data: schemas.OrderStatusUpdate, profile: CurrentSeller, db: DbSession
):
    order = repo.get_order(db, order_id)
    if not any(i.seller_id == profile.id for i in order.items):
        raise repo.not_found("Заказ")
    if data.status not in SELLER_TRANSITIONS.get(order.status, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Нельзя перевести заказ из «{order.status.value}» в «{data.status.value}»",
        )
    order.status = data.status
    db.commit()
    return repo.order_out(db, order)


# ============================================================ Каталог (публично)

catalog = APIRouter(prefix="/products", tags=["catalog"])


@catalog.get("", response_model=list[schemas.ProductListItem])
def list_products(
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return repo.search_products(db, q, category, limit, offset)


@catalog.get("/{product_id}", response_model=schemas.ProductDetail)
def product_detail(product_id: int, db: DbSession):
    product = repo.get_product(db, product_id)
    if not repo.is_publicly_visible(product):
        raise repo.not_found("Товар")
    return repo.to_detail(db, product)


# ============================================================ Корзина

cart = APIRouter(prefix="/cart", tags=["cart"])


@cart.get("", response_model=schemas.CartOut)
def get_cart(user: Customer, db: DbSession):
    c = repo.get_or_create_cart(db, user)
    db.commit()
    return repo.cart_out(c)


@cart.post("/items", response_model=schemas.CartOut, status_code=status.HTTP_201_CREATED)
def add_to_cart(data: schemas.CartItemIn, user: Customer, db: DbSession):
    product = repo.get_product(db, data.product_id)
    if not repo.is_publicly_visible(product):
        raise repo.not_found("Товар")
    sizes = [row[0] for row in (product.size_table or {}).get("rows", []) if row]
    if sizes and data.size not in sizes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Выберите размер из таблицы")
    c = repo.get_or_create_cart(db, user)
    size = data.size if sizes else None
    item = next((i for i in c.items if i.product_id == product.id and i.size == size), None)
    if item:
        item.amount = min(item.amount + data.amount, 99)
    else:
        c.items.append(CartItem(product=product, size=size, amount=data.amount))
    db.commit()
    return repo.cart_out(repo.get_or_create_cart(db, user))


def _own_cart_item(db, user: User, item_id: int) -> CartItem:
    item = db.get(CartItem, item_id)
    if item is None or item.cart.user_id != user.id:
        raise repo.not_found("Позиция корзины")
    return item


@cart.patch("/items/{item_id}", response_model=schemas.CartOut)
def update_cart_item(item_id: int, data: schemas.CartItemUpdate, user: Customer, db: DbSession):
    _own_cart_item(db, user, item_id).amount = data.amount
    db.commit()
    return repo.cart_out(repo.get_or_create_cart(db, user))


@cart.delete("/items/{item_id}", response_model=schemas.CartOut)
def delete_cart_item(item_id: int, user: Customer, db: DbSession):
    db.delete(_own_cart_item(db, user, item_id))
    db.commit()
    return repo.cart_out(repo.get_or_create_cart(db, user))


# ============================================================ Заказы и оплата

orders = APIRouter(prefix="/orders", tags=["orders"])


@orders.post("", response_model=schemas.OrderCreated, status_code=status.HTTP_201_CREATED)
def create_order(data: schemas.OrderCreate, user: Customer, db: DbSession):
    order = repo.create_order_from_cart(db, user, data)
    order.payment_id, payment_url = payment_gateway.create_payment(order.id, order.total)
    db.commit()
    return schemas.OrderCreated(order=repo.order_out(db, order), payment_url=payment_url)


@orders.get("", response_model=list[schemas.OrderOut])
def my_orders(user: Customer, db: DbSession):
    return [repo.order_out(db, o) for o in repo.user_orders(db, user)]


def _own_order(db, user: User, order_id: int) -> Order:
    order = repo.get_order(db, order_id)
    if order.user_id != user.id:
        raise repo.not_found("Заказ")
    return order


@orders.get("/{order_id}", response_model=schemas.OrderOut)
def my_order(order_id: int, user: Customer, db: DbSession):
    return repo.order_out(db, _own_order(db, user, order_id))


@orders.post("/{order_id}/cancel", response_model=schemas.OrderOut)
def cancel_order(order_id: int, user: Customer, db: DbSession):
    order = _own_order(db, user, order_id)
    if order.status != OrderStatus.new:
        raise HTTPException(status.HTTP_409_CONFLICT, "Отменить можно только неоплаченный заказ")
    order.status = OrderStatus.cancelled
    db.commit()
    return repo.order_out(db, order)


@orders.post("/{order_id}/confirm-delivery", response_model=schemas.OrderOut)
def confirm_delivery(order_id: int, user: Customer, db: DbSession):
    order = _own_order(db, user, order_id)
    if order.status not in (OrderStatus.paid, OrderStatus.shipped):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заказ ещё не оплачен или уже получен")
    order.status = OrderStatus.delivered
    db.commit()
    return repo.order_out(db, order)


def _order_confirmation_email(order_id: int) -> None:
    from database import SessionLocal

    with SessionLocal() as db:
        order = db.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items), selectinload(Order.user))
        )
        if order is None:
            return
        lines = "".join(
            f"<li>{i.product_name}{f' ({i.size})' if i.size else ''} × {i.amount} — {i.price} ₽</li>"
            for i in order.items
        )
        send_email(
            order.user.email,
            f"Заказ №{order.id} оплачен",
            f"<p>Спасибо за покупку, {order.user.first_name}!</p><ul>{lines}</ul>"
            f"<p>Сумма: {order.total} ₽. Трек-номер: <b>{order.tracking_number}</b>. "
            f"Ожидаемый срок доставки: до {order.estimated_delivery_days} дн.</p>",
        )


payments = APIRouter(tags=["payments"])


def process_payment_webhook(
    db, data: schemas.PaymentWebhook, background: BackgroundTasks
) -> Order:
    if not payment_gateway.verify(data.payment_id, data.order_id, data.amount, data.signature):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная подпись webhook")
    order = repo.get_order(db, data.order_id)
    if order.payment_id != data.payment_id or order.total != data.amount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Платёж не соответствует заказу")
    if data.event != "payment.succeeded":
        return order
    # Идемпотентность: повторный webhook не меняет уже оплаченный заказ
    if order.status == OrderStatus.new:
        order.status = OrderStatus.paid
        order.paid_at = datetime.now(timezone.utc)
        order.tracking_number = generate_tracking_number()
        db.commit()
        background.add_task(_order_confirmation_email, order.id)
    return order


@payments.post("/webhooks/yookassa")
def yookassa_webhook(data: schemas.PaymentWebhook, db: DbSession, background: BackgroundTasks):
    process_payment_webhook(db, data, background)
    return {"status": "ok"}


@payments.post("/payments/test/{order_id}/pay", response_model=schemas.OrderOut)
def test_pay(order_id: int, user: Customer, db: DbSession, background: BackgroundTasks):
    """Тестовая страница ЮKassa: имитирует оплату и отправку webhook от шлюза."""
    order = _own_order(db, user, order_id)
    if order.status != OrderStatus.new:
        raise HTTPException(status.HTTP_409_CONFLICT, "Заказ уже оплачен или отменён")
    webhook = schemas.PaymentWebhook(
        event="payment.succeeded",
        payment_id=order.payment_id,
        order_id=order.id,
        amount=order.total,
        signature=payment_gateway.sign(order.payment_id, order.id, order.total),
    )
    return repo.order_out(db, process_payment_webhook(db, webhook, background))


# ============================================================ Оценки

reviews = APIRouter(prefix="/reviews", tags=["reviews"])


@reviews.post("", response_model=schemas.ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(data: schemas.ReviewCreate, user: Customer, db: DbSession):
    order = _own_order(db, user, data.order_id)
    if order.status != OrderStatus.delivered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Оценить товар можно после получения заказа")
    if not any(i.product_id == data.product_id for i in order.items):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Этого товара нет в заказе")
    review = Review(
        order_id=order.id,
        product_id=data.product_id,
        user_id=user.id,
        rating=data.rating,
        comment=(data.comment or "").strip() or None,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Вы уже оценили этот товар в этом заказе")
    return schemas.ReviewOut(
        id=review.id,
        rating=review.rating,
        comment=review.comment,
        author=user.first_name,
        created_at=review.created_at,
    )


# ============================================================ Документы и администрирование

documents = APIRouter(prefix="/documents", tags=["documents"])


@documents.get("/{doc_id}/file")
def download_document(doc_id: int, user: CurrentUser, db: DbSession):
    doc = db.get(VerificationDoc, doc_id)
    is_owner = doc is not None and user.seller is not None and doc.seller_id == user.seller.id
    if doc is None or not (is_owner or user.role == Role.admin):
        raise repo.not_found("Документ")
    return FileResponse(storage.path(doc.object_key), filename=doc.original_name)


admin = APIRouter(prefix="/admin", tags=["admin"])


@admin.get("/sellers", response_model=list[schemas.SellerAdminOut])
def admin_sellers(
    _: Admin, db: DbSession, verification_status: VerificationStatus | None = None
):
    stmt = select(Seller).options(selectinload(Seller.user), selectinload(Seller.documents))
    if verification_status:
        stmt = stmt.where(Seller.verification_status == verification_status)
    return db.scalars(stmt.order_by(Seller.created_at.desc())).all()


@admin.post("/sellers/{seller_id}/verification", response_model=schemas.SellerAdminOut)
def decide_verification(
    seller_id: int,
    data: schemas.VerificationDecision,
    _: Admin,
    db: DbSession,
    background: BackgroundTasks,
):
    profile = db.get(Seller, seller_id)
    if profile is None:
        raise repo.not_found("Продавец")
    if not profile.documents:
        raise HTTPException(status.HTTP_409_CONFLICT, "Продавец не загрузил документы")
    if not data.approve and not data.reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите причину отказа")
    now = datetime.now(timezone.utc)
    profile.verification_status = (
        VerificationStatus.verified if data.approve else VerificationStatus.rejected
    )
    profile.rejection_reason = None if data.approve else data.reason
    for doc in profile.documents:
        doc.reviewed_at = now
    db.commit()
    text = (
        "Ваш магазин прошёл верификацию — товары видны покупателям."
        if data.approve
        else f"Верификация отклонена: {data.reason}. Загрузите исправленные документы."
    )
    background.add_task(send_email, profile.user.email, "Результат верификации SportMarket", f"<p>{text}</p>")
    return profile


@admin.patch("/products/{product_id}/moderate", response_model=schemas.ProductDetail)
def moderate_product(product_id: int, is_active: bool, _: Admin, db: DbSession):
    product = repo.get_product(db, product_id)
    product.is_active = is_active
    db.commit()
    return repo.to_detail(db, product)


for r in (auth, users, seller, catalog, cart, orders, payments, reviews, documents, admin):
    api.include_router(r)
