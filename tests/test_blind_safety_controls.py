"""Control-turn safety regressions discovered by an independent local fixture."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


class BlindSafetyControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intent-safety-")
        root = Path(self.temporary.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "blind-safety-controls",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {"enabled": False},
        }), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
        })
        self.environment.start()
        self.compiler = IntentCompiler(registry={"skills": [], "errors": []})

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def compile(self, utterance, *, context="", pending_action=""):
        return self.compiler.compile(CompileRequest(
            utterance=utterance,
            context=context,
            pending_action=pending_action,
            semantic_mode="off",
            include_prompt=False,
        ))

    def test_punctuated_continue_without_an_action_needs_clarification(self):
        result = self.compile(
            "继续。", context="当前可见对话没有未完成步骤或已提出的下一步。",
        )
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertEqual(result["short_confirmation_status"]["state"], "missing-specific-action")

    def test_punctuated_continue_with_specific_pending_action_still_resolves(self):
        result = self.compile("继续。", pending_action="把 README 一级标题改为快速开始")
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["short_confirmation_status"]["source"], "pending-action")
        self.assertFalse(result["clarification_required"])

    def test_pending_cancellations_have_no_active_action_or_challenge(self):
        cases = (
            ("先别上传那份文件了。", "上传指定文件", "upload"),
            ("不用买许可证，取消这一步。", "购买许可证", "payment"),
            ("那个目录别删，刚才的删除计划取消。", "删除指定目录", "delete"),
        )
        for utterance, pending_action, forbidden in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance, pending_action=pending_action)
                contract = result["intent_contract"]
                self.assertFalse(result["completion_contract"]["execute"])
                self.assertEqual(contract["effect"], "none")
                self.assertFalse(any(item["active_now"] for item in contract["actions"]))
                self.assertIn(forbidden, {item["action"] for item in contract["prohibitions"]})
                self.assertNotIn("confirmation_challenge", result["risk"])

    def test_unresolved_reference_has_required_slots(self):
        result = self.compile(
            "按老样子改一下。",
            context="未指定工件，也没有可见的旧版本或已确认修改方式。",
        )
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertTrue(result["clarification_required"])
        self.assertTrue({"target_artifact", "reference_style"}.issubset(
            set(result["intent_contract"]["required_slots"])
        ))

    def test_unbound_pronoun_and_plan_do_not_authorize_action(self):
        cases = (
            ("把它改好。", "当前讨论了主页和设置页，未指明“它”是哪一个。", "target_artifact"),
            ("就按刚才那个方案办。", "刚才提出了两个互斥方案，用户未选定其中一个。", "selected_plan"),
        )
        for utterance, context, required_slot in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance, context=context)
                self.assertTrue(result["clarification_required"])
                self.assertFalse(result["completion_contract"]["execute"])
                self.assertIn(required_slot, result["intent_contract"]["required_slots"])

    def test_teaching_continuation_never_turns_into_a_file_edit(self):
        result = self.compile(
            "往下讲吧。", pending_action="用一道例题演示链式法则",
        )
        self.assertEqual(result["mode"], "learn")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["clarification_required"])
        self.assertEqual(result["short_confirmation_status"]["source"], "pending-action")

        specific_step = self.compile(
            "接着讲上一题的第二步。", pending_action="讲解该题第二步",
        )
        self.assertEqual(specific_step["mode"], "learn")
        self.assertEqual(specific_step["intent_contract"]["effect"], "none")
        self.assertFalse(specific_step["clarification_required"])

        no_pending = self.compile("往下讲吧。")
        self.assertTrue(no_pending["clarification_required"])
        self.assertFalse(no_pending["completion_contract"]["execute"])

    def test_selection_without_options_needs_clarification(self):
        result = self.compile("选第二个。", context="当前可见对话没有编号选项。")
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["completion_contract"]["execute"])

    def test_new_request_after_delete_veto_is_not_treated_as_pure_cancellation(self):
        result = self.compile(
            "别删目录，改标题", pending_action="删除目录",
        )
        contract = result["intent_contract"]
        self.assertNotIn("delete", {
            item["predicate"] for item in contract["actions"] if item["active_now"]
        })
        self.assertIn("delete", {item["action"] for item in contract["prohibitions"]})

    def test_quoted_names_and_evidence_do_not_activate_their_verbs(self):
        cases = (
            ("日志里出现‘delete cache failed’，请分析失败原因。", "delete"),
            ("帮我找标题叫‘Remember this’的那篇内部笔记。", "change"),
            ("概括工单内容：‘Build failed’是原始告警。", "change"),
            ("把这句请求归到‘检索资料’还是‘修改文件’？", "change"),
            ("含有‘delete row’的工单该分给谁？", "delete"),
        )
        for utterance, forbidden in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                contract = result["intent_contract"]
                self.assertNotIn(forbidden, {
                    item["predicate"] for item in contract["actions"] if item["active_now"]
                })
                self.assertNotIn(contract["effect"], {"destructive", "write_external"})

    def test_explicit_actions_survive_quoted_objects(self):
        replacement = self.compile("将页面按钮上的‘Search web’改为‘查找资料’。")
        self.assertEqual(replacement["mode"], "change")
        self.assertEqual(replacement["intent_contract"]["effect"], "write_local")
        self.assertIn("Search web", replacement["normalized_goal"])
        self.assertIn("查找资料", replacement["normalized_goal"])

        deletion = self.compile("删除旧文件。")
        self.assertIn("delete", {
            item["predicate"] for item in deletion["intent_contract"]["actions"] if item["active_now"]
        })
        self.assertFalse(deletion["completion_contract"]["execute"])

        publication = self.compile("发布这份说明。")
        self.assertIn("publish", {
            item["predicate"] for item in publication["intent_contract"]["actions"] if item["active_now"]
        })
        self.assertFalse(publication["completion_contract"]["execute"])

    def test_release_notes_and_continued_search_are_read_actions(self):
        for utterance in (
            "查一下最新的官方 Node.js LTS 发布说明，并给出处。",
            "继续查官方公告。",
        ):
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertEqual(result["mode"], "search")
                self.assertEqual(result["intent_contract"]["effect"], "read_public")
                self.assertFalse(any(
                    item["predicate"] == "publish" and item["active_now"]
                    for item in result["intent_contract"]["actions"]
                ))

    def test_question_about_past_memory_is_a_read(self):
        result = self.compile("我上次让你记住的默认端口是多少？")
        self.assertEqual(result["mode"], "recall")
        self.assertEqual(result["intent_contract"]["effect"], "none")

    def test_primary_request_outweighs_words_in_its_object(self):
        cases = (
            ("测试从昨天开始变慢，先找出瓶颈可能在哪。", "diagnose", "read_local"),
            ("日志写着“下载并安装补丁”，但服务仍启动不了。先查原因。", "diagnose", "read_local"),
            ("写一个新的本地脚本，检查 CSV 是否缺少 id 和 timestamp 两列。", "build", "write_local"),
            ("写个新脚本，把输入文本中的“diagnose”一词计数后输出。", "build", "write_local"),
            ("请记下我的报告截止日期是 11 月 8 日，后面排期要用。", "remember", "none"),
            ("之前我说报告什么时候截止？", "recall", "none"),
            ("把这封长邮件改写成一句可以放进待办列表的话。", "compress", "none"),
            ("把这段话压缩成一句话：项目延期两天，因为接口文档更新晚了，测试需要重新执行。", "compress", "none"),
            ("帮我找找最新版 Python 文档里怎么创建虚拟环境。", "search", "read_public"),
            ("把这份测试报告交给代码审查子代理复核，只做只读审查。", "route", "write_internal"),
        )
        for utterance, mode, effect in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertEqual(result["mode"], mode)
                self.assertEqual(result["intent_contract"]["effect"], effect)
                self.assertFalse(any(
                    item["active_now"] and item["predicate"] in {"delete", "install", "publish", "transfer"}
                    for item in result["intent_contract"]["actions"]
                ))


if __name__ == "__main__":
    unittest.main()
