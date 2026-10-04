# HTTP 接口契约 v1

根地址 `http://127.0.0.1:8000/api/v1`，请求及响应使用 JSON。金额为十进制字符串，时间为带时区 ISO 8601。数字对象编号与展示编号不同：`id:1` 对应 `ORD-000001`。

## 登录、身份与 CSRF

1. GET `/auth/csrf`，保存响应 cookie 与 `csrf_token`。
2. POST `/auth/login`，JSON 为 `{"username":"user01","password":"demo12345"}`。携带步骤 1 的 cookie 和 `X-CSRFToken`。
3. 登录成功后会话 cookie 与 CSRF token 会轮换。保存 cookie 和此次响应中的新 `csrf_token`。
4. 后续请求发送该会话 cookie；POST/PUT 另外发送 `X-CSRFToken`。登录和退出也需要 CSRF。

身份来自登录会话，业务接口不接受 `user_id`、`owner_id` 或任意身份参数。Agent 将来需要为用户维持独立、受信的会话，不能把模型生成的用户编号当成授权。不要把管理员会话交给普通用户的助手。初始 Agent 不实现会话委派。

GET `/me` 返回 username 和 is_staff；POST `/auth/logout` 退出；GET `/health` 无需登录。

## 查询接口

| 方法与路径 | 说明 |
|---|---|
| GET `/products` | 上架商品；可用 q 按名称搜索 |
| GET `/products/{id}` | 上架商品详情 |
| GET `/addresses` | 当前用户地址簿 |
| GET `/orders` | 本人订单；status 筛选，q 匹配数字编号、ORD 编号、商品名或备注 |
| GET `/orders/{id}` | 本人订单详情、地址快照、明细、状态、版本 |
| GET `/operations` | 本人已成功提交的操作摘要 |
| GET `/operations/{key}` | 本人某次操作的原始结果及 committed=true |
| GET `/manage/products` | 管理员查看全部商品，包括下架商品 |
| GET `/manage/orders` | 管理员查看全部订单，支持同样的订单筛选 |

列表参数 `page` 默认 1，`page_size` 默认 20、最大 100。返回 `{"count":500,"page":1,"page_size":20,"results":[...]}`。超出末页得到空 results。

## 写入接口

除登录、退出与聊天外，每次 POST/PUT 都必须发送 `Idempotency-Key`，非空且最多 100 字符，仅允许英文字母、数字、点、下划线、冒号和短横线，建议 UUID。每个逻辑操作使用一个新编号；重试保持相同编号、路径和参数。业务写入返回 `{"data":{...},"replayed":false}`，重放返回 `replayed:true`。

| 方法与路径 | JSON 字段 |
|---|---|
| POST `/addresses` | recipient, phone, province, city, district, detail，均为字符串且必填 |
| PUT `/addresses/{id}` | 上述全部字段 + version |
| POST `/orders` | address_id, items；可选 note（最多 300 字） |
| POST `/orders/{id}/pay` | version；模拟支付 |
| POST `/orders/{id}/cancel` | version |
| POST `/orders/{id}/address` | version, address_id |
| POST `/orders/{id}/ship` | version, tracking_no；仅管理员 |
| POST `/manage/products` | name, category, description, price, stock, active；仅管理员 |
| PUT `/manage/products/{id}` | 上述全部字段 + version；仅管理员 |

创建订单示例（仅请求契约，不是 Agent 工具实现）：

```json
{"address_id":3,"items":[{"product_id":1,"quantity":2}],"note":"请周末配送"}
```

修改订单地址示例：

```json
{"version":1,"address_id":4}
```

`active` 必须是 JSON 布尔值。`price` 推荐十进制字符串，正数且最多两位小数。未列出的字段会被拒绝。订单、地址、商品更新后版本加 1；重放不会再增加。

原操作记录是提交当时的快照。读取原记录确认执行结果后，若还需当前状态，应再次查询业务对象。用户甲和乙的相同 key 彼此隔离。

## 错误与核验

错误响应形如 `{"error":{"code":"version_conflict","message":"订单已变化，请重新查询后操作"}}`。

- 400：invalid_json / invalid_input / invalid_fields / invalid_phone。
- 401：unauthenticated；需要重新登录。
- 403：forbidden / csrf_failed。
- 404：not_found；不存在与非本人对象使用相同响应，避免暴露归属。
- 409：invalid_state / out_of_stock / version_conflict / idempotency_conflict / busy。
- 503：agent_unavailable，仅聊天空服务连接失败时使用。

写入成功需通过响应、GET 对象和操作记录核实。网络断开时，不换新编号盲目重试；先 GET `/operations/{key}`。没有记录可能表示未开始、尚在处理或失败，使用原 key 重试不会重复提交同一操作。重新查询后改变参数属于新操作，必须重新取得用户确认并使用新 key。

## AI 面板连接

POST `/assistant/chat` 接受 `{"message":"你好"}`，需要登录与 CSRF。网站只把 message 发给 `http://127.0.0.1:8001/chat`，不传密码、cookie 或业务数据。返回占位回复和 `implemented:false`。对话不持久化，页面刷新后清空。
