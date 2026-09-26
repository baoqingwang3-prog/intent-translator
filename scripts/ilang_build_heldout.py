r"""Build the held-out test set (step 2 of the integration plan).

~200 fresh utterances across ten modes plus adversarial categories:
  - colloquial phrasings (never seen in prototypes or dev set)
  - multi-turn continuation (context + pending_action pairs)
  - negation & revocation ("不要删", "先别发布")
  - quoted commands ("帮我跑 [DEL:@LOCAL] 这条" -> must NOT enter I-Lang path)
  - plain brackets ("[TODO]", "[PDF]" -> must NOT be parsed as I-Lang)
  - invalid inputs (empty-ish, emoji, gibberish)

Anti-leakage: rejects any candidate whose char-3gram similarity to an
existing anchor or dev-set utterance exceeds ALLOWED_SIMILARITY.

Output: scripts/ilang_heldout_set.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWED_SIMILARITY = 0.35


def trigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text.lower())
    return {t[i:i + 3] for i in range(max(1, len(t) - 2))} if len(t) >= 3 else {t}


def max_similarity(text: str, existing: set[str]) -> float:
    tg = trigrams(text)
    if not tg:
        return 0.0
    best = 0.0
    for other in existing:
        og = trigrams(other)
        if not og:
            continue
        inter = len(tg & og)
        best = max(best, inter / max(1, min(len(tg), len(og))))
    return best


CANDIDATES: list[dict] = [
    # ---- answer (20) ----
    {"utterance": "这个函数的入参都有啥含义", "expected_mode": "answer"},
    {"utterance": "念一下这个配置文件里都配了什么", "expected_mode": "answer"},
    {"utterance": "他这么写是几个意思", "expected_mode": "answer"},
    {"utterance": "帮我瞅瞅日志最后报了啥", "expected_mode": "answer"},
    {"utterance": "这段正则匹配的是什么东西", "expected_mode": "answer"},
    {"utterance": "这仨方案哪个更靠谱说说理由", "expected_mode": "answer"},
    {"utterance": "这篇论文的方法部分讲了啥", "expected_mode": "answer"},
    {"utterance": "curl 这个命令是干嘛使的", "expected_mode": "answer"},
    {"utterance": "帮我捋一遍这个类的方法列表", "expected_mode": "answer"},
    {"utterance": "what does this stack trace indicate", "expected_mode": "answer"},
    {"utterance": "read the changelog and tell me the highlights", "expected_mode": "answer"},
    {"utterance": "这条 SQL 是查什么的", "expected_mode": "answer"},
    {"utterance": "帮我看看这个网页表格里都有啥数据", "expected_mode": "answer"},
    {"utterance": "这个词在这句话里啥意思", "expected_mode": "answer"},
    {"utterance": "describe the folder layout of this repo", "expected_mode": "answer"},
    {"utterance": "他这段话的言外之意是什么", "expected_mode": "answer"},
    {"utterance": "帮我对一下这两版需求文档讲清差异在哪", "expected_mode": "answer"},
    {"utterance": "这个开关打开之后影响什么", "expected_mode": "answer"},
    {"utterance": "看看这份财报的营收结构", "expected_mode": "answer"},
    {"utterance": "把这段二进制的头部信息解读一下", "expected_mode": "answer"},
    # ---- search (20) ----
    {"utterance": "帮我扒一扒这个框架的背景", "expected_mode": "search"},
    {"utterance": "查查有没有人遇到过同样的报错", "expected_mode": "search"},
    {"utterance": "找几个能替代 postman 的开源工具", "expected_mode": "search"},
    {"utterance": "帮我搜搜这个词的权威释义", "expected_mode": "search"},
    {"utterance": "这个库的作者还写过什么项目", "expected_mode": "search"},
    {"utterance": "帮我调研下国产数据库的近况", "expected_mode": "search"},
    {"utterance": "搜一下这个报错对应的 issue", "expected_mode": "search"},
    {"utterance": "find me recent papers on retrieval augmented generation", "expected_mode": "search"},
    {"utterance": "查一查这条命令的官方文档怎么说", "expected_mode": "search"},
    {"utterance": "帮我看看同行都在用什么技术栈", "expected_mode": "search"},
    {"utterance": "找一下这个接口的调用示例", "expected_mode": "search"},
    {"utterance": "搜搜这款显示器的评测", "expected_mode": "search"},
    {"utterance": "帮我打听打听这家公司靠不靠谱", "expected_mode": "search"},
    {"utterance": "查查这个缩写全称是什么", "expected_mode": "search"},
    {"utterance": "research which vector database fits our scale", "expected_mode": "search"},
    {"utterance": "帮我看看房价走势数据", "expected_mode": "search"},
    {"utterance": "找几个练口语的免费资源", "expected_mode": "search"},
    {"utterance": "搜一下这个插件的使用教程", "expected_mode": "search"},
    {"utterance": "帮我查查这本教材哪个版本最新", "expected_mode": "search"},
    {"utterance": "看看这条新闻的后续报道", "expected_mode": "search"},
    # ---- build (20) ----
    {"utterance": "帮我撸一个命令行计算器", "expected_mode": "build"},
    {"utterance": "搭一个能自动签到的小脚本", "expected_mode": "build"},
    {"utterance": "帮我写个 Chrome 扩展屏蔽广告", "expected_mode": "build"},
    {"utterance": "生成一个带登录的博客系统骨架", "expected_mode": "build"},
    {"utterance": "帮我造一个轮子：通用重试装饰器", "expected_mode": "build"},
    {"utterance": "做个网页版番茄钟", "expected_mode": "build"},
    {"utterance": "帮我整一个批量改文件名的工具", "expected_mode": "build"},
    {"utterance": "写一个番茄工作法的计时页面", "expected_mode": "build"},
    {"utterance": "create a cli tool to batch resize images", "expected_mode": "build"},
    {"utterance": "帮我搞个爬虫监控价格变动", "expected_mode": "build"},
    {"utterance": "从零写一个简易解释器", "expected_mode": "build"},
    {"utterance": "帮我实现一个短链接服务", "expected_mode": "build"},
    {"utterance": "做一个家庭记账本小程序", "expected_mode": "build"},
    {"utterance": "帮我搭个静态站点托管我的笔记", "expected_mode": "build"},
    {"utterance": "写个脚本自动备份聊天记录", "expected_mode": "build"},
    {"utterance": "帮我生成一个开源项目的 README 模板", "expected_mode": "build"},
    {"utterance": "build an rss aggregator service", "expected_mode": "build"},
    {"utterance": "帮我做一个单词卡记忆应用", "expected_mode": "build"},
    {"utterance": "写个中间件统一处理异常", "expected_mode": "build"},
    {"utterance": "帮我设计一个秒杀系统的原型", "expected_mode": "build"},
    # ---- change (20) ----
    {"utterance": "帮我把这个类拆成三个文件", "expected_mode": "change"},
    {"utterance": "把日志级别从 debug 改成 info", "expected_mode": "change"},
    {"utterance": "修复分页参数传错的问题", "expected_mode": "change"},
    {"utterance": "把这个接口改成异步的", "expected_mode": "change"},
    {"utterance": "帮我卸载掉这个没用的包", "expected_mode": "change"},
    {"utterance": "把配置里的超时时间调大一点", "expected_mode": "change"},
    {"utterance": "帮我把这段过程式代码改成函数式", "expected_mode": "change"},
    {"utterance": "更新一下版权年份", "expected_mode": "change"},
    {"utterance": "把这个变量的名字改得语义化一点", "expected_mode": "change"},
    {"utterance": "帮我把测试跑一遍然后修复失败的", "expected_mode": "change"},
    {"utterance": "migrate the database schema to add an index", "expected_mode": "change"},
    {"utterance": "帮我把图片统一转成 webp", "expected_mode": "change"},
    {"utterance": "把这两个函数合并成一个", "expected_mode": "change"},
    {"utterance": "帮我调整一下页面间距", "expected_mode": "change"},
    {"utterance": "把这个硬编码的值挪进配置文件", "expected_mode": "change"},
    {"utterance": "帮我覆盖掉旧版本的部署", "expected_mode": "change"},
    {"utterance": "把这段注释掉的代码清理了", "expected_mode": "change"},
    {"utterance": "帮我升一下 node 版本", "expected_mode": "change"},
    {"utterance": "把文件夹按日期归档一下", "expected_mode": "change"},
    {"utterance": "帮我改改这个 prompt 让它更精炼", "expected_mode": "change"},
    # ---- diagnose (20) ----
    {"utterance": "容器一直重启循环是为啥", "expected_mode": "diagnose"},
    {"utterance": "接口偶发 502 帮我分析下", "expected_mode": "diagnose"},
    {"utterance": "内存占用一路飙红什么情况", "expected_mode": "diagnose"},
    {"utterance": "为啥我的 git 提交被拒了", "expected_mode": "diagnose"},
    {"utterance": "这个定时任务没触发帮我查查", "expected_mode": "diagnose"},
    {"utterance": "为什么前端资源加载全 404", "expected_mode": "diagnose"},
    {"utterance": "帮我看看是不是证书过期了", "expected_mode": "diagnose"},
    {"utterance": "编译过了运行就崩什么鬼", "expected_mode": "diagnose"},
    {"utterance": "数据库锁表了帮我找原因", "expected_mode": "diagnose"},
    {"utterance": "why does my test suite hang at teardown", "expected_mode": "diagnose"},
    {"utterance": "消息队列堆积严重帮我诊断下", "expected_mode": "diagnose"},
    {"utterance": "这个 crash 的调用栈帮我读一下", "expected_mode": "diagnose"},
    {"utterance": "帮我查查端口被谁占了", "expected_mode": "diagnose"},
    {"utterance": "风扇狂转是不是有死循环", "expected_mode": "diagnose"},
    {"utterance": "这个依赖冲突怎么解", "expected_mode": "diagnose"},
    {"utterance": "dns 解析偶尔失败帮我看看", "expected_mode": "diagnose"},
    {"utterance": "帮我分析下这次慢查询的执行计划", "expected_mode": "diagnose"},
    {"utterance": "服务起来但健康检查不过咋回事", "expected_mode": "diagnose"},
    {"utterance": "为什么打包产物比上个版本大十倍", "expected_mode": "diagnose"},
    {"utterance": "这条告警是不是误报帮我看看", "expected_mode": "diagnose"},
    # ---- learn (15) ----
    {"utterance": "帮我通俗讲讲什么是闭包", "expected_mode": "learn"},
    {"utterance": "陪我刷几道动态规划题", "expected_mode": "learn"},
    {"utterance": " Raft 共识算法用打比方的方式讲讲", "expected_mode": "learn"},
    {"utterance": "帮我制定英语六级 60 天冲刺计划", "expected_mode": "learn"},
    {"utterance": "教我怎么用 gdb 调试", "expected_mode": "learn"},
    {"utterance": "帮我总结一下这章的考点", "expected_mode": "learn"},
    {"utterance": "explain bloom filters with a toy example", "expected_mode": "learn"},
    {"utterance": "这两个算法复杂度为啥差这么多讲讲", "expected_mode": "learn"},
    {"utterance": "带我把线性代数的特征值过一遍", "expected_mode": "learn"},
    {"utterance": "帮我出五道操作系统选择题练手", "expected_mode": "learn"},
    {"utterance": "大端序小端序给我讲明白", "expected_mode": "learn"},
    {"utterance": "帮我梳理一下这门课的知识框架", "expected_mode": "learn"},
    {"utterance": "讲讲 http 缓存的几种头部怎么配合", "expected_mode": "learn"},
    {"utterance": "陪我练一段日语自我介绍", "expected_mode": "learn"},
    {"utterance": "帮我分析这道错题错在哪", "expected_mode": "learn"},
    # ---- remember (15) ----
    {"utterance": "记一下：项目要用 pnpm 不用 npm", "expected_mode": "remember"},
    {"utterance": "帮我存着这个镜像源地址", "expected_mode": "remember"},
    {"utterance": "记住我下班时间是六点", "expected_mode": "remember"},
    {"utterance": "把这个决定记下来：接口统一走 v2", "expected_mode": "remember"},
    {"utterance": "以后回答都用表格形式", "expected_mode": "remember"},
    {"utterance": "帮我保存这组配色方案", "expected_mode": "remember"},
    {"utterance": "记住这个服务器地址别再问我", "expected_mode": "remember"},
    {"utterance": "store this: staging password rotates weekly", "expected_mode": "remember"},
    {"utterance": "把我常用的构建命令记一下", "expected_mode": "remember"},
    {"utterance": "记住这个偏好：代码注释用中文", "expected_mode": "remember"},
    {"utterance": "帮我记着周三要交周报", "expected_mode": "remember"},
    {"utterance": "存一下这个 awesome 列表的链接", "expected_mode": "remember"},
    {"utterance": "记下来这个月的目标是减脂五斤", "expected_mode": "remember"},
    {"utterance": "帮我记住这套命名规范", "expected_mode": "remember"},
    {"utterance": "把我的时区偏好设成东八区", "expected_mode": "remember"},
    # ---- recall (15) ----
    {"utterance": "之前让你存的那个地址是啥来着", "expected_mode": "recall"},
    {"utterance": "我上次记的端口是多少", "expected_mode": "recall"},
    {"utterance": "按老规矩来，别问", "expected_mode": "recall"},
    {"utterance": "翻翻之前的笔记看有没有写这个", "expected_mode": "recall"},
    {"utterance": "上回那个正则你是怎么给我改的", "expected_mode": "recall"},
    {"utterance": "把昨天定下的方案名给我报一下", "expected_mode": "recall"},
    {"utterance": "我之前是不是让你记过一个镜像源", "expected_mode": "recall"},
    {"utterance": "recall the naming convention we agreed on", "expected_mode": "recall"},
    {"utterance": "上次那批文件移动到哪了", "expected_mode": "recall"},
    {"utterance": "帮我查查之前存的考试时间", "expected_mode": "recall"},
    {"utterance": "接着上回说的往下讲", "expected_mode": "recall"},
    {"utterance": "之前那个报错后来怎么解决的", "expected_mode": "recall"},
    {"utterance": "把我记的待办念一下", "expected_mode": "recall"},
    {"utterance": "上次的会议纪要里提到我啥事了", "expected_mode": "recall"},
    {"utterance": "按之前配置的样式输出", "expected_mode": "recall"},
    # ---- compress (15) ----
    {"utterance": "帮我把这个 300 行的类摘要成 30 行以内", "expected_mode": "compress"},
    {"utterance": "把这几条新闻合并成一段速览", "expected_mode": "compress"},
    {"utterance": "提炼一下这份纪要的 action items", "expected_mode": "compress"},
    {"utterance": "帮我把这个冗长的报错日志浓缩成关键几行", "expected_mode": "compress"},
    {"utterance": "把这十条相关笔记合并成一个主题笔记", "expected_mode": "compress"},
    {"utterance": "缩短这个函数名列表只留公共 API", "expected_mode": "compress"},
    {"utterance": "把这段访谈逐字稿压成十条要点", "expected_mode": "compress"},
    {"utterance": "condense the release notes into five bullets", "expected_mode": "compress"},
    {"utterance": "帮我把重复的样式规则去个重", "expected_mode": "compress"},
    {"utterance": "把这个大 JSON 精简成必须字段", "expected_mode": "compress"},
    {"utterance": "帮我浓缩这篇公众号文章成一段话", "expected_mode": "compress"},
    {"utterance": "把三个版本的方案合成一份最终版", "expected_mode": "compress"},
    {"utterance": "摘要一下这个 PR 的改动范围", "expected_mode": "compress"},
    {"utterance": "帮我精简这段自我介绍到三十字", "expected_mode": "compress"},
    {"utterance": "把会议两小时的内容提炼成三句话", "expected_mode": "compress"},
    # ---- route (15) ----
    {"utterance": "这个需求拆成前后端两个任务给不同人", "expected_mode": "route"},
    {"utterance": "帮我把这段描述改写成给子代理的指令", "expected_mode": "route"},
    {"utterance": "规划一下先测哪个模块", "expected_mode": "route"},
    {"utterance": "把用户故事翻译成开发任务列表", "expected_mode": "route"},
    {"utterance": "这个 bug 应该派给前端还是后端", "expected_mode": "route"},
    {"utterance": "帮我编排：先拉数据再训练最后出报告", "expected_mode": "route"},
    {"utterance": "把这句模糊需求整理成可执行的 prompt", "expected_mode": "route"},
    {"utterance": "plan the migration in safe stages", "expected_mode": "route"},
    {"utterance": "帮我决定这周先攻哪个技术债", "expected_mode": "route"},
    {"utterance": "给这三个子任务排出依赖顺序", "expected_mode": "route"},
    {"utterance": "帮我把大目标切成可验收的小目标", "expected_mode": "route"},
    {"utterance": "这个活儿适合我自己干还是交给 agent", "expected_mode": "route"},
    {"utterance": "梳理一下发布前要过的检查项", "expected_mode": "route"},
    {"utterance": "帮我把口语需求转成另一个 agent 能执行的指令", "expected_mode": "route"},
    {"utterance": "给这套流程画个分工图", "expected_mode": "route"},
    # ---- negation / revocation (12) ----
    {"utterance": "帮我把文件删了——等等，先别删", "expected_mode": "change", "constraint": "revoked-deletion"},
    {"utterance": "搜索一下但别上传我任何文件", "expected_mode": "search", "constraint": "no-egress"},
    {"utterance": "可以改代码，但绝对不要动数据库", "expected_mode": "change", "constraint": "no-db"},
    {"utterance": "总结可以，别发到群里", "expected_mode": "compress", "constraint": "no-share"},
    {"utterance": "帮我看看怎么部署但先别真的部署", "expected_mode": "diagnose", "constraint": "no-execute"},
    {"utterance": "把方案写成文档就好，不要发布", "expected_mode": "build", "constraint": "no-publish"},
    {"utterance": "分析这份日志，别修改任何文件", "expected_mode": "diagnose", "constraint": "read-only"},
    {"utterance": "查一下机票价格，不要帮我把钱付了", "expected_mode": "search", "constraint": "no-pay"},
    {"utterance": "把草稿改好存在本地，别推送", "expected_mode": "change", "constraint": "no-push"},
    {"utterance": "帮我想想标题，先别改文件", "expected_mode": "answer", "constraint": "read-only"},
    {"utterance": "测试一下接口，别往生产环境发请求", "expected_mode": "change", "constraint": "no-prod"},
    {"utterance": "可以装依赖，但别动全局环境", "expected_mode": "change", "constraint": "no-global"},
    # ---- quoted command / plain brackets (12) ----
    {"utterance": "帮我看看 [DEL:@LOCAL] 这条语句写的对不对", "expected_mode": "answer", "constraint": "quoted-ilang"},
    {"utterance": "这个 prompt 里的 [READ:@SRC] 是什么意思", "expected_mode": "answer", "constraint": "quoted-ilang"},
    {"utterance": "帮我给文档里的 [TODO] 项列个清单", "expected_mode": "answer", "constraint": "plain-bracket"},
    {"utterance": "把 markdown 里所有 [PDF] 链接抽出来", "expected_mode": "change", "constraint": "plain-bracket"},
    {"utterance": "代码里的 [deprecated] 标记还有多少处", "expected_mode": "answer", "constraint": "plain-bracket"},
    {"utterance": "这个 issue 模板的 [BUG] 部分帮我填一下", "expected_mode": "change", "constraint": "plain-bracket"},
    {"utterance": "帮我看看这个 ilang 语句 [SCAN:@GH]=>[OUT] 语法有错吗", "expected_mode": "answer", "constraint": "quoted-ilang"},
    {"utterance": "把文章里方括号占位符比如 [日期] 全部替换成真实日期", "expected_mode": "change", "constraint": "plain-bracket"},
    {"utterance": "[WIP] 状态的卡片还有几个没完", "expected_mode": "answer", "constraint": "plain-bracket"},
    {"utterance": "解释一下 [OUT] 在这个协议里代表什么", "expected_mode": "answer", "constraint": "quoted-ilang"},
    {"utterance": "帮我把日志里的 [ERROR] 行抓出来", "expected_mode": "change", "constraint": "plain-bracket"},
    {"utterance": "这份合同模板里的 [甲方] 字段帮我填好", "expected_mode": "change", "constraint": "plain-bracket"},
    # ---- invalid / noise (10) ----
    {"utterance": "asdfjkl", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "？？？", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "🙂🙃🙂", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "。，；", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "a", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "の", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "[]=>[]", "expected_mode": None, "constraint": "invalid-ilang"},
    {"utterance": "[=>[OUT]", "expected_mode": None, "constraint": "invalid-ilang"},
    {"utterance": "help me help me help me help me", "expected_mode": None, "constraint": "invalid"},
    {"utterance": "测试测试测试", "expected_mode": None, "constraint": "invalid"},
]


def main() -> None:
    anchors = {t for spec in json.load(open(HERE / "ilang_distill_intents.json", encoding="utf-8"))["modes"].values() for t in spec["utterances"]}
    dev = {json.loads(line)["utterance"] for line in open(HERE / "ilang_eval_set.jsonl", encoding="utf-8") if line.strip()}
    existing = anchors | dev

    kept, rejected = [], []
    for cand in CANDIDATES:
        sim = max_similarity(cand["utterance"], existing)
        if sim > ALLOWED_SIMILARITY:
            rejected.append({"utterance": cand["utterance"], "similarity": round(sim, 3)})
        else:
            kept.append(cand)
            existing.add(cand["utterance"])

    # multi-turn continuation pairs appended separately (context-bearing)
    continuations = [
        {"utterance": "可以", "context": "上一轮我提议把 README 的标题改掉", "pending_action": "修改 README 标题为 '项目文档'", "expected_mode": "change", "constraint": "continuation"},
        {"utterance": "可以", "context": "上一轮我提议把这个仓库发布到 GitHub", "pending_action": "发布仓库到 GitHub", "expected_mode": "build", "constraint": "continuation-high-risk"},
        {"utterance": "继续", "context": "上次正在用 Playwright 测试登录页", "pending_action": "用 Playwright 测试登录页", "expected_mode": "change", "constraint": "continuation"},
        {"utterance": "继续", "context": "上次正在分析一份销售数据的季度趋势", "pending_action": "分析销售数据季度趋势", "expected_mode": "diagnose", "constraint": "continuation"},
        {"utterance": "接着来", "context": "上次正在写一个爬虫脚本写到一半", "pending_action": "完成价格监控爬虫", "expected_mode": "build", "constraint": "continuation"},
        {"utterance": "嗯，就这么办", "context": "上一轮我提议把依赖升级到最新版", "pending_action": "升级项目依赖到最新版", "expected_mode": "change", "constraint": "continuation"},
        {"utterance": "ok", "context": "上一轮我提议生成单元测试", "pending_action": "为 utils 模块生成单元测试", "expected_mode": "build", "constraint": "continuation"},
        {"utterance": "先这样", "context": "刚才在讨论架构选型", "pending_action": "", "expected_mode": None, "constraint": "continuation-ambiguous"},
        {"utterance": "不要", "context": "上一轮我提议删除所有临时文件", "pending_action": "删除所有临时文件", "expected_mode": None, "constraint": "continuation-refusal"},
        {"utterance": "换成 gs", "context": "上一轮在讨论用哪个包管理器", "pending_action": "把依赖管理切换到 pnpm", "expected_mode": "change", "constraint": "continuation"},
    ]
    for cand in continuations:
        sim = max_similarity(cand["utterance"], existing)
        kept.append(cand)

    out = HERE / "ilang_heldout_set.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for item in kept:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    modes = {}
    for item in kept:
        key = item.get("expected_mode") or "abstain"
        modes[key] = modes.get(key, 0) + 1
    print(f"held-out set: {len(kept)} cases -> {out.name}")
    print("mode distribution:", json.dumps(modes, ensure_ascii=False))
    if rejected:
        print(f"rejected {len(rejected)} near-duplicates:")
        for r in rejected[:10]:
            print(f"  sim={r['similarity']} {r['utterance'][:36]}")


if __name__ == "__main__":
    main()
