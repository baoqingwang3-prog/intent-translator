# Codex 交接提示词：intent-translator 语义层蒸馏迭代

> 用法：把本文件全文作为一条提示词发给 Codex（在 `D:\测试\intent-translator-repo` 目录下启动）。
> 本文件自包含：背景、现状、约束、验收全部在内，无需本次对话的任何上下文。

---

## 任务契约

```yaml
TASK_ID: ilang-distill-iter2
MODE: CHANGE
SCOPE: D:\测试\intent-translator-repo\scripts\ilang_*.py, ilang_distill_intents.json, tests/
ALLOWED_ACTIONS: 读代码、跑测试、改 scripts/ 下 ilang_ 前缀文件、新增测试、调阈值、补原型句
FORBIDDEN_ACTIONS: 修改 src/intent_translator_mcp/ 核心代码、修改 mcp.json、安装全局包、网络外发、删除数据
STATE: OPEN
ACCEPTANCE: 下述验收清单全部有证据；新语句库在保留题 + 新题上给出对比数字
```

## 背景

`intent-translator`（本地意图编译器，v1.0.0a5）的 mode 判定靠 `core.py` 里的关键词表匹配，benchmark 固定题回归 96.5%，但 benchmark 外的真实中文表达路由错误率高（实测 5 句错 3 句），且从不推荐 primary_skill。

2026-09-18 已落地一轮蒸馏改造，思路来自四个 GitHub 项目：
- aurelio-labs/semantic-router：Route+utterances 语义锚点
- voml77/embedding-intent-router：质心+双阈值+弃权
- vllm-project/semantic-router：信号分层（便宜信号先行）
- microsoft/TypeChat：typed schema 约束输出

## 现状（已有资产，勿重写）

全部在 `D:\测试\intent-translator-repo\scripts\`：

| 文件 | 作用 |
|---|---|
| `ilang_semantic_adapter.py` | I-Lang 语法（`[VERB:@T\|k=v]=>...`）→ SemanticProposal |
| `ilang_distill_router.py` | embedding 意图路由器：bge-small-zh-v1.5 质心+双阈值（accept 0.46 / weak 0.40+margin 0.04），输出严格匹配 SemanticProposal schema |
| `ilang_distill_intents.json` | 10 mode × 12-18 条中英原型句（可积累资产，路由错就补句） |
| `ilang_semantic_main.py` | 混合入口：I-Lang 语句走语法，自然语言走 embedding |
| `ilang_nl2ilang.py` | 反向编译：自然语言 → I-Lang 语句（模式模板+槽位抽取） |

运行环境事实（路径用 `%USERPROFILE%` 指代本机用户目录，如 `C:\Users\<你>`）：
- Python：`%USERPROFILE%\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe`
- fastembed+onnxruntime 装在 `%USERPROFILE%\.workbuddy-ai\binaries\node\workspace\pydeps`（代码经 `ILANG_DISTILL_DEPS` 环境变量或 `~` 展开自动定位；安装新包必须 `--index-url https://pypi.org/simple` 且用 `--target` 指到同目录）
- embedding 模型 BAAI/bge-small-zh-v1.5 已缓存本地；**勿换 MiniLM（会 memory allocation crash）**
- intent-translator 官方 venv：`%USERPROFILE%\.intent-translator\mcp\runtimes\1.0.0a5\venv\Scripts\python.exe`（跑它的编译器/测试用它）

单测基线（2026-09-19）：416 测试全过；164 句评测集（`ilang_eval_set.jsonl`）上，纯 keyword 79.9%、纯 embed 60.4%、**级联规则 85.4%**。

级联判定规则（已验证，写死在调用方即可，无需改上游）：
1. keyword（`IntentCompiler`，`semantic_mode="off"`）与 embed 路由器结论一致 → 直判（该档准确率 97.5%）
2. 分歧时：若 keyword 判 `answer` 且 confidence ≤ 0.60 且 embed 结论非 answer → 信 embed（这是 keyword 的"没辙兜底"档，embed 翻案 33 次几乎全对）
3. 其余分歧 → 信 keyword（分歧中 keyword 独对 53 vs embed 独对 21，keyword 是更强的先验）

剩余 24 错中 13 例是"可以"/"continue"类待办恢复句（正确答案依赖 pending_action 上下文，纯语句路由器原理上不可判，属合规错误），9 例是 meta 问句两引擎齐错，真正可救的只有 ~2 例。

## 本次要做的（按优先级）

1. ~~补齐评测集~~（已完成：`scripts/ilang_eval_set.jsonl`，164 句）
2. ~~对比评测~~（已完成：`scripts/ilang_compare_eval.py`；注意跑评测时内存需 >3GB 空闲，onnxruntime 已固定单线程）
3. ~~级联规则工程化~~（已完成：`ilang_semantic_main.py` 的 `cascade_mode()`，端到端 141/164=86.0%，schema 4/4 PASS，判定路径 agree=78 / kw-prior=52 / embed-rescue=34）
4. ~~底座试探~~（已完成一轮：jina-v2-base-zh 42.1% 更差已弃；mpnet-base 在 2.3GB 空闲内存下单线程 20 分钟跑不完已放弃；e5-large 2.24GB 同样内存不足。结论：这台机器的空闲内存只够 bge-small-zh）
5. **剩余可做**（低优先）：a) 内存 >6GB 时复测 e5-large；b) SetFit 式微调 bge-small 头部；c) skill 推荐骨架（mode→primary_skill 候选，参考 `skills/intent-translator/references/routes.md`）

## 硬约束

- 不改 `src/intent_translator_mcp/`（那是上游，改了会和 venv 里的 1.0.0a5 脱钩）
- 输出 JSON 必须始终通过 `SemanticProposal.model_validate()`（用 intent-translator venv 验证）
- 路由器不确定时弃权（mode=None + clarification_recommended=true），不许硬猜凑命中数
- **仓库有泄露审计**（`scripts/release_audit.py` + `test_personalization_firewall`）：代码/文档里不得出现 `C:\Users\<具体用户名>`、`D:\测试` 字样的绝对路径（用 `%USERPROFILE%` / 相对路径），否则 416 测试会挂 2 个
- 所有命令非交互式；测试用 `python -m unittest discover -s tests -q`
- 中文输出统一 UTF-8（脚本里已有 reconfigure，保持）

## 验收清单

- [x] `scripts/ilang_eval_set.jsonl` 存在（164 句，2026-09-19 完成）
- [x] 对比表：embedding vs 关键词 vs 级联（79.9% / 60.4% / **86.0%** 端到端）
- [x] 级联写入主入口 `ilang_semantic_main.py`，schema 校验 4/4 PASS
- [x] `python -m unittest discover -s tests -q` 全过（416 基线，2026-09-19 两次复核 OK）
- [x] `ilang_nl2ilang.py` 对测试话术产出合法 I-Lang 语句
- [x] 底座横评完成（bge-small-zh 最优；jina 更差；mpnet/e5 败于本机内存）
- [ ] （可选）内存充裕时复测 e5-large，或 SetFit 微调冲 88%+
- [ ] （可选）skill 推荐骨架：`alternatives` 放 mode 对应的 skill 候选
