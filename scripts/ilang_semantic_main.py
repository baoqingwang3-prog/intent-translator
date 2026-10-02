r"""Hybrid semantic adapter entry point — cascaded decision.

One process, three paths, one JSON contract:

1. I-Lang detected  ([VERB:@T|k=v]=>... or greek aliases)
   -> syntax parser (ilang_semantic_adapter.build_proposal)
2. otherwise        -> cascade: local keyword engine (IntentCompiler) and
   local embedding router (ilang_distill_router.route) are consulted, then
   arbitrated:
   a) both agree                        -> that mode
   b) kw says answer w/ conf<=0.60      -> embed mode  (kw fallback tier)
   c) any other disagreement            -> kw mode     (stronger prior)

Import note: the keyword engine lives in the repo's src/ tree, which needs
pydantic; both src/ and the fastembed deps dir are added to sys.path with
expanduser("~") so no personal absolute paths leak (release audit checks
this). Set ILANG_DISTILL_DEPS to override the deps location.

The command adapter uses a local model and no API keys. For a strict offline
run, configure a cached model snapshot and enable the router's offline mode.
Output matches the SemanticProposal schema.
"""

from __future__ import annotations

import json
import re
import os
import sys
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# deps dir for fastembed + pydantic (overridable; no absolute personal paths)
_DEFAULT_DEPS = Path.home() / ".workbuddy-ai" / "binaries" / "node" / "workspace" / "pydeps"
DEPS = Path(os.environ.get("ILANG_DISTILL_DEPS", str(_DEFAULT_DEPS)))
if DEPS.is_dir() and str(DEPS) not in sys.path:
    sys.path.append(str(DEPS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ilang_semantic_adapter import STEP_RE, build_proposal as ilang_proposal  # noqa: E402
from intent_translator_mcp.core import (  # noqa: E402
    _analyze_action_clauses, _context_has_resumable_action, _educational_pending_action,
    _explanatory_question, _has_independent_followup_request,
    _leading_local_edit_before_veto,
    _directive_action_surface, _missing_reference_slots, _primary_compression_request,
    _primary_local_diagnosis, _primary_local_lookup, _primary_memory_recall,
    _primary_memory_store, _primary_public_lookup, _primary_teaching_request,
    _selection_index,
)

_ANSWER_FALLBACK_CONF = 0.60

# Plan #2 "widen LLM escalation": local disagreement on a close call is
# exactly where the host LLM adds value. When keyword wins a disagreement
# but both sides were weak, the cascade keeps keyword's mode (authority
# never transfers) yet flags the proposal for host-LLM review via
# clarification_recommended=True. Guard classes (refusal / continuation /
# invalid) are decided before these gates and are never affected.
_ESCALATE_DISAGREE_KW_CONF = 0.60
_ESCALATE_EMBED_SCORE = 0.55

# I-Lang verb whitelist (step 3: tighten detection). Plain brackets like
# [TODO], [PDF], [ERROR], [甲方] must NOT enter the I-Lang path.
_ILANG_VERBS = {
    # data I/O
    "READ", "WRIT", "GET", "DEL", "LIST", "COPY", "MOVE", "STRM", "CACH", "SYNC", "SEND", "RUN",
    # transform
    "FMT", "CONV", "SPLIT", "MERGE", "MAP", "FILT", "SORT", "DEDU", "FLAT", "NEST", "CHNK",
    "REDU", "PIVT", "TRNS", "ENCD", "DECD", "HASH", "CMPR", "EXPN", "XLAT", "REWR", "DIFF",
    # analysis
    "SCAN", "MTCH", "CNT", "STAT", "EVAL", "SCOR", "RANK", "TRND", "CORR", "FRCS", "ANOM",
    "SENT", "CLST", "BNCH", "AUDT", "VALD", "CLSF",
    # generation
    "CREA", "DRFT", "EXPD", "SHRT", "PARA", "STYL", "TMPL", "FILL", "EXTC", "GEN",
    # execution
    "PLAN", "DECI", "CHEK", "FIX", "DPLO", "SAVE", "REVW", "LERN", "TEST", "PARS", "LOOP", "WAIT",
    # output / structure / meta / batch
    "OUT", "DISP", "EXPT", "PRNT", "LOG", "LINK", "SET", "TAG", "GRP", "EMBD",
    "HELP", "DESC", "INTR", "NOOP", "BATC",
    # memory-ish extensions used by the adapter
    "MEM", "RECALL", "REMEM", "ROUTE", "DIAG",
    # greek aliases
    "Σ", "Δ", "φ", "∇", "λ", "∂", "μ", "ψ", "ξ", "ζ", "θ", "Ω", "Π",
}


def has_ilang_syntax(utterance: str) -> bool:
    """Recognize a complete I-Lang expression, not a command quoted in prose."""
    source = utterance.strip()
    matches = list(STEP_RE.finditer(source))
    if not matches or matches[0].start() != 0 or matches[-1].end() != len(source):
        return False
    if any((match.group(1) or "") not in _ILANG_VERBS for match in matches):
        return False
    if any(source[before.end():after.start()].strip() != "=>"
           for before, after in zip(matches, matches[1:])):
        return False
    return len(matches) > 1 or bool((matches[0].group(2) or "").strip()
                                     or (matches[0].group(3) or "").strip())


# continuation: terse utterances resolved via context + pending_action
_CONTINUATION_TERSE = {"可以", "继续", "往下讲", "往下讲吧", "继续讲", "继续讲吧", "接着讲", "接着讲吧", "接着来", "接着干", "嗯，就这么办", "ok", "okk",
                       "okay", "好", "行", "就这么办", "干吧", "go", "ok继续"}
_REFUSAL_TERSE = {"不要", "别", "不行", "算了", "取消", "停", "先别", "no", "cancel"}
_CORRECTION_START = re.compile(r"^(?:换成|改成|改为)\s*(\S+)")
_CORRECTION_NEW_ACTION = re.compile(
    r"^(?:(?:直接|先)\s*)?(?:搜索|查找|调研|删除|安装|发布|上传|发送|创建|生成|"
    r"分析|诊断|排查|测试|翻译|修改|修复|构建|开发|运行|查询|"
    r"解释|说明|概括|归纳|总结|规划|教我)", re.I)
_CORRECTION_NEGATION = re.compile(r"^(?:不要|不再|不|别|取消|停止|暂停|先别)")
_EXTERNAL_PENDING = re.compile(r"发布|上架|推送|上传|外发|发送|发给|发到|共享|公开|publish|push|upload", re.I)
_CONSTRAINT_TAIL = re.compile(
    r"^(?P<primary>.+?)(?:[，,]\s*)?(?:但是|不过|但|[，,])\s*"
    r"(?:绝对\s*)?(?:先)?(?:不要|别|不得|禁止)")


def _pure_revocation(source: str) -> bool:
    """A withdrawn action is a control turn unless another task is requested."""
    negation = re.search(
        r"(?:不要忘记|别忘记)(?!\S)|"
        r"(?:不要|不得|禁止|别|先别|不再|取消|撤销|作废|停止|暂停)\s*"
        r"(?:再|去|把|将)?\s*(?:安装|升级|上传|推送|发布|发送|外发|删除|移除|清空|"
        r"修改|更改|执行|运行|付款|支付|install|publish|upload|delete|change|run)",
        source,
        re.I,
    )
    if not negation or source[negation.start():].startswith(("不要忘记", "别忘记")):
        return False
    before = source[:negation.start()]
    after = source[negation.end():]
    if re.search(r"查|核对|核查|检查|搜索|找出|解释|分析|总结|概括|修改|修复|创建|写|\bcheck\b|\bsearch\b", before, re.I):
        return False
    # A 把-construction before the ban ("把草稿改好存在本地，别推送") is an
    # asserted directive with a prohibition tail, not a pure revocation.
    if re.search(r"把\s*\S", before):
        return False
    if _has_independent_followup_request(source):
        return False
    return True


def _all_actions_revoked(source: str) -> bool:
    if _has_independent_followup_request(source):
        return False
    actions = [clause for clause in _analyze_action_clauses(source) if clause["predicate"] != "other"]
    if not actions or any(clause["polarity"] != "prohibited" for clause in actions):
        return False
    return any(
        earlier["predicate"] == later["predicate"]
        and not re.search(r"不要|不得|禁止|别|取消|撤销|作废|停止|暂停", earlier["text"])
        and re.search(r"不要|不得|禁止|别|取消|撤销|作废|停止|暂停", later["text"])
        for i, earlier in enumerate(actions)
        for later in actions[i + 1:]
    )


def _independent_goal_modes(source: str) -> set[str]:
    parts = re.split(r"[,，；;]\s*(?:并且|并|同时|然后|接着)\s*", source)
    if len(parts) < 2:
        return set()
    return {mode for part in parts if (mode := _clear_primary_mode(part))}


def _constrained_primary_mode(utterance: str) -> str | None:
    """Read an explicit primary request without letting a ban choose its mode."""
    match = _CONSTRAINT_TAIL.match(utterance.strip())
    if not match:
        return None
    primary = match.group("primary").strip()
    if len(primary) > 40 or re.search(r"并|然后|同时|顺便", primary):
        return None
    if re.match(r"^(?:请|帮我)?\s*(?:搜索|查找|检索)", primary):
        return "search"
    if re.match(r"^(?:请|帮我)?\s*总结", primary):
        return "compress"
    if re.match(r"^(?:请|帮我)?\s*分析", primary) and re.search(r"日志|报错|错误|异常", primary):
        return "diagnose"
    if re.match(r"^(?:请|帮我)?\s*(?:想想|想几个|起几个)", primary) and re.search(r"标题|名字|题目", primary):
        return "answer"
    return None


def _existing_artifact_answer(utterance: str) -> bool:
    """Distinguish explanation of existing material from search or editing."""
    source = utterance.casefold()
    if re.search(
        r"(?:官方文档|官网|联网|互联网|全网|github|\bweb\b|搜索|搜搜|查一查|查查|"
        r"修改|更改|改成|编辑|替换|填好|删除|安装|卸载|部署|执行|推送|发布|上传|发送|"
        r"创建|生成|制作|写(?:一个|个|入)|做(?:一个|个)|抓出来|提取|摘要|总结|浓缩|精简|"
        r"任务清单|规划|拆成|拆分|编排)",
        source,
    ):
        return False
    technical_object = re.search(
        r"(?:命令|\bsql\b|开关|配置|这个类|这段类|函数|方法|changelog|folder|\brepo\b|文档|文件|代码)",
        source,
    )
    explanation = re.search(
        r"(?:干嘛使的|是查什么的|打开之后影响什么|作用是什么|含义是什么|方法列表|"
        r"\bhighlights\b|\blayout\b)",
        source,
    )
    if technical_object and explanation:
        return True
    existing_item = re.search(r"(?:这个|这条|这份|文档里|文件里|卡片|\bthis\b|\bthe\b)", source)
    list_or_count = re.search(r"(?:列个清单|方法列表|还有几个|有多少|有哪些|数量是多少)", source)
    return bool(existing_item and list_or_count)


def _explicit_primary_mode(utterance: str) -> str | None:
    """Recognize a few direct requests whose action is clearer than router scores.

    This is only a mode proposal. The host still parses constraints, effects,
    authorization, and execution independently.
    """
    source = utterance.strip()
    if len(source) > 200 or re.match(r"^(?:请|帮我)?\s*(?:先)?(?:不要|别|禁止|停止|取消|暂停)", source):
        return None
    if (re.search(r"(?:然后|同时|顺便|并且)", source)
            or re.search(r"[，,]\s*(?:请|帮我)?\s*(?:教我|讲讲|写|做|搜索|查找|运行|部署)", source)):
        return None
    lower = source.casefold()

    build_start = re.match(r"^(?:帮我|请)?\s*(?:写|做|造|撸|搭|搞|起)(?:一个|个|套)?", source)
    if build_start:
        if re.search(
            r"(?:脚本|工具|爬虫|站点|中间件|demo|ci|流水线|mock|服务器|插件|项目|"
            r"计算器|轮子|装饰器|应用|程序)", lower
        ):
            return "build"
        return None

    route_signals = (
        r"^(?:帮我)?\s*(?:规划(?:一下)?|编排)",
        r"(?:应该派给|拆任务|先做哪个|后做哪个|先测哪个|给子代理的指令)",
        r"(?:可执行的\s*prompt|safe stages|可验收的小目标|交给\s*agent)",
        r"(?:发布前.*检查项|(?:转成|整理成).*任务清单)",
    )
    if any(re.search(pattern, lower) for pattern in route_signals):
        return "route"

    if re.search(r"^(?:请|帮我)?\s*(?:(?:把|将).{0,60})?(?:摘要|浓缩|精简).{0,40}(?:成|到|为)", source):
        return "compress"

    diagnostic_signals = (
        r"(?:一直|反复|总是|总)\S{0,12}(?:重启|崩|失败|超时|收不到)",
        r"(?:没触发|收不到|死循环|冲突怎么解|运行就崩|占用一路|狂转|过期了)",
        r"(?:端口.*被谁占|hang at teardown|exiting immediately)",
        r"(?:慢查询.*执行计划|报错怎么回事|(?:为啥|为什么|why).*(?:failed|报错|异常|崩|重启))",
    )
    if any(re.search(pattern, lower) for pattern in diagnostic_signals):
        return "diagnose"

    recall_signals = (
        r"(?:上次|上回|之前|昨天|以前).*(?:记的|存的|定下|配置的|会议纪要|怎么给我改)",
        r"(?:我记的.*待办|之前存的|上次记的)",
    )
    if any(re.search(pattern, lower) for pattern in recall_signals):
        return "recall"

    learning_signals = (
        r"^(?:请|帮我)?\s*(?:教我|教教我|讲讲|用大白话解释)",
        r"(?:打比方.*讲|给我讲明白|with a toy example|学习路线|这章.*考点|错题.*错在哪)",
    )
    if any(re.search(pattern, lower) for pattern in learning_signals):
        return "learn"

    search_signals = (
        r"^(?:请|帮我)?\s*(?:搜搜|搜索|检索|查查).*(?:权威释义|评测|缩写|全称)",
        r"^(?:请|帮我)?\s*(?:看看|查询).*房价.*(?:走势|数据)",
        r"^(?:请|帮我)?\s*(?:找几个|找一些).*(?:免费资源|学习资源|练习资源)",
        r"(?:作者|创始人).*(?:还写过|还做过).*项目",
        r"社区里怎么评价",
    )
    if any(re.search(pattern, lower) for pattern in search_signals):
        return "search"

    if (re.match(r"^(?:帮我)?\s*(?:把|将).*(?:拆成.*文件|调大|调小|转成|清理了|"
                 r"清理掉|替换成|填好|排版调好|优化一下|改成)", source)
            or re.match(r"^(?:帮我)?\s*(?:卸载|升一下|装一下)", source)
            or re.search(r"(?:模板|表格|表单).*(?:字段|空白|占位符).*填好", source)):
        return "change"

    if _existing_artifact_answer(source):
        return "answer"

    if (re.search(r"^(?:以后|今后).*(?:回答|输出).*(?:都|用|保持)", source)
            or re.search(r"(?:时区|语言|格式|风格).*偏好.*(?:设成|设置)", source)):
        return "remember"
    return None


def _clear_primary_mode(utterance: str) -> str | None:
    """Route an explicit request from its main verb, ignoring quoted data."""
    source = utterance.strip()
    if len(source) > 300:
        return None
    if re.search(r"只看.{0,24}(?:状态|差异|日志)", source) and not re.search(
        r"修改|更改|写入|删除|发布|上传", source
    ):
        return "diagnose"
    if _explanatory_question(source):
        return "answer"
    if _primary_memory_recall(source):
        return "recall"
    if _primary_memory_store(source):
        return "remember"
    if _primary_compression_request(source):
        return "compress"
    if _primary_teaching_request(source):
        return "learn"
    if _primary_local_diagnosis(source):
        return "diagnose"
    if _primary_public_lookup(source) or _primary_local_lookup(source):
        return "search"
    if re.search(r"更新.{0,24}(?:现有|已有|原有)", source):
        return "change"
    source = re.sub(r"“[^”]*”|‘[^’]*’|\"[^\"]*\"|'[^']*'", " 内容 ", source)
    source = re.sub(r"\s+", " ", source).strip()

    if re.search(r"^(?:我)?(?:上次|上回|之前|以前|此前).{0,45}(?:说过|记住|约定|规定|偏好|截止|默认|格式|是什么|多少|什么时候|哪)", source) or re.match(r"^(?:请)?(?:回忆|回想)(?:一下)?", source):
        return "recall"
    if re.match(r"^(?:请)?(?:记住|记下|记一下|记下来)", source) or re.search(r"记作|(?:请)?记下来[。.!！]?$", source):
        return "remember"
    if re.search(r"(?:应|该|要)?(?:交给|分给|归到|派给|进入).{0,40}(?:还是|子代理|队列|部门|组)", source) or re.search(r"(?:还是).{0,25}(?:处理|负责|归属|队列)", source) or re.search(r"^(?:请)?(?:判断|判定).{0,40}(?:归属|进入.{0,20}队列)", source) or re.search(r"(?:应该|该|适合|由哪|谁).{0,24}(?:组|团队|部门|角色|代理|子任务).{0,16}(?:接手|负责|处理|执行|承接)", source) or re.search(r"(?:谁|哪个|哪组|哪队).{0,22}(?:接手|负责|处理|执行|承接)", source):
        return "route"
    if re.search(r"(?:压缩成|压缩到|压成|缩成|缩到|缩为|浓缩为|浓缩成|精简成|概括|归纳为|归纳成|提炼|总结成|改写成一句)", source) and not re.search(r"(?:学会|教我|带我学|如何写|怎么写).{0,20}(?:摘要|总结|概括|归纳)", source):
        return "compress"
    if re.search(r"(?:教我|教教我|带我学会|让我练|让我试|用提问方式|做一步等我|每轮只纠正|跟我练)", source) or re.search(r"(?:我想学会|我不会).{0,60}(?:请先教|给我.{0,16}练习|做一步等我)", source):
        return "learn"
    if re.search(r"(?:日志|报错|错误|失败|超时|变慢|启动不了|崩溃|瓶颈)", source) and re.search(r"(?:先)?(?:查|找|判断|分析|排查|定位|解释).{0,35}(?:原因|瓶颈|为什么|在哪|怎么回事)|(?:原因|瓶颈|为什么).{0,20}(?:在哪|出现|导致)|先查原因", source):
        return "diagnose"
    if re.search(r"^(?:请|帮我)?\s*(?:查一下|查找|检索|搜索|搜一下|找找|找三篇|找几篇|找标题|找出).{2,}", source) and not re.search(r"(?:原因|瓶颈|为什么).{0,12}(?:在哪|导致|出现)?", source):
        return "search"
    if re.search(r"^(?:请|帮我)?\s*在.{0,25}(?:项目|仓库|目录)里找出.{0,45}(?:定义|文件|路径|位置)", source):
        return "search"
    if re.search(r"^(?:请|帮我)?\s*(?:在.{0,20}(?:项目|仓库|目录|文件)里)?(?:继续|接着)?(?:查|搜).{0,30}(?:官方|公告|文档|文件|资料|论文|网页|来源)", source):
        return "search"
    if re.search(r"^(?:请|帮我)?\s*(?:把|将).{0,90}(?:改为|改成|修改|修正|替换|合并|调整|修复)", source) or re.match(r"^(?:请|帮我)?\s*(?:修正|修改|修复|调整|替换)(?:现有|已有|当前|这个|这份|该)", source):
        return "change"
    if re.search(r"^(?:请|帮我)?\s*(?:新建|创建|搭|做一份|写一个|给.{0,35}做一套).{0,70}(?:新|模板|练习题|原型|脚本|工具|页面|清单)", source):
        return "build"
    if re.match(r"^(?:什么是|何为|已知.{0,80}(?:多少|几|求)|现在是.{0,60}换算)", source) or re.search(r"(?:换算成).{0,25}(?:几点|多少)", source) or re.match(r"^(?:不要搜索[，,]\s*)?(?:直接)?解释.{0,80}(?:是什么|什么意思|含义)", source):
        return "answer"
    return None

# pending_action text -> mode inference (ordered, first hit wins)
_PENDING_HINTS: list[tuple[str, str]] = [
    ("发布", "build"), ("publish", "build"), ("上架", "build"), ("生成", "build"),
    ("创建", "build"), ("写一个", "build"), ("实现", "build"), ("开发", "build"),
    ("爬虫", "build"), ("切换", "change"),
    ("测试", "change"), ("test", "change"), ("升级", "change"), ("修改", "change"),
    ("删除", "change"), ("delete", "change"), ("安装", "change"), ("移动", "change"),
    ("更新", "change"), ("改", "change"), ("修复", "change"), ("fix", "change"),
    ("分析", "diagnose"), ("诊断", "diagnose"), ("排查", "diagnose"), ("调研", "search"),
    ("搜索", "search"), ("search", "search"), ("查找", "search"), ("找", "search"),
    ("摘要", "compress"), ("压缩", "compress"), ("精简", "compress"), ("合并", "compress"),
    ("概括", "compress"), ("归纳", "compress"),
    ("解释", "answer"), ("说明", "answer"), ("教我", "learn"), ("规划", "route"),
    ("翻译", "change"), ("translate", "change"),
]


def infer_pending_mode(pending_action: str) -> str | None:
    if _educational_pending_action(pending_action):
        return "learn"
    text = pending_action.casefold()
    for hint, mode in _PENDING_HINTS:
        if hint in text:
            return mode
    return None


def _keyword_compile(utterance: str, context: str = "", pending_action: str = "") -> dict:
    """Deterministic keyword engine; returns {mode, confidence} or {}."""
    try:
        os.environ.setdefault("INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON", "[]")
        from intent_translator_mcp.models import CompileRequest
        from intent_translator_mcp.core import IntentCompiler

        global _KW_COMPILER
        try:
            compiler = _KW_COMPILER
        except NameError:
            compiler = _KW_COMPILER = IntentCompiler(entrypoint="semantic-adapter")
        env = compiler.compile(CompileRequest(
            utterance=utterance, context=context,
            pending_action=pending_action, semantic_mode="off",
        ))
        return {
            "mode": env.get("mode"),
            "confidence": float(env.get("confidence") or 0.0),
        }
    except Exception:
        return {}


def _embed_route(utterance: str) -> dict:
    from ilang_distill_router import route

    return route(utterance)


def _is_meaningless(text: str) -> bool:
    """True for noise: no real token, one-character input, or a repeating pattern
    ("测试测试测试", "help me help me help me"), pure punctuation/emoji."""
    t = re.sub(r"\s+", "", text)
    if not re.search(r"[一-鿿A-Za-z0-9]", t):
        return True
    if len(t) <= 1:
        return True
    # Common keyboard-row runs are noise, including "asdfjkl". A short
    # meaningful request such as "改代码" must still reach the router.
    if re.fullmatch(r"(?:asdf|jkl|qwer|tyui|zxcv|bnm|qwerty)+", t.casefold()):
        return True
    for unit in (1, 2, 3):
        if len(t) >= 2 * unit and len(t) % unit == 0:
            chunk = t[:unit]
            if chunk * (len(t) // unit) == t:
                return True
    # space-separated same-token spam ("help me help me help me"):
    # unique word count tiny relative to total tokens
    toks = [w.casefold() for w in re.findall(r"[A-Za-z一-鿿]+", text)]
    return len(toks) >= 3 and len(set(toks)) <= max(1, len(toks) // 3)


def cascade_mode(utterance: str, context: str = "", pending_action: str = "") -> tuple[str | None, str, float]:
    """Return (mode, decider, confidence) using the validated cascade.

    decider is one of: continuation, refusal, agree, embed-rescue, kw-prior,
    kw-escalate, embed-only, kw-only, none.

    kw-escalate: keyword still wins the mode (authority never transfers),
    but the proposal is flagged for host-LLM review because the local
    evidence was weak on both sides.
    """
    # Step 0a: refusal / revocation always wins and never executes.
    active_request = _directive_action_surface(utterance)
    stripped = re.sub(r"[。.!！?？\s]+$", "", active_request.strip().casefold())
    has_followup = (
        _has_independent_followup_request(stripped)
        or _leading_local_edit_before_veto(stripped)
    )
    scoped_cancellation = bool(
        pending_action.strip()
        and re.search(
            r"取消|撤销|撤回|作废|停止|中止|停掉|先别|别再|不要|不用|不再|别删|别改",
            stripped,
        )
        and not has_followup
        and (
            re.match(r"^(?:先|暂时|现在)?(?:别|不要|不用|不再|取消|撤销|停止|中止)", stripped)
            or re.search(
                r"(?:计划|步骤|动作|这一步|那一步|操作|指令|安排).{0,16}(?:取消|撤销|作废|停掉|停止)",
                stripped,
            )
            or re.search(r"(?:刚才|先前).{0,24}(?:取消|撤销|作废|停掉|停止)", stripped)
            or re.search(r"(?:取消|撤销|撤回|作废|停掉|停止)(?:了|掉)?$", stripped)
        )
    )
    correction_turn = bool(pending_action.strip() and _CORRECTION_START.match(utterance.strip()))
    if not correction_turn and (stripped in _REFUSAL_TERSE or scoped_cancellation or _pure_revocation(stripped) or _all_actions_revoked(stripped)):
        return None, "refusal", 1.0

    # "先这样" closes the discussion for now; it does not confirm the
    # pending action or specify a new one.
    if stripped in {"先这样", "暂时这样", "就这样吧"}:
        return None, "continuation-unresolved", 0.3

    if _missing_reference_slots(stripped, pending_action, context):
        return None, "reference-unresolved", 0.3

    if _selection_index(stripped) is not None and not pending_action.strip() and not _context_has_resumable_action(context):
        return None, "selection-unresolved", 0.3

    if pending_action.strip() and _educational_pending_action(pending_action) and re.match(
        r"^(?:继续|接着|往下|再往下)讲", stripped,
    ):
        return "learn", "continuation", 0.9

    if pending_action.strip() and re.fullmatch(
        r"(?:好|可以|行)[，,]?\s*(?:就)?按(?:刚才|之前)(?:说的|约定的)?(?:改|做|执行|办)",
        stripped,
    ):
        pending_mode = infer_pending_mode(pending_action)
        return pending_mode, "continuation" if pending_mode else "continuation-unresolved", 0.9 if pending_mode else 0.3

    # Step 0b: terse continuation / bare terse approval resolved by
    # pending_action (checked BEFORE meaningless: "可以" is tiny but
    # meaningful — with or without a pending action).
    if stripped in _CONTINUATION_TERSE:
        pending_mode = infer_pending_mode(pending_action) if pending_action.strip() else None
        if pending_mode:
            return pending_mode, "continuation", 0.9
        # no pending action: it is a bare approval/ack; flag for host LLM
        # instead of guessing (nothing local to resolve it against).
        return None, "continuation-unresolved", 0.3

    # A correction to a named prior action needs that action for its scope.
    correction = _CORRECTION_START.match(utterance.strip()) if pending_action.strip() else None
    if correction:
        target = correction.group(1)
        if _CORRECTION_NEGATION.match(target):
            return None, "correction-unresolved", 0.3
        if _CORRECTION_NEW_ACTION.match(target):
            if re.match(r"^(?:解释|说明)", target):
                return "answer", "correction", 0.8
            target_mode = infer_pending_mode(target)
            if target_mode:
                return target_mode, "correction", 0.8
            return None, "correction-unresolved", 0.3
        return infer_pending_mode(pending_action) or "change", "correction", 0.8

    constrained_mode = _constrained_primary_mode(active_request)
    if constrained_mode:
        return constrained_mode, "constraint-primary", 0.82

    # Step 0c: meaningless input abstains (spam, symbols, tiny/repeating).
    if _is_meaningless(active_request):
        return None, "invalid", 0.0

    if len(_independent_goal_modes(active_request)) > 1:
        return None, "multi-goal-unresolved", 0.3

    clear_mode = _clear_primary_mode(active_request)
    if clear_mode:
        return clear_mode, "clear-primary", 0.85

    explicit_mode = _explicit_primary_mode(active_request)
    if explicit_mode:
        return explicit_mode, "explicit-primary", 0.82

    kw = _keyword_compile(active_request, context, pending_action)
    emb = _embed_route(active_request)
    kmode, kconf = kw.get("mode"), float(kw.get("confidence") or 0.0)
    emode = emb.get("mode")
    escore = float(emb.get("raw_score") or 0.0)

    if emode and kmode:
        if emode == kmode:
            return kmode, "agree", max(kconf, emb["confidence"])
        if kmode == "answer" and kconf <= _ANSWER_FALLBACK_CONF and emode != "answer":
            return emode, "embed-rescue", emb["confidence"]
        # close disagreement: kw keeps the mode, escalate to host LLM
        if kconf <= _ESCALATE_DISAGREE_KW_CONF and escore >= _ESCALATE_EMBED_SCORE:
            return kmode, "kw-escalate", kconf
        return kmode, "kw-prior", kconf
    if emode:
        return emode, "embed-only", emb["confidence"]
    if kmode:
        return kmode, "kw-only", kconf
    return None, "none", 0.0


# Skill recommendation (from routes.md ownership table). Conservative:
# only consulted when the cascade is confident (agree / continuation);
# rescue and escalate cases keep primary_skill None so the host LLM never
# gets a skill hint for a borderline call. None means "no clean route".
_SKILL_ROUTES: dict[str, tuple[str | None, list[str]]] = {
    "search": ("agent-reach", ["smart-search", "deep-research"]),
    "diagnose": ("diagnosing-bugs", ["tdd"]),
    "build": ("tdd", ["code-review"]),
    "change": ("tdd", ["code-review"]),
    "learn": ("study-assistant", []),
    "answer": (None, []),
    "compress": (None, []),
    "route": (None, []),
    "remember": (None, []),
    "recall": (None, []),
}


def _skill_hint(mode: str | None, decider: str, confidence: float) -> tuple[str | None, list[str]]:
    """Conservative and NON-ROUTING: skill candidates go into alternatives
    only. primary_skill stays None because the compiler treats it as a
    routing instruction (observed: a suggested-but-uninstalled skill flips
    execute=True -> False, i.e. the semantic layer would be changing
    authorization behavior — the boundary it must never cross)."""
    if mode is None or confidence < 0.80:
        return None, []
    if os.environ.get('ILANG_SKILL_HINTS', '1') != '1':
        return None, []
    primary, alts = _SKILL_ROUTES.get(mode, (None, []))
    candidates = ([primary] if primary else []) + list(alts)
    return None, candidates[:5]


def cascade_proposal(payload: dict) -> dict:
    utterance = str(payload.get("utterance", "")).strip()
    context = str(payload.get("context", "") or "")
    pending_action = str(payload.get("pending_action", "") or "")
    deterministic = payload.get("deterministic_draft") or {}
    mode, decider, confidence = cascade_mode(utterance, context, pending_action)
    external_review = decider in {"continuation", "correction", "correction-unresolved"} and bool(
        _EXTERNAL_PENDING.search(pending_action) or _EXTERNAL_PENDING.search(utterance))
    if decider == "refusal":
        interpretation = "Terse refusal/revocation detected; no execution proposed."
        control_status = "revoke" if pending_action.strip() or _pure_revocation(_directive_action_surface(utterance)) else "clarify"
        # A bound revocation is already decided. Only an unbound veto asks back.
        clar = control_status == "clarify"
    elif decider == "continuation":
        interpretation = f"Continuation resolved via pending_action -> {mode}."
        control_status = "normal"
        clar = external_review
    else:
        interpretation = (
            f"Cascaded router: mode={mode or 'abstain'} via {decider} (conf={confidence:.2f})."
        )
        # Skill candidates ride the interpretation text (host-LLM-visible,
        # compiler-inert): putting them in primary_skill/alternatives was
        # observed to flip the gateway execute decision, which would let the
        # semantic layer change authorization behavior — forbidden.
        skill_primary, skill_alts = _skill_hint(mode, decider, confidence)
        if skill_alts:
            interpretation += f" Skill candidates: {', '.join(skill_alts)}."
        control_status = "clarify" if mode is None else "normal"
        clar = mode is None or decider in {"embed-rescue", "kw-escalate", "none", "constraint-primary"} or external_review
    primary_skill, skill_alts = _skill_hint(mode, decider, confidence)
    return {
        "normalized_goal": str(deterministic.get("normalized_goal") or utterance)[:1000],
        "interpretation": interpretation,
        "mode": mode,
        "assumptions": [],
        "alternatives": [],
        "confidence": round(min(1.0, max(0.0, confidence)), 4),
        "primary_skill": None,
        "risk_hints": ["external"] if external_review else [],
        "clarification_recommended": bool(clar),
        "control_status": control_status,
        "language": "zh",
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 1
    utterance = str(payload.get("utterance", ""))
    if has_ilang_syntax(utterance):
        proposal = ilang_proposal(payload)
        proposal["interpretation"] = "[ilang] " + proposal.get("interpretation", "")
    else:
        proposal = cascade_proposal(payload)
    json.dump(proposal, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
