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

## 隐私边界

- 画像和记忆默认保存在 `~/.intent-translator/`，不会进入仓库。
- 项目本身不收集遥测。
- 读取记忆不会暗中增加访问计数；写入纠错和结果需要显式工具调用。
- 敏感记忆必须设置保留时间，用户可以检查、导出、撤回或删除。
- 发布、外发隐私、不可逆删除和其他高影响动作不能由一句模糊的“可以”扩大授权。

## 现在还不能吹什么

- 24 条回归题的 100% 只说明这些固定案例没有退化，不代表能理解所有人。
- 新语言、方言、职业和陌生表达仍需要真实用户评测。
- 各宿主是否自动调用 MCP 不完全一致。
- 可选语义模型层尚未完成，特别新颖的隐喻仍依赖宿主模型判断。

完整英文文档见 [README.md](README.md)，上线风险优先级见 [docs/launch-readiness.md](docs/launch-readiness.md)。
