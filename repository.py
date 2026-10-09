from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

import schemas
from models import (
    Cart,
    CartItem,
    Instruction,
    InstructionStep,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    Review,
    Seller,
    User,
    VerificationStatus,
)
from services import media_url

# Заказы в этих статусах считаются продажей
SOLD_STATUSES = (OrderStatus.paid, OrderStatus.shipped, OrderStatus.delivered)


def not_found(what: str = "Объект") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} не найден")


# ---------- Users ----------


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


# ---------- Ratings ----------


def rating_stats(db: Session, product_ids: list[int]) -> dict[int, tuple[float | None, int]]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(Review.product_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.product_id.in_(product_ids))
        .group_by(Review.product_id)
    ).all()
    stats = {pid: (round(float(avg), 2), cnt) for pid, avg, cnt in rows}
    return {pid: stats.get(pid, (None, 0)) for pid in product_ids}


# ---------- Products ----------


def _seller_public(seller: Seller) -> schemas.SellerPublic:
    return schemas.SellerPublic(
        id=seller.id,
        name=seller.name,
        description=seller.description,
        is_verified=seller.verification_status == VerificationStatus.verified,
    )


def _main_image(product: Product) -> str | None:
    photos = [m for m in product.media if m.media_type.value == "photo"]
    return media_url(photos[0].object_key) if photos else None


def to_list_item(product: Product, stats: tuple[float | None, int]) -> schemas.ProductListItem:
    return schemas.ProductListItem(
        id=product.id,
        name=product.name,
        price=product.price,
        category=product.category,
        delivery_days=product.delivery_days,
        image_url=_main_image(product),
        rating=stats[0],
        reviews_count=stats[1],
        seller=_seller_public(product.seller),
    )


def to_detail(db: Session, product: Product) -> schemas.ProductDetail:
    stats = rating_stats(db, [product.id])[product.id]
    reviews = db.scalars(
        select(Review)
        .where(Review.product_id == product.id)
        .options(selectinload(Review.user))
        .order_by(Review.created_at.desc())
    ).all()
    base = to_list_item(product, stats)
    return schemas.ProductDetail(
        **base.model_dump(),
        description=product.description,
        composition=product.composition,
        size_table=product.size_table,
        is_active=product.is_active,
        media=[
            schemas.MediaOut(
                id=m.id, media_type=m.media_type, url=media_url(m.object_key), is_main=m.is_main
            )
            for m in product.media
        ],
        instructions=[schemas.InstructionOut.model_validate(i) for i in product.instructions],
        reviews=[
            schemas.ReviewOut(
                id=r.id,
                rating=r.rating,
                comment=r.comment,
                author=r.user.first_name,
                created_at=r.created_at,
            )
            for r in reviews
        ],
    )


def _product_query():
    return select(Product).options(
        selectinload(Product.seller),
        selectinload(Product.media),
        selectinload(Product.instructions).selectinload(Instruction.steps),
    )


def search_products(
    db: Session, q: str | None, category: str | None, limit: int, offset: int
) -> list[schemas.ProductListItem]:
    """Каталог: только активные товары верифицированных продавцов."""
    stmt = (
        _product_query()
        .join(Product.seller)
        .where(Product.is_active, Seller.verification_status == VerificationStatus.verified)
    )
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Product.name).like(pattern), func.lower(Product.description).like(pattern))
        )
    if category:
        stmt = stmt.where(Product.category == category)
    products = db.scalars(stmt.order_by(Product.created_at.desc()).limit(limit).offset(offset)).all()
    stats = rating_stats(db, [p.id for p in products])
    return [to_list_item(p, stats[p.id]) for p in products]


def get_product(db: Session, product_id: int) -> Product:
    product = db.scalar(_product_query().where(Product.id == product_id))
    if product is None:
        raise not_found("Товар")
    return product


def is_publicly_visible(product: Product) -> bool:
    return product.is_active and product.seller.verification_status == VerificationStatus.verified


def seller_products(db: Session, seller: Seller) -> list[schemas.ProductListItem]:
    products = db.scalars(
        _product_query().where(Product.seller_id == seller.id).order_by(Product.created_at.desc())
    ).all()
    stats = rating_stats(db, [p.id for p in products])
    return [to_list_item(p, stats[p.id]) for p in products]


def set_instructions(product: Product, instructions: list[schemas.InstructionIn]) -> None:
    kinds = [i.kind for i in instructions]
    if len(kinds) != len(set(kinds)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Каждый блок (технологии/уход) можно указать один раз"
        )
    product.instructions.clear()
    for ins in instructions:
        product.instructions.append(
            Instruction(
                kind=ins.kind,
                name=ins.name,
                steps=[
                    InstructionStep(position=pos, name=s.name, description=s.description)
                    for pos, s in enumerate(ins.steps)
                ],
            )
        )


# ---------- Cart ----------


def get_or_create_cart(db: Session, user: User) -> Cart:
    cart = db.scalar(
        select(Cart)
        .where(Cart.user_id == user.id)
        .options(
            selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.media),
            selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.seller),
        )
    )
    if cart is None:
        cart = Cart(user_id=user.id)
        db.add(cart)
        db.flush()
    return cart


def cart_out(cart: Cart) -> schemas.CartOut:
    items = [
        schemas.CartItemOut(
            id=i.id,
            product_id=i.product_id,
            name=i.product.name,
            image_url=_main_image(i.product),
            size=i.size,
            amount=i.amount,
            price=i.product.price,
            delivery_days=i.product.delivery_days,
        )
        for i in cart.items
    ]
    return schemas.CartOut(
        items=items,
        total=sum((i.price * i.amount for i in items), Decimal("0")),
        max_delivery_days=max((i.delivery_days for i in items), default=0),
    )


# ---------- Orders ----------


def create_order_from_cart(db: Session, user: User, data: schemas.OrderCreate) -> Order:
    cart = get_or_create_cart(db, user)
    if not cart.items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Корзина пуста")
    unavailable = [i.product.name for i in cart.items if not is_publicly_visible(i.product)]
    if unavailable:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Товары больше недоступны: {', '.join(unavailable)}"
        )
    order = Order(
        user_id=user.id,
        delivery_address=data.delivery_address.strip(),
        delivery_method=data.delivery_method,
        payment_method=data.payment_method,
        total=sum((i.product.price * i.amount for i in cart.items), Decimal("0")),
        estimated_delivery_days=max(i.product.delivery_days for i in cart.items),
        items=[
            OrderItem(
                product_id=i.product_id,
                seller_id=i.product.seller_id,
                product_name=i.product.name,
                size=i.size,
                amount=i.amount,
                price=i.product.price,
            )
            for i in cart.items
        ],
    )
    db.add(order)
    # Корзина очищается сразу: позиции уже зафиксированы в OrderItem
    cart.items.clear()
    db.flush()
    return order


def order_out(db: Session, order: Order) -> schemas.OrderOut:
    rated = db.scalars(
        select(Review.product_id).where(Review.order_id == order.id, Review.user_id == order.user_id)
    ).all()
    out = schemas.OrderOut.model_validate(order)
    out.rated_product_ids = list(rated)
    return out


def get_order(db: Session, order_id: int) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
    if order is None:
        raise not_found("Заказ")
    return order


def user_orders(db: Session, user: User) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.user_id == user.id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        ).all()
    )


def seller_orders(db: Session, seller: Seller) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.items.any(OrderItem.seller_id == seller.id))
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        ).all()
    )


# ---------- Analytics ----------


def seller_analytics(db: Session, seller: Seller) -> schemas.SellerAnalytics:
    products = db.scalars(select(Product).where(Product.seller_id == seller.id)).all()
    sales = {
        pid: (int(units), Decimal(revenue))
        for pid, units, revenue in db.execute(
            select(
                OrderItem.product_id,
                func.sum(OrderItem.amount),
                func.sum(OrderItem.amount * OrderItem.price),
            )
            .join(Order)
            .where(OrderItem.seller_id == seller.id, Order.status.in_(SOLD_STATUSES))
            .group_by(OrderItem.product_id)
        ).all()
    }
    orders_count = db.scalar(
        select(func.count(func.distinct(Order.id)))
        .join(OrderItem)
        .where(OrderItem.seller_id == seller.id, Order.status.in_(SOLD_STATUSES))
    )
    stats = rating_stats(db, [p.id for p in products])
    rows = [
        schemas.ProductStats(
            product_id=p.id,
            name=p.name,
            units_sold=sales.get(p.id, (0, Decimal(0)))[0],
            revenue=sales.get(p.id, (0, Decimal(0)))[1].quantize(Decimal("0.01")),
            rating=stats[p.id][0],
            reviews_count=stats[p.id][1],
        )
        for p in products
    ]
    rows.sort(key=lambda r: r.revenue, reverse=True)
    avg_rating = db.scalar(
        select(func.avg(Review.rating)).join(Product).where(Product.seller_id == seller.id)
    )
    return schemas.SellerAnalytics(
        orders_count=orders_count or 0,
        units_sold=sum(r.units_sold for r in rows),
        revenue=sum((r.revenue for r in rows), Decimal("0.00")),
        products_total=len(products),
        products_with_sales=sum(1 for r in rows if r.units_sold),
        average_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
        products=rows,
    )
