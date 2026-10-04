from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from django.core.management import call_command
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from shop.models import Product, Order, Operation
from shop import services as s


class ConcurrentWrites(TransactionTestCase):
    def setUp(self):
        call_command("seed_demo", stdout=StringIO())

    def run_pair(self, same_key=False):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            user = User.objects.get(username="user01")
            data = {"address_id": 3, "items": [{"product_id": 3, "quantity": 1}]}
            barrier.wait()
            try:
                return s.perform(
                    user,
                    "same" if same_key else f"key-{index}",
                    "orders",
                    data,
                    lambda: s.create_order(user, data),
                )
            except s.BusinessError as e:
                return e.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    def test_last_item_cannot_be_oversold(self):
        results = self.run_pair()
        self.assertEqual(Order.objects.count(), 501, results)
        self.assertEqual(Product.objects.get(pk=3).stock, 0)
        self.assertEqual(Operation.objects.count(), 1)
        self.assertEqual(sum(isinstance(r, tuple) for r in results), 1)
        self.assertTrue(any(r in ("busy", "out_of_stock") for r in results))

    def test_concurrent_same_key_then_retry(self):
        results = self.run_pair(same_key=True)
        user = User.objects.get(username="user01")
        data = {"address_id": 3, "items": [{"product_id": 3, "quantity": 1}]}
        result, replayed = s.perform(
            user, "same", "orders", data, lambda: s.create_order(user, data)
        )
        self.assertTrue(replayed)
        self.assertEqual(Order.objects.count(), 501, results)
        self.assertEqual(Product.objects.get(pk=3).stock, 0)
        self.assertEqual(Operation.objects.count(), 1)
