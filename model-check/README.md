# 本地模型选型验证

**本机实测已完成，结论与限制见 [REPORT.md](REPORT.md)。**

本目录用于验证硬件与模型是否适合作为学习基线；不属于 Agent 的业务实现，不导入业务代码，不执行工具、不修改网站数据。

候选：Ollama `qwen3.5:9b`，Q4_K_M，约 6.6GB。设备：Apple M5、24GB 统一内存、10 核 GPU。上下文配置 8192、单并发，关闭 thinking，短输出上限 256 tokens。这是受控的组件测试，不是完整 Agent 成功率。

启动模型服务后复跑：

```sh
cd /Users/colin/code/my/agent-learning/model-check
/opt/homebrew/bin/python3.13 check.py --model qwen3.5:9b --repeats 3
```

共 20 条固定合成用例：6 条意图分类、4 条提取、3 条缺失/歧义/未知处理、4 条依据与规则、3 条工具选择。每条重复三次，共 60 次。结构化任务启用 JSON schema，因此格式合规包含运行时约束的贡献，不能归功于提示词本身。

工具测试只检查模型提出的名字与参数，不执行工具。缺编号用例的自动判定只检查不调用工具且有文本，需人工核实其是否真的追问、没有宣称成功。

每次结果放在 `results/时间戳/`，包含模型摘要、Ollama 版本、脚本哈希、参数、实际输出、通过情况、延迟、生成速度、加载耗时与运行内存。保留失败结果，修改测试或提示需作为新版本记录。此处用例全部可见，不是保留验收集。

未验证：长上下文、图片、多并发、完整多轮 Agent、生产可靠性。首次加载、长输入、长输出和多次模型调用会增加耗时。不要把单次短回复延迟当成完整业务操作耗时。

官方资料（2026-09-28 访问核验）：

- [模型发布页](https://ollama.com/library/qwen3.5:9b)
- [Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Ollama 工具调用](https://docs.ollama.com/capabilities/tool-calling)
- [Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama 上下文设置](https://docs.ollama.com/context-length)

没有核验到上述资料的对应官方中文版本，保留官方原文。
