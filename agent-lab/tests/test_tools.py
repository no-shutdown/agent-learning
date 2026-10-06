"""工具目录、契约与 HTTP 适配测试；不覆盖尚未实现的 runtime。"""

import unittest
from unittest.mock import Mock

from agent_lab.clients import ApiResponse, BusinessApiTransport, BusinessApiConnectionError
from agent_lab.clients.orders_api import OrdersApi
from agent_lab.tools import ALL_TOOLS, LIST_ORDERS, ToolRegistry, InvalidArguments


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.transport = BusinessApiTransport()
        self.response = ApiResponse(status_code=200, headers={}, data={"example": True})
        self.transport.send = Mock(side_effect=self.send)
        self.requests = []
        self.registry = ToolRegistry()

    def send(self, request):
        self.requests.append(request)
        return self.response

    def test_catalogue_does_not_need_session(self):
        definitions = self.registry.definitions()
        self.assertEqual(len(definitions), 18)
        self.assertEqual({d["tool_id"] for d in definitions}, {t.tool_id for t in ALL_TOOLS})
        self.assertIs(self.registry.get("list_orders"), LIST_ORDERS)
        self.assertTrue(self.registry.get("ship_order").admin)
        self.assertTrue(self.registry.get("ship_order").writes)
        self.transport.send.assert_not_called()
        with self.assertRaises(KeyError):
            self.registry.get("missing")
        with self.assertRaises(ValueError):
            ToolRegistry([LIST_ORDERS, LIST_ORDERS])
        self.assertEqual(ToolRegistry([]).definitions(), [])
        self.assertEqual(len(ToolRegistry([LIST_ORDERS]).definitions()), 1)

    def test_definitions_do_not_mutate_contracts(self):
        definition = self.registry.definitions()[0]
        definition["parameters"]["properties"].clear()
        self.assertIn("page", LIST_ORDERS.definition()["parameters"]["properties"])

    def test_invalid_input_never_calls_business(self):
        cases = [
            ("get_order", {"order_id": True}),
            ("get_order", {"order_id": "12"}),
            ("get_order", {}),
            ("list_orders", []),
            ("list_orders", {"q": 123}),
            ("create_order", {"address_id": 1, "items": {}}),
            ("create_order", {"address_id": 1, "items": [None]}),
            ("list_orders", {"status": "unknown"}),
            ("list_orders", {"page_size": 101}),
            ("pay_order", {"order_id": 12, "version": 1, "confirmed": True}),
            ("create_order", {"address_id": 1, "items": []}),
            (
                "create_order",
                {
                    "address_id": 1,
                    "items": [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}],
                },
            ),
        ]
        for name, args in cases:
            with self.subTest(tool=name, arguments=args):
                with self.assertRaises(InvalidArguments):
                    self.registry.get(name).invoke(self.transport, args, "test-operation")
        self.transport.send.assert_not_called()

    def test_client_query_preserves_values_without_aliasing(self):
        api = OrdersApi(self.transport)
        query = {"page": 2, "q": "订单", "status": "paid"}
        api.list_orders(query)
        request = self.requests[-1]
        self.assertEqual(request.query, query)
        query["page"] = 3
        self.assertEqual(request.query["page"], 2)
        api.list_orders()
        self.assertIsNone(self.requests[-1].query)

    def test_invalid_client_query_never_calls_transport(self):
        api = OrdersApi(self.transport)
        for query in ({"page": True}, {"page": 1.5}, {"q": None}, {1: "value"}):
            with self.subTest(query=query):
                with self.assertRaises(TypeError):
                    api.list_orders(query)
        self.transport.send.assert_not_called()

    def test_write_passes_original_key_and_body(self):
        tool = self.registry.get("change_order_address")
        args = {"order_id": 12, "version": 1, "address_id": 3}
        for key in (None, "", "invalid key"):
            with self.assertRaises(ValueError):
                tool.invoke(self.transport, args, key)
        self.transport.send.assert_not_called()
        self.assertIs(tool.invoke(self.transport, args, "original-key"), self.response)
        request = self.requests[-1]
        self.assertEqual(request.body, {"version": 1, "address_id": 3})
        self.assertEqual(request.idempotency_key, "original-key")
        self.assertTrue(request.requires_csrf)
        self.assertEqual(args, {"order_id": 12, "version": 1, "address_id": 3})

    def test_read_preserves_response_and_errors_without_retry(self):
        self.assertIs(LIST_ORDERS.invoke(self.transport, {"page_size": 5}, None), self.response)
        self.assertEqual(self.requests[-1].query, {"page_size": 5})
        self.transport.send = Mock(side_effect=BusinessApiConnectionError("test failure"))
        with self.assertRaises(BusinessApiConnectionError):
            LIST_ORDERS.invoke(self.transport, {}, None)
        self.transport.send.assert_called_once()

    def test_all_tools_use_expected_http_endpoints(self):
        address = dict(
            recipient="测试",
            phone="13800000000",
            province="省",
            city="市",
            district="区",
            detail="测试路",
        )
        product = dict(
            name="测试", category="测试", description="", price="1.00", stock=0, active=True
        )
        cases = [
            ("list_products", {}, "GET", "products"),
            ("get_product", {"product_id": 12}, "GET", "products/12"),
            ("list_admin_products", {}, "GET", "manage/products"),
            ("create_product", product, "POST", "manage/products"),
            (
                "update_product",
                {**product, "product_id": 12, "version": 1},
                "PUT",
                "manage/products/12",
            ),
            ("list_addresses", {}, "GET", "addresses"),
            ("create_address", address, "POST", "addresses"),
            ("update_address", {**address, "address_id": 12, "version": 1}, "PUT", "addresses/12"),
            ("list_orders", {}, "GET", "orders"),
            ("list_admin_orders", {}, "GET", "manage/orders"),
            ("get_order", {"order_id": 12}, "GET", "orders/12"),
            (
                "create_order",
                {"address_id": 12, "items": [{"product_id": 12, "quantity": 1}]},
                "POST",
                "orders",
            ),
            ("pay_order", {"order_id": 12, "version": 1}, "POST", "orders/12/pay"),
            ("cancel_order", {"order_id": 12, "version": 1}, "POST", "orders/12/cancel"),
            (
                "change_order_address",
                {"order_id": 12, "version": 1, "address_id": 12},
                "POST",
                "orders/12/address",
            ),
            (
                "ship_order",
                {"order_id": 12, "version": 1, "tracking_no": "TEST"},
                "POST",
                "orders/12/ship",
            ),
            ("list_operations", {}, "GET", "operations"),
            ("get_operation", {"idempotency_key": "op-1"}, "GET", "operations/op-1"),
        ]
        for name, args, method, path in cases:
            with self.subTest(tool=name):
                self.registry.get(name).invoke(self.transport, args, "test-operation")
                self.assertEqual((self.requests[-1].method, self.requests[-1].path), (method, path))


if __name__ == "__main__":
    unittest.main()
