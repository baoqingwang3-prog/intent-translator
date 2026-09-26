# 给 ZCode 的交接提示词：intent-translator 语义路由 e5-large 收尾

> 把本文件全文发给 ZCode。它自包含：背景、现状、每一步怎么跑、所有坑、验收标准。
> 工作目录：`D:\测试\intent-translator-repo`

## 一句话任务

**在 WSL 里跑通 `intfloat/multilingual-e5-large` embedding 模型的 164 句意图路由评测**（我卡在最后一步：模型文件已下载 95%，只差清单文件），拿到分数后与现有 bge-small-zh 级联方案对比，若更优则替换默认模型。

## 背景（已完成的，别重做）

这是一个本地意图编译器（intent-translator v1.0.0a5）的语义增强项目。已落地：

| 文件（都在 `scripts/`） | 作用 | 状态 |
|---|---|---|
| `ilang_distill_router.py` | embedding 意图路由器（质心+双阈值+弃权） | ✅ 稳定 |
| `ilang_distill_intents.json` | 10 mode × 226 条中英原型句 | ✅ 可继续补 |
| `ilang_semantic_main.py` | **级联主入口**：keyword+embed 仲裁 | ✅ 端到端 86.0% |
| `ilang_semantic_adapter.py` | I-Lang 语法（`[VERB:@T\|k=v]=>`）解析 | ✅ |
| `ilang_nl2ilang.py` | 自然语言→I-Lang 反向编译 | ✅ |
| `ilang_eval_set.jsonl` | 164 句评测集（132 benchmark+32 口语） | ✅ |
| `ilang_compare_eval.py` | 三方对比评测脚本 | ✅ |

现有成绩（164 句）：keyword 单独 79.9%，embed(bge-small-zh) 单独 60.4%，**级联 86.0%**。
底座横评：jina-v2-base-zh 42.1%（更差，弃用）；**e5-large 是最后一个候选**。

## 现状：e5-large 卡在哪

WSL 的 Ubuntu 24.04 里已建好 venv（`~/ilang/venv`，fastembed 0.8.0 + pydantic 已装）。
跑法：

```bash
wsl -e bash -c "export ILANG_DISTILL_EMBED_MODEL=intfloat/multilingual-e5-large HF_ENDPOINT=https://hf-mirror.com; ~/ilang/venv/bin/python /mnt/d/测试/intent-translator-repo/scripts/ilang_compare_eval.py"
```

**卡点**：fastembed 0.8 走 huggingface xet 协议下载大文件，hf-mirror.com 不代理 xet 的 `cas-server.xethub.hf.co`，报 401。

**精确进度（09-21 晚）**：`model.onnx_data`（2.235GB）已下载 **~430MB（19%）**，断点文件在：
`%USERPROFILE%\AppData\Local\Temp\fastembed_cache\models--qdrant--multilingual-e5-large-onnx\blobs\0cf1883fee...85ac7127.incomplete`

我这边已停掉下载循环（断点文件保留）。实测 hf-mirror 直连仅 ~0.35MB/s，跑完剩余 1.8GB 要 80+ 小时，**这条慢路不推荐**。快路见下：

- **快路 A（推荐，一条命令）**：给 WSL 开宿主代理。WSL NAT 网段（172.19.x.x）访问 Windows 宿主 7897 端口被防火墙拦，需**管理员 PowerShell** 执行（你有权限，我这边被安全策略挡了）：
  ```powershell
  New-NetFirewallRule -DisplayName "Allow 7897 from WSL" -Direction Inbound -LocalPort 7897 -Protocol TCP -Action Allow -Profile Any
  ```
  然后 WSL 里（网关 IP 用 `ip route show default` 现查，我上次是 172.19.96.1，重启会变）：
  ```bash
  export HTTPS_PROXY=http://172.19.96.1:7897 HTTP_PROXY=http://172.19.96.1:7897 HF_HUB_DISABLE_XET=1
  ```
  走宿主 Clash 直连 hf.co，速度正常，几分钟下完
- **快路 B**：浏览器/下载工具直接下 `https://hf-mirror.com/qdrant/multilingual-e5-large-onnx/resolve/main/model.onnx_data`（2.08GB），下完放到上面 blobs 目录，改名 `0cf1883fee81c63819a44e2ba0efa51d4043d9759685a4ebebbde97e0623d15c`（去掉 `.incomplete` 后缀）

缓存目录结构：
```
%USERPROFILE%\AppData\Local\Temp\fastembed_cache\
  blobs\（分片与 ONNX 本体）
  models--Qdrant--bge-small-zh-v1.5\        (完整，当前在用)
  models--jinaai--jina-embeddings-v2-base-zh\
  models--qdrant--multilingual-e5-large-onnx\ (模型清单+snapshot 链接，缺 model.onnx_data)
```

## 你要做的（按顺序）

1. **开代理快路**（快路 A 或 B 二选一，见上），把 `model.onnx_data` 补齐（2.08GB）
2. **验证模型可离线加载**：删掉 `.incomplete` 后缀改名后，跑：
   ```bash
   wsl -e bash -c "export ILANG_DISTILL_EMBED_MODEL=intfloat/multilingual-e5-large; ~/ilang/venv/bin/python /mnt/d/测试/intent-translator-repo/scripts/ilang_compare_eval.py"
   ```
   推理约 5-9 分钟（164 句 × 226 原型句编码，CPU 单线程），耐心等
3. **判定**：
   - e5-large 纯 embed 分数 **> 60.4%**（bge-small 基线）→ 再跑级联对比；级联 > 86.0% 就把 `ilang_distill_router.py` 第 63 行默认模型改为 e5-large
   - ≤ 60.4% → 结论写"e5-large 无增益"，保持 bge-small，收工

## 硬坑清单（每个都真实踩过）

- **WSL 实例会回收**：`/tmp` 和长时间空闲的 WSL 实例会被杀，venv 必须放 `~/ilang/venv`（home 持久），别放 /tmp。wsl.conf 的 `vmIdleTimeout` 在此版本无效，别折腾
- **网络**：WSL 直连 huggingface.co 不通；走宿主 7897 代理被防火墙拦（加规则需管理员，我这边提权被安全策略挡了）；**hf-mirror.com 可直连**（小文件 OK，xet 大文件 401）
- **评测脚本必须内存充足时跑**：Windows 侧空闲内存 <3GB 时 onnxruntime 会 bad allocation（脚本已固定 `OMP_NUM_THREADS=1`，别改回多线程）
- **别用 MiniLM**（paraphrase-multilingual-MiniLM-L12-v2）：内存分配崩溃，已拉黑
- **仓库有泄露审计**：`scripts/release_audit.py` + `test_personalization_firewall` 会扫所有文本文件，代码/文档里出现 `C:\Users\<用户名>` 或 `D:\测试` 绝对路径 → 416 个测试挂 2 个。写路径一律用 `os.path.expanduser("~")` 或 `%USERPROFILE%`
- **上游 `src/` 勿动**：仓库有大量未提交的用户升级现场（15 文件 3810 行，0.10.0a1→1.0.0a5），不是垃圾，别 git checkout 清掉
- **pip 必须加** `--index-url https://pypi.org/simple`（默认源 404）

## 验收

- [ ] e5-large 在 164 句评测集上的分数（纯 embed + 若更优则级联）
- [ ] 与基线对比结论（bge-small 60.4% / 级联 86.0%）
- [ ] 若替换默认模型：改 `ilang_distill_router.py:63`，重跑 `ilang_semantic_main.py` 冒烟（3 句：I-Lang 语句、中文 change 句、diagnose 句）
- [ ] `python -m unittest discover -s tests -q` 416 全过（venv：`C:\Users\<你>\.intent-translator\mcp\runtimes\1.0.0a5\venv\Scripts\python.exe`，测试里路径已用 ~ 展开写）
- [ ] 最终报告：分数表 + 是否换模型的判断依据
