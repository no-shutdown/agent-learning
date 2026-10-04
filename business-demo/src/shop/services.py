"""Authoritative business rules shared by HTML views and HTTP API."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from django.db import transaction, OperationalError
from django.db.models import F
from django.utils import timezone
from .models import Address, Order, OrderItem, Product, Operation

ADDRESS_FIELDS = ("recipient", "phone", "province", "city", "district", "detail")


class BusinessError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def integer(value, name, low=1, high=1000000000):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise BusinessError("invalid_input", f"{name} 必须是整数")
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise BusinessError("invalid_input", f"{name} 必须是整数")
    n = int(value)
    if not low <= n <= high:
        raise BusinessError("invalid_input", f"{name} 必须介于 {low} 和 {high}")
    return n


def text(value, name, maximum, required=True):
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or (required and not value.strip())
    ):
        raise BusinessError(
            "invalid_input",
            f"{name} 不能为空且最多 {maximum} 字" if required else f"{name} 最多 {maximum} 字",
        )
    return value.strip()


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise BusinessError("invalid_fields", "字段缺失或包含不允许的字段")


def address_data(data):
    fields(data, ADDRESS_FIELDS, ADDRESS_FIELDS)
    limits = (40, 11, 30, 30, 30, 150)
    out = {k: text(data[k], k, limit) for k, limit in zip(ADDRESS_FIELDS, limits)}
    if not re.fullmatch(r"1[0-9]{10}", out["phone"]):
        raise BusinessError("invalid_phone", "演示规则：手机号应为以 1 开头的 11 位数字")
    return out


def address_json(a):
    return {"id": a.id, "version": a.version, **{k: getattr(a, k) for k in ADDRESS_FIELDS}}


def product_json(p):
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "price": str(p.price),
        "stock": p.stock,
        "active": p.active,
        "version": p.version,
    }


def order_json(o):
    return {
        "id": o.id,
        "number": f"ORD-{o.id:06d}",
        "status": o.status,
        "status_label": o.get_status_display(),
        "total": str(o.total),
        "address": o.address,
        "note": o.note,
        "tracking_no": o.tracking_no or None,
        "version": o.version,
        "created_at": o.created_at.isoformat(),
        "items": [
            {
                "product_id": i.product_id,
                "name": i.name,
                "unit_price": str(i.unit_price),
                "quantity": i.quantity,
            }
            for i in o.items.all()
        ],
    }


def own_order(actor, pk):
    try:
        return Order.objects.prefetch_related("items").get(pk=pk, owner=actor)
    except Order.DoesNotExist:
        raise BusinessError("not_found", "订单不存在或不属于当前用户", 404)


def own_address(actor, pk):
    try:
        return Address.objects.get(pk=integer(pk, "address_id"), owner=actor)
    except Address.DoesNotExist:
        raise BusinessError("not_found", "地址不存在或不属于当前用户", 404)


def require_staff(actor):
    if not actor.is_staff:
        raise BusinessError("forbidden", "需要管理员权限", 403)


def checked_update(order, version, **changes):
    version = integer(version, "version")
    count = Order.objects.filter(pk=order.pk, version=version, status=order.status).update(
        **changes, version=F("version") + 1, updated_at=timezone.now()
    )
    if not count:
        raise BusinessError("version_conflict", "订单已变化，请重新查询后操作", 409)
    order.refresh_from_db()
    return order_json(order)


def perform(actor, key, action, data, handler):
    """A committed key is a completed operation; failures roll back the key and effects."""
    key = text(key, "Idempotency-Key", 100)
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
        raise BusinessError(
            "invalid_input", "操作编号仅允许英文字母、数字、点、下划线、冒号和短横线"
        )
    fingerprint = hashlib.sha256(
        json.dumps({"action": action, "data": data}, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    try:
        with transaction.atomic():
            # SQLite BEGIN IMMEDIATE serializes writers before business reads.
            op, created = Operation.objects.get_or_create(
                actor=actor, key=key, defaults={"action": action, "fingerprint": fingerprint}
            )
            if not created:
                if op.fingerprint != fingerprint:
                    raise BusinessError("idempotency_conflict", "同一操作编号不能用于不同参数", 409)
                return op.result, True
            result = handler()
            op.result = result
            op.target = str(result.get("id", ""))
            op.save(update_fields=["result", "target"])
            return result, False
    except OperationalError as e:
        if "locked" in str(e).lower():
            raise BusinessError("busy", "数据库忙，请先查询操作记录，再使用原操作编号重试", 409)
        raise


def create_address(actor, data):
    return address_json(Address.objects.create(owner=actor, **address_data(data)))


def edit_address(actor, pk, data):
    fields(data, (*ADDRESS_FIELDS, "version"), (*ADDRESS_FIELDS, "version"))
    a = own_address(actor, pk)
    clean = address_data({k: data[k] for k in ADDRESS_FIELDS})
    if not Address.objects.filter(pk=a.pk, version=integer(data["version"], "version")).update(
        **clean, version=F("version") + 1
    ):
        raise BusinessError("version_conflict", "地址已变化，请刷新后重试", 409)
    a.refresh_from_db()
    return address_json(a)


def create_order(actor, data):
    fields(data, ("address_id", "items", "note"), ("address_id", "items"))
    a = own_address(actor, data["address_id"])
    note = text(data.get("note", ""), "note", 300, False)
    if not isinstance(data["items"], list) or not 1 <= len(data["items"]) <= 20:
        raise BusinessError("invalid_input", "订单应含 1～20 个商品项目")
    prepared, seen, total = [], set(), Decimal("0.00")
    for item in data["items"]:
        fields(item, ("product_id", "quantity"), ("product_id", "quantity"))
        pk = integer(item["product_id"], "product_id")
        qty = integer(item["quantity"], "quantity", high=99)
        if pk in seen:
            raise BusinessError("invalid_input", "同一商品请合并为一个项目")
        seen.add(pk)
        try:
            p = Product.objects.get(pk=pk, active=True)
        except Product.DoesNotExist:
            raise BusinessError("not_found", "商品不存在或已下架", 404)
        if not Product.objects.filter(pk=pk, active=True, stock__gte=qty).update(
            stock=F("stock") - qty, version=F("version") + 1
        ):
            raise BusinessError("out_of_stock", "商品库存不足", 409)
        total += p.price * qty
        prepared.append((p, qty))
    o = Order.objects.create(
        owner=actor,
        address={k: getattr(a, k) for k in ADDRESS_FIELDS},
        total=total,
        note=note,
        created_at=timezone.now(),
    )
    for p, qty in prepared:
        OrderItem.objects.create(order=o, product=p, name=p.name, unit_price=p.price, quantity=qty)
    return order_json(o)


def order_action(actor, pk, action, data):
    if action == "ship":
        require_staff(actor)
        try:
            o = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            raise BusinessError("not_found", "订单不存在", 404)
        fields(data, ("version", "tracking_no"), ("version", "tracking_no"))
        if o.status != Order.Status.PAID:
            raise BusinessError("invalid_state", "只有待发货订单可以发货", 409)
        tracking = text(data["tracking_no"], "tracking_no", 60)
        return checked_update(o, data["version"], status=Order.Status.SHIPPED, tracking_no=tracking)
    o = own_order(actor, pk)
    fields(
        data,
        ("version", "address_id") if action == "address" else ("version",),
        ("version", "address_id") if action == "address" else ("version",),
    )
    if action == "pay":
        if o.status != Order.Status.PENDING:
            raise BusinessError("invalid_state", "只有待支付订单可以模拟支付", 409)
        return checked_update(o, data["version"], status=Order.Status.PAID)
    if action == "cancel":
        if o.status not in (Order.Status.PENDING, Order.Status.PAID):
            raise BusinessError("invalid_state", "已发货或已取消订单不能取消", 409)
        result = checked_update(o, data["version"], status=Order.Status.CANCELLED)
        for item in o.items.all():
            Product.objects.filter(pk=item.product_id).update(
                stock=F("stock") + item.quantity, version=F("version") + 1
            )
        return result
    if action == "address":
        if o.status not in (Order.Status.PENDING, Order.Status.PAID):
            raise BusinessError("invalid_state", "只有未发货且未取消的订单可以修改地址", 409)
        a = own_address(actor, data["address_id"])
        return checked_update(
            o, data["version"], address={k: getattr(a, k) for k in ADDRESS_FIELDS}
        )
    raise BusinessError("not_found", "未知操作", 404)


def save_product(actor, pk, data):
    require_staff(actor)
    allowed = ("name", "category", "description", "price", "stock", "active")
    fields(data, (*allowed, "version") if pk else allowed, (*allowed, "version") if pk else allowed)
    clean = {
        k: text(data[k], k, n, k != "description")
        for k, n in [("name", 100), ("category", 30), ("description", 1000)]
    }
    try:
        price = Decimal(str(data["price"]))
        if (
            not price.is_finite()
            or not Decimal("0.01") <= price <= Decimal("99999999.99")
            or price.as_tuple().exponent < -2
        ):
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise BusinessError("invalid_input", "价格必须为正数，且最多两位小数")
    if not isinstance(data["active"], bool):
        raise BusinessError("invalid_input", "active 必须是布尔值")
    clean.update(
        price=price,
        stock=integer(data["stock"], "stock", low=0, high=1000000),
        active=data["active"],
    )
    if pk:
        if not Product.objects.filter(pk=pk, version=integer(data["version"], "version")).update(
            **clean, version=F("version") + 1
        ):
            raise BusinessError("version_conflict", "商品已变化或不存在，请刷新后重试", 409)
        p = Product.objects.get(pk=pk)
    else:
        p = Product.objects.create(**clean)
    return product_json(p)
