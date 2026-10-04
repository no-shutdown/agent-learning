# 验证记录 · 2026-09-28

环境：Apple M5 / 24GB；Python 3.13.15；Django 5.2.17；SQLite。

已完成：

- `make check`：Ruff lint、格式与 Django 系统检查通过。
- `make test`：30 项测试通过；独立测试数据库，不污染日常数据。
- `makemigrations --check --dry-run`：模型与迁移一致。
- 测试覆盖正常创建、库存回滚、同编号重放、同编号不同参数、并发竞争最后一件商品、并发同编号后重试、身份隔离、CSRF、状态变化、旧版本、地址快照、管理员权限、错误输入与固定数据重置。
- 浏览器实际验证：user01 登录、首页与商品详情、创建订单、模拟支付、修改收货地址；admin 登录、查看待发货订单并模拟发货。页面状态与接口结果一致。
- 网站 AI 面板实际发送消息，收到 Agent 空服务占位回复，明确 implemented=false。
- 使用真实 HTTP 会话创建订单，重启网站进程，再查原操作记录、用原编号重试，确认原结果恢复且没有重复创建。

并发测试发现 SQLite 默认延迟事务可能在升级写锁时使双方都失败，现使用 `transaction_mode=IMMEDIATE`，并保留数据库繁忙时的受控错误。参考 [Django 官方 SQLite 事务说明](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes)（2026-09-28 访问核验）。

测试完成后恢复默认 500 笔订单基线。测试期间的订单与操作记录不作为学习用例保留。

范围限制：这些是本机业务基线验证，不是生产负载或安全审计；模型能力另见父目录 model-check。未来 Agent 的会话委派、对话确认和执行恢复尚未实现。
