from django.conf import settings
from django.db import models
from django.db.models import Q


class Product(models.Model):
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=30)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="product_positive_price")
        ]


class Address(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recipient = models.CharField(max_length=40)
    phone = models.CharField(max_length=11)
    province = models.CharField(max_length=30)
    city = models.CharField(max_length=30)
    district = models.CharField(max_length=30)
    detail = models.CharField(max_length=150)
    version = models.PositiveIntegerField(default=1)


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending_payment", "待支付"
        PAID = "paid", "待发货"
        SHIPPED = "shipped", "已发货"
        CANCELLED = "cancelled", "已取消"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    address = models.JSONField()
    total = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=300, blank=True)
    tracking_no = models.CharField(max_length=60, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class Operation(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    action = models.CharField(max_length=60)
    fingerprint = models.CharField(max_length=64)
    target = models.CharField(max_length=60, blank=True)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "key"], name="unique_actor_operation")
        ]
        ordering = ["-id"]
