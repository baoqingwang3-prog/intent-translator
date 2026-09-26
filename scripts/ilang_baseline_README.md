# 基线记录（2026-09-22）

## 运行环境
- Python 3.13.12（WorkBuddy managed）、fastembed 0.8.0、onnxruntime 1.30.0
- E5 模型目录：%TEMP%/e5l_model/（model.onnx 545KB + model.onnx_data 2.08GB，从 fastembed xet 缓存 blob 拼装）
- 具体跑法见 ilang_compare_eval.py 的 provenance 输出（含全部 sha256）

## 结果（164 句开发集，非 held-out）
| 路由 | 命中 | 准确率 |
|---|---|---|
| embed(E5-large, maxsim) | 122 | 74.4% |
| keyword | 131 | 79.9% |
| **cascade(E5)** | **142** | **86.6%** |

对照（bge-small-zh，09-19）：embed 60.4% / keyword 79.9% / cascade 86.0%

## 延迟（单线程，E5-large 已预热）
- 初始化 39s（常驻进程只发生一次）
- cascade 单句：median 224ms / p95 260ms（满足 P95 ≤ 500ms 目标）
- embed 单句：median 218ms

## 结论
- E5-large 纯 embed 74.4% 显著高于 bge-small 60.4%（+14pt）
- E5 级联 86.6% vs BGE 级联 86.0%：+0.6pt，收益来自 embed 路径增强后"embed-rescue"翻案更准
- 内存成本：ONNX RSS 约 2.2GB（加载后常驻），超 ≤1GB 目标 → E5 适合"按需加载/独立进程"而非常驻 WorkBuddy 主进程
- 判定：BGE-small 保持默认（内存达标），E5-large 作为可选高精度模式（ILANG_DISTILL_MODEL_PATH + ILANG_DISTILL_EMBED_MODEL 环境变量启用）

## 已知失败（不放宽门槛）
- fastembed 原生缓存路径加载 E5 会报 "External data path escapes model directory"（xet blob 分散布局导致）；解法即本目录的拼装模型。此项为工具链限制，不是模型或代码缺陷
