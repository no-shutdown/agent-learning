import json
from io import StringIO
from unittest.mock import patch
from django.test import TestCase, Client
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth.models import User
from shop.models import Address, Order, Product, Operation


class BusinessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.user = User.objects.get(username="user01")
        self.client.force_login(self.user)
        self.serial = 0

    def post(self, route, data, key=None, method="post"):
        self.serial += 1
        return getattr(self.client, method)(
            "/api/v1/" + route,
            data=json.dumps(data),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key or f"test-{self.serial}",
        )

    def create(self, key="new", items=None):
        return self.post(
            "orders", {"address_id": 3, "items": items or [{"product_id": 1, "quantity": 2}]}, key
        )

    def test_seed_scale_and_identifiers(self):
        self.assertEqual(
            (
                User.objects.count(),
                Product.objects.count(),
                Order.objects.count(),
                Address.objects.count(),
            ),
            (50, 30, 500, 100),
        )
        self.assertEqual(Order.objects.get(pk=1).owner, self.user)

    def test_all_user_pages_render(self):
        for url in [
            "/",
            "/products/",
            "/products/1/",
            "/orders/",
            "/orders/1/",
            "/addresses/",
            "/operations/",
            "/assistant/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_pages_render(self):
        self.client.force_login(User.objects.get(username="admin"))
        for url in ["/manage/products/", "/manage/orders/"]:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_unauthenticated_and_csrf(self):
        self.assertEqual(Client().get("/api/v1/orders").status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(
                "/api/v1/orders/1/pay", data='{"version":1}', content_type="application/json"
            ).status_code,
            403,
        )

    def test_api_login_with_csrf_rotation(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        r = client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": "user01", "password": "demo12345"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/api/v1/me").json()["username"], "user01")
        self.assertNotEqual(token, r.json()["csrf_token"])

    def test_create_stock_snapshot_and_replay(self):
        stock = Product.objects.get(pk=1).stock
        first = self.create().json()
        again = self.create().json()
        self.assertEqual(first["data"], again["data"])
        self.assertTrue(again["replayed"])
        self.assertEqual(Order.objects.count(), 501)
        self.assertEqual(Product.objects.get(pk=1).stock, stock - 2)
        self.assertEqual(Operation.objects.count(), 1)

    def test_same_key_different_payload_rejected(self):
        self.create()
        r = self.create(items=[{"product_id": 1, "quantity": 1}])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "idempotency_conflict")

    def test_failed_multi_item_order_rolls_back(self):
        before = Product.objects.get(pk=1).stock
        r = self.create(items=[{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 1}])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Product.objects.get(pk=1).stock, before)
        self.assertEqual(Operation.objects.count(), 0)

    def test_duplicate_product_rejected(self):
        self.assertEqual(
            self.create(
                items=[{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 1}]
            ).status_code,
            400,
        )

    def test_quantity_bounds(self):
        for n in [0, 100, -1, 1.1, True, "1.5"]:
            with self.subTest(n=n):
                self.assertEqual(
                    self.create(key=str(n), items=[{"product_id": 1, "quantity": n}]).status_code,
                    400,
                )

    def test_inactive_product(self):
        self.assertEqual(self.create(items=[{"product_id": 30, "quantity": 1}]).status_code, 404)

    def test_cross_user_read_and_write(self):
        self.assertEqual(self.client.get("/api/v1/orders/14").status_code, 404)
        self.assertEqual(self.post("orders/14/pay", {"version": 1}).status_code, 404)
        self.assertEqual(
            self.post("orders/1/address", {"version": 1, "address_id": 5}).status_code, 404
        )

    def test_identity_cannot_be_supplied(self):
        self.assertEqual(self.post("orders/1/pay", {"version": 1, "owner_id": 3}).status_code, 400)

    def test_pay_and_cancel_restore_inventory_once(self):
        before = Product.objects.get(pk=1).stock
        o = self.create().json()["data"]
        self.assertEqual(self.post(f"orders/{o['id']}/pay", {"version": 1}).status_code, 200)
        r = self.post(f"orders/{o['id']}/cancel", {"version": 2}, key="cancel")
        self.assertEqual(r.status_code, 200)
        self.post(f"orders/{o['id']}/cancel", {"version": 2}, key="cancel")
        self.assertEqual(Product.objects.get(pk=1).stock, before)

    def test_stale_version_no_mutation(self):
        self.post("orders/1/pay", {"version": 1})
        r = self.post("orders/1/address", {"version": 1, "address_id": 4})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Order.objects.get(pk=1).version, 2)

    def test_status_forbids_changes(self):
        for pk in [3, 4]:
            self.assertEqual(
                self.post(f"orders/{pk}/address", {"version": 1, "address_id": 4}).status_code, 409
            )
            self.assertEqual(self.post(f"orders/{pk}/cancel", {"version": 1}).status_code, 409)

    def test_staff_ship_then_customer_cannot_change(self):
        self.client.force_login(User.objects.get(username="admin"))
        self.assertEqual(
            self.post("orders/2/ship", {"version": 1, "tracking_no": "DEMO-TEST"}).status_code, 200
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.post("orders/2/address", {"version": 1, "address_id": 4}).status_code, 409
        )
        self.assertEqual(Order.objects.get(pk=2).tracking_no, "DEMO-TEST")

    def test_nonstaff_ship_and_product_edit_forbidden(self):
        self.assertEqual(
            self.post("orders/2/ship", {"version": 1, "tracking_no": "X"}).status_code, 403
        )
        self.assertEqual(self.post("manage/products", {}).status_code, 403)

    def test_address_validation_and_snapshot(self):
        original = Order.objects.get(pk=1).address
        a = Address.objects.get(pk=3)
        data = {
            k: getattr(a, k)
            for k in ["recipient", "phone", "province", "city", "district", "detail"]
        }
        self.assertEqual(self.post("addresses", {**data, "phone": "123"}).status_code, 400)
        self.assertEqual(
            self.post(
                "addresses/3", {**data, "version": 1, "detail": "新模拟路 99 号"}, method="put"
            ).status_code,
            200,
        )
        self.assertEqual(Order.objects.get(pk=1).address, original)
        r = self.post("orders/1/address", {"version": 1, "address_id": 3})
        self.assertEqual(r.json()["data"]["address"]["detail"], "新模拟路 99 号")

    def test_operation_read_scoped_and_recoverable(self):
        result = self.create("recover").json()["data"]
        self.assertEqual(self.client.get("/api/v1/operations/recover").json()["result"], result)
        self.client.force_login(User.objects.get(username="user02"))
        self.assertEqual(self.client.get("/api/v1/operations/recover").status_code, 404)

    def test_listing_pagination_and_search(self):
        self.assertEqual(len(self.client.get("/api/v1/products?page_size=5").json()["results"]), 5)
        self.assertEqual(self.client.get("/api/v1/orders?q=ORD-000001").json()["count"], 1)
        self.assertEqual(self.client.get("/api/v1/orders?status=bad").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/orders?page_size=1000").status_code, 400)

    def test_malformed_requests(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/orders", data="[1]", content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/orders", data="{", content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/orders/1/pay", data='{"version":1}', content_type="application/json"
            ).status_code,
            400,
        )

    def test_product_update_version_and_price(self):
        self.client.force_login(User.objects.get(username="admin"))
        data = {
            "name": "测试商品",
            "category": "测试",
            "description": "测试",
            "price": "10.25",
            "stock": 10,
            "active": True,
        }
        r = self.post("manage/products", data)
        self.assertEqual(r.status_code, 200)
        pk = r.json()["data"]["id"]
        self.assertEqual(
            self.post(
                f"manage/products/{pk}", {**data, "version": 1, "price": "NaN"}, method="put"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post(
                f"manage/products/{pk}", {**data, "version": 1, "price": "12.00"}, method="put"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(f"manage/products/{pk}", {**data, "version": 1}, method="put").status_code,
            409,
        )

    def test_note_is_data(self):
        self.assertIn("忽略", self.client.get("/api/v1/orders/9").json()["note"])
        self.assertEqual(Order.objects.get(pk=14).version, 1)

    def test_agent_unavailable_is_explicit(self):
        from urllib.error import URLError

        with patch("shop.agent_proxy.open_agent", side_effect=URLError("offline")):
            r = self.post("assistant/chat", {"message": "你好"})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "agent_unavailable")

    def test_reset_reproducible(self):
        before = list(
            Order.objects.values("id", "owner_id", "status", "total", "address", "created_at")
        )
        with self.assertRaises(CommandError):
            call_command("seed_demo", reset=True, stdout=StringIO())
        call_command("seed_demo", reset=True, yes=True, stdout=StringIO())
        self.assertEqual(
            before,
            list(
                Order.objects.values("id", "owner_id", "status", "total", "address", "created_at")
            ),
        )

    def test_reset_restores_next_identifiers(self):
        first = self.create().json()["data"]["id"]
        call_command("seed_demo", reset=True, yes=True, stdout=StringIO())
        self.client.force_login(User.objects.get(username="user01"))
        second = self.create().json()["data"]["id"]
        self.assertEqual(first, second)
        self.assertEqual(second, 501)

    def test_operation_key_is_url_safe(self):
        self.assertEqual(self.post("orders/1/pay", {"version": 1}, key="bad/key").status_code, 400)
        self.assertEqual(Order.objects.get(pk=1).status, "pending_payment")
