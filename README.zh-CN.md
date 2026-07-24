# Personal Intent Compiler

[English](README.md) | [简体中文](README.zh-CN.md)

这是一个本地优先的 Agent Skill 和可选 MCP 中枢。它把“继续”“可以”“按老样子来”这类简短、依赖上下文的话，整理成更可靠的执行约定，同时保留用户的语气，并在发布、删除、外发隐私等高影响动作前检查授权。

它不声称读心，也不会凭人格类型决定一个人的思考方式。通用中枢只负责意图、授权、记忆和 Skill 路由；具体职业能力仍由对应 Skill 和可信资料提供。

## 怎么选

| 你的需求 | 推荐安装 | 会改动什么 |
|---|---|---|
| 先让 Agent 更会理解上下文 | 只装 Skill | 复制一个 Skill 文件夹；首次初始化时创建本地画像 |
| 让宿主直接调用意图检查工具 | Skill + MCP | 额外创建隔离 Python 环境和宿主配置片段 |
| 只想看看电脑能不能用 | 暂不安装 | 环境检测和 doctor 都是只读的 |

第一次使用建议先只装 Skill。确认行为符合预期后，再加 MCP。它不要求账号、API Key、云模型或 Obsidian。

如果主要使用 Codex，并希望一次装好 Skill、MCP、学生画像、托管规则和 doctor，可在 Windows 运行：

```powershell
.\setup-codex.ps1 -StudyGoal "期末考试","语言考试" -ObsidianVaultName "示例仓库" -ObsidianVaultPath "D:\Notes\ExampleVault" -ManagedNote "AI/学习索引.md" -EnableShadow
```

公开仓库包含通用的 `university-student` 大学生基础包和 `student-exam-prep` 目标扩展包。影子评测只有传入 `-EnableShadow` 才会启用。你的学校、专业、课程表、成绩、目标、当前科目、Vault 路径、进度、错题和纠错历史只写入本地画像或数据库，不应提交到 GitHub。结构说明见 [docs/student-profile.md](docs/student-profile.md)。

## 安装 Skill

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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-mcp.ps1
```

MCP 会安装到按版本区分的隔离目录，先验证新版本再切换宿主配置，避免 Windows 正在使用旧进程时升级失败。

可选的 `setup-codex.ps1` 可以一次安装 Skill 和 MCP、应用通用学生画像包，并向全局 `AGENTS.md` 写入可替换的托管规则块。脚本会先备份已有文件；学习目标和 Obsidian 路径只写入本机画像，不进入仓库。

macOS / Linux：

```bash
sh ./install-mcp.sh
```

体检安装状态，默认隐藏完整主机路径：

```bash
intent-translator-doctor
intent-translator-doctor --json
```

## 卸载

卸载 Skill 默认保留本地画像和记忆：

```powershell
.\uninstall.ps1 -TargetHost Codex
```

```bash
sh ./uninstall.sh --host codex
```

只卸载 MCP 运行环境和生成的配置片段：

```powershell
.\uninstall-mcp.ps1
```

```bash
sh ./uninstall-mcp.sh
```

MCP 共提供 10 个工具：7 个意图、纠错和结果工具，以及 `intent_shadow_observe`、`intent_shadow_review`、`intent_study_pointer`。影子评测默认关闭且默认不保存发言预览；学习资料只保存用户明确登记的指针，可以显式同步一个索引到已配置的 Obsidian 仓库，不会扫描整个仓库。

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

如果包装器会把内容发出电脑，还必须设置 `INTENT_TRANSLATOR_SEMANTIC_EXTERNAL=1`，并在每次请求里单独允许外发；涉及敏感内容时还要第二次授权。模型可以提出解释、假设、备选含义和风险，但不能降低规则已经判定的风险，也不能替用户授予发布、删除或外发权限。只有模型识别出的新动作一律先确认再执行。

## 隐私边界

- 画像和记忆默认保存在 `~/.intent-translator/`，不会进入仓库。
- 项目本身不收集遥测。
- 读取记忆不会暗中增加访问计数；写入纠错和结果需要显式工具调用。
- 敏感记忆必须设置保留时间，用户可以检查、导出、撤回或删除。
- 发布、外发隐私、不可逆删除和其他高影响动作不能由一句模糊的“可以”扩大授权。
- 影子评测默认关闭；启用后保存带本地画像盐的哈希和差异指标，默认不保存发言预览，最多保留 30 天、500 条。
- Obsidian 只保存资料指针和一个受管索引，不自动扫描或复制整个 Vault。

## 现在还不能吹什么

- 24 条回归题的 100% 只说明这些固定案例没有退化，不代表能理解所有人。
- 新语言、方言、职业和陌生表达仍需要真实用户评测。
- 各宿主是否自动调用 MCP 不完全一致。
- 项目不内置模型；真实语义效果取决于用户接入的适配器，仍需独立真实模型评测。

完整英文文档见 [README.md](README.md)，上线风险优先级见 [docs/launch-readiness.md](docs/launch-readiness.md)。
