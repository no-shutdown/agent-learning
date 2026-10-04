"""Supplementary manual-review probes; no business calls or agent loop."""

import json
import time
from datetime import datetime
from pathlib import Path
from check import request

cases = [
    (
        "natural-query",
        "你是中文订单助手。仅依据用户附带的合成接口数据回答，不补造物流。最多120字，说明已知与未知。",
        '请告诉我订单3现在怎么样：{"id":3,"status":"shipped","status_label":"已发货","tracking_no":null,"items":[{"name":"杯子","quantity":1}]}',
    ),
    (
        "natural-clarify",
        "你是中文订单助手。只能依据给定候选理解请求；没有执行工具。订单和地址未明确时先追问，不能宣称已修改。回复不超过120字。",
        "用户请求：把那个杯子的地址改到上海。候选：订单1，杯子，待支付；订单2，杯子，待发货。",
    ),
]
if __name__ == "__main__":
    out = (
        Path(__file__).resolve().parent
        / "results"
        / ("natural-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    )
    out.mkdir(parents=True)
    for name, system, user in cases:
        payload = {
            "model": "qwen3.5:9b",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "think": False,
            "stream": False,
            "options": {"num_ctx": 8192, "num_predict": 256, "temperature": 0.2},
            "keep_alive": "10m",
        }
        start = time.monotonic()
        with request("/api/chat", payload) as response:
            data = json.load(response)
        result = {
            "id": name,
            "system": system,
            "input": user,
            "output": data["message"]["content"],
            "seconds": round(time.monotonic() - start, 3),
            "tokens": data.get("eval_count"),
        }
        with (out / "natural-language.jsonl").open("a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)
