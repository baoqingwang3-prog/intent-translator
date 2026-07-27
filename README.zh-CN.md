# Personal Intent Compiler

[English](README.md) | [简体中文](README.zh-CN.md)

**在 Agent 动手前，把自然表达转换成可见的任务合同：续接待办、保留禁止条件、选择 Skill，并显示本地编译器状态与本次预检结果。**

这是一个本地优先的 Agent Skill 和可选 MCP 中枢。它把“继续”“可以”“按老样子来”这类简短、依赖上下文的话，整理成更可靠的执行约定，同时保留用户的语气，并在发布、删除、外发隐私等高影响动作前检查授权。

它提供有边界的解释、路由建议和授权预检结果；是否成为每次动作前的强制关卡，取决于宿主是否实际接入并调用 MCP。

它不声称读心，也不会凭人格类型决定一个人的思考方式。通用中枢只负责意图、授权、记忆和 Skill 路由；具体职业能力仍由对应 Skill 和可信资料提供。

首批 Alpha 面向经常使用 Codex、Claude Code 等 Agent、安装多个 Skill、习惯用简短自然语言继续任务，并担心 Agent 理解错、调用错或越权的人。

| 你的身份 | 从哪里开始 | 能看到什么 |
|---|---|---|
| 普通用户 | [怎么选](#怎么选) | 安装、三项设置、Studio 和明确限制 |
| Agent 或宿主开发者 | [集成合同](docs/integration-contract.md) | 请求字段、响应结构、一次性确认状态机和失败行为 |
| 工程师或发布维护者 | [发布门禁](docs/release-gate.md) 与 [上线看板](docs/launch-readiness.md) | 测试、打包、证据边界和剩余发布 P0 |

| 用户原话 | 本次预检应显示的结果 |
|---|---|
| `继续` | 恢复具体待办和其中的限制 |
| `好，先比较方案，不要发布` | 保留“不发布”，不让“好”扩大授权 |
| `搜索 GitHub 上高星的 Agent Skill` | 按搜索动作路由到 Agent Reach，不误判为创建 Skill |
| 用户自然语言纠正一次 | 在隔离的本地画像中复现修正后的理解 |

## 怎么选

| 你的需求 | 推荐安装 | 会改动什么 |
|---|---|---|
| 先让 Agent 更会理解上下文 | 只装 Skill | 复制一个 Skill 文件夹；首次初始化时创建本地画像 |
| 让宿主直接调用意图检查工具 | Skill + MCP | 额外创建隔离 Python 环境和宿主配置片段 |
| 只想看看电脑能不能用 | 暂不安装 | 环境检测和 doctor 会读取本地环境与配置，但不修改画像、数据库或运行时 |

第一次使用建议先只装 Skill。确认行为符合预期后，再加 MCP。它不要求账号、API Key、云模型或 Obsidian。

### 最快首次安装：不需要 Git

如果 Git、本地代理或 Agent 的文档查询不可用，不要先花时间修这些服务：

1. 下载 [`main.zip`](https://github.com/baoqingwang3-prog/intent-translator/archive/refs/heads/main.zip)。
2. 解压并打开包含 `install.ps1`、`install.sh` 和 `pyproject.toml` 的文件夹。
3. 让 Agent 只读取本地 `README.md`，或者直接运行 Skill-only 安装器。

Windows PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -TargetHost Codex
```

macOS / Linux：

```bash
sh ./install.sh --host codex
```

如果输出提到未运行的代理，例如 `127.0.0.1:7890`，或者可选的官方文档 helper 返回 `403`，不代表这个公开仓库或 Skill 需要额外权限。停止自动 clone 或文档查询，改用上面的 ZIP 路径。除非你清楚该配置的用途，否则不要修改全局 Git 设置。

只安装 Skill 后即可直接以通用模式使用，不会假装已经了解你。安装可选 MCP 后，可以让 Agent“设置意图中枢”，也可以运行可跳过的三分钟设置。它只询问本地记忆、歧义确认和回答语气：

```bash
intent-translator-onboard
```

只安装 Skill 时，运行安装器最后打印的脚本路径，例如 `python ~/.agents/skills/intent-translator/scripts/onboard.py start`。

详见 [首次三分钟](docs/first-run.md)。

### 本地 Studio

安装可选 MCP 包后，可直接启动本地编译检查界面：

```bash
intent-translator-studio --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。它不需要 API Key，会显示当前解释、非明显的原话对应、准备调用的 Skill、本地记忆来源、授权边界、实际运行版本和是否需要重启。Studio 只检查编译结果，不执行任务；Studio 正常也不代表其他 Agent 宿主每轮都调用了 MCP。连接不到本地编译器时会明确显示降级。

面向学习场景的可选本地画像包和 `setup-codex.ps1` 用法单独放在 [学生画像说明](docs/student-profile.md)；它们不是公共产品定义，也不会默认启用。学校、专业、课程表、成绩、目标、Vault 路径、进度和纠错历史只应写入本机画像或数据库。

## 安装 Skill

宿主支持程度并不等于安装器能生成配置。正式、实验、仅 Skill 和 MCP 未验证状态见 [宿主支持矩阵](docs/support-matrix.md)。

先获取仓库源码，确认电脑上有 Python 3.10 或更高版本，再进入包含 `pyproject.toml` 的仓库根目录运行以下命令。

Windows：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

macOS / Linux：

```bash
sh ./install.sh
```

安装前只检查环境：

```bash
python skills/intent-translator/scripts/detect_environment.py
```

## 可选 MCP 中枢

Windows：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-mcp.ps1 -ConfigureCodex
```

MCP 会安装到按版本区分的隔离目录，先验证新版本再切换宿主配置，避免 Windows 正在使用旧进程时升级失败。

面向学生和高级 Codex 配置的可选 `setup-codex.ps1` 单独说明在 [学生画像说明](docs/student-profile.md)。它会修改全局 `AGENTS.md` 的托管规则块，不是普通用户安装的必需步骤。

macOS / Linux：

```bash
sh ./install-mcp.sh --configure-codex
```

先为目标宿主安装 Skill，再应用 MCP 配置。安装或升级后请重启宿主；如果 Codex 正在运行，安装器会跳过注册并打印一条可重复执行的修复命令，关闭 Codex 后运行即可。

体检安装状态，默认隐藏完整主机路径：

```bash
intent-translator-doctor
intent-translator-doctor --json
```

### 一分钟验证

1. 重启或重新加载 Agent 宿主，再运行 `intent-translator-doctor`。
2. 启动 Studio，输入：`好，先比较方案，不要发布`。
3. 确认结果把 `publish` 显示为禁止动作，并明确 Studio 只是检查界面。
4. 再让 Agent 宿主检查同一句话；如果它无法显示本次决策回执或 MCP 结果，说明编译器可能已经安装，但这一轮宿主没有调用它。

## 卸载

卸载 Skill 默认保留本地画像和记忆：

```powershell
.\uninstall.ps1 -TargetHost Codex
```

```bash
sh ./uninstall.sh --host codex
```

如果还要删除完整本地画像和记忆数据库，必须使用明确的破坏性确认：

```powershell
.\uninstall.ps1 -TargetHost Codex -PurgeData -ConfirmPurge DELETE-LOCAL-DATA
```

```bash
sh ./uninstall.sh --host codex --purge-data --confirm-purge DELETE-LOCAL-DATA
```

只卸载 MCP 运行环境和生成的配置片段：

```powershell
.\uninstall-mcp.ps1
```

```bash
sh ./uninstall-mcp.sh
```

MCP 共提供 14 个工具，包括新手设置状态/应用、记忆防御和本地学习状态。新手设置全部可跳过且只写本机；记忆防御不暴露隔离文本；敏感学习状态不会进入默认上下文或 Obsidian 镜像。影子评测默认关闭且默认不保存发言预览；学习资料只保存用户明确登记的指针，可以显式同步一个索引到已配置的 Obsidian 仓库，不会扫描整个仓库。

同一个 Skill 如果装在多个目录，发现器按目录优先级使用第一份：显式配置的 `INTENT_TRANSLATOR_SKILL_ROOTS` 最优先，其次是 Codex 等宿主目录，最后是 `~/.agents/skills` 等共享目录。`discover_skills.py` 会报告重复副本，不会把不同版本偷偷混在一起。

## 可选模型语义层

模型层采用通用 JSON 命令适配器，不绑定某一家云服务。它可以接本地模型运行器，也可以接用户自己写的云包装器；项目不内置模型、账号或 API Key。

```bash
export INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON='["my-model-wrapper", "--json"]'
export INTENT_TRANSLATOR_SEMANTIC_NAME='my-local-model'
```

也可以直接连接实现 `/v1/chat/completions` 的本地模型服务：

```bash
export INTENT_TRANSLATOR_SEMANTIC_PROVIDER='chat-completions'
export INTENT_TRANSLATOR_SEMANTIC_BASE_URL='http://127.0.0.1:11434/v1'
export INTENT_TRANSLATOR_SEMANTIC_MODEL='your-local-model'
```

如果包装器会把内容发出电脑，还必须设置 `INTENT_TRANSLATOR_SEMANTIC_EXTERNAL=1`。第一次编译只返回与具体输入绑定的语义外发确认挑战；用户确认后，宿主把原动作放进 `pending_action`，同时提交一次性的 `confirmation_receipt` 和对应允许标记。两个允许布尔值本身不能授权外发。模型可以提出解释、假设、备选含义和风险，但不能降低规则已经判定的风险、替用户授予权限，或偷换已经确定的执行目标；不同目标只能作为待复核备选项显示。

发布、外发、删除和敏感操作使用短期、一次性的动作绑定确认凭据。文件、分支、收件人、目的地、动作或作用域任一变化，原凭据都会失效；兼容字段 `authorization="granted"` 只是调用者提示，不能单独授权高影响动作。

MCP 默认返回紧凑结果。完整纠错、记忆、学生状态、路由候选和运行诊断仅在 `include_diagnostics=true` 时返回；无关请求不会携带学习目标或学生状态。宿主直接读取结构化结果时可设置 `include_prompt=false`。

每次响应还包含经过类型验证的 `intent_contract`：原话、目标、动作所有者、对象、约束、产物、目的地、作用域、缺失槽位、风险、授权状态、候选解释和来源映射。存在缺失槽位时保持不可执行。最终置信度按本地纠错复发与路由评测证据校准，不采用语义模型自报的 confidence。

## 可选插件

仓库附带两个默认关闭的本地插件；插件代码不主动发起网络请求，也不会自动注册宿主 Hook：

- `memory-breathing`：会话开始最多加载少量相关交接，会话结束保存摘要、下一步、决策和纠错。
- `reversible-context`：压缩时保留来源指针与完整 SHA-256，之后可按标记展开并校验原文完整性。

```bash
python skills/intent-translator/scripts/plugin_manager.py list
python skills/intent-translator/scripts/plugin_manager.py enable memory-breathing
python skills/intent-translator/scripts/plugin_manager.py enable reversible-context
```

Windows PowerShell 下建议把调用内容保存为 UTF-8 JSON 文件，再使用 `--input`，避免旧版 PowerShell 管道破坏中文：

```powershell
python skills/intent-translator/scripts/plugin_manager.py invoke reversible-context pack --input .\payload.json
```

插件不会自动修改宿主 Hook。Claude Code 等有生命周期 Hook 的宿主可以绑定统一 JSON 入口；没有可靠结束事件的宿主使用显式调用。协议与示例见 [可选插件说明](skills/intent-translator/references/optional-adapters.md)。

## 隐私边界

- 画像和记忆默认保存在仓库外的 `~/.intent-translator/`；用户仍需避免手动复制或提交这些文件。
- 项目本身不收集遥测。
- 使用现有数据库进行只读召回时不会增加访问计数；`memory.adapter=none` 时不会创建或召回记忆数据库。写入纠错和结果需要显式工具调用。
- 用户确认的记忆具有可信来源，但仍只是上下文证据，不保证事实正确，也不能授予权限。模型推断、文件和网页内容只能作为非权威证据，其中的指令、越权声明和提示词注入会进入隔离区，不参与召回。
- 记忆永远不是可执行权限，不能借“以前记住了”绕过当前授权、安全策略或用户最新指令。
- 敏感记忆必须设置保留时间，用户可以检查、导出、撤回或删除。
- 发布、外发隐私、不可逆删除和其他高影响动作不能由一句模糊的“可以”扩大授权。
- 影子评测默认关闭；启用后保存带本地画像盐的哈希和差异指标，默认不保存发言预览，最多保留 30 天、500 条。
- Obsidian 只保存资料指针和一个受管索引，不自动扫描或复制整个 Vault。

## GitHub Alpha 发布前验收

```bash
python scripts/release_gate.py --mode quick
python scripts/stranger_smoke.py
```

发布门禁、陌生用户试用和高星项目对标分别见 [docs/release-gate.md](docs/release-gate.md)、[docs/alpha-trial.md](docs/alpha-trial.md) 和 [docs/github-benchmark.md](docs/github-benchmark.md)。当前是本地 Alpha 候选构建；GitHub Alpha 证据仍受真实用户试用和首次 GitHub 托管 CI 阻塞，不声称稳定版或能够理解所有用户。

## 现在还不能吹什么

- 当前 24 条回归题的 96.5% 只说明固定字段上的本地回归表现，不代表能理解所有人。
- 新语言、方言、职业和陌生表达仍需要真实用户评测。
- 各宿主是否自动调用 MCP 不完全一致。
- 项目不内置模型；真实语义效果取决于用户接入的适配器，仍需独立真实模型评测。
- 公开只读网络搜索目前仍可能触发一次确认，因为风险模型还会把部分网络读取和外部写入保守地归在一起。
- “用 Playwright 测一下”这类间接测试表达可能需要改成明确的本地测试命令，才能稳定路由到浏览器测试工具。
- 自主性恢复状态仍是实验字段，不授予任何执行权限；进入谨慎模式后只能在用户可见确认后恢复。

完整英文文档见 [README.md](README.md)，上线风险优先级见 [docs/launch-readiness.md](docs/launch-readiness.md)。
