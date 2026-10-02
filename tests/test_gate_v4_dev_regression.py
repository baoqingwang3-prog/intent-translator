"""Development regressions for the post-v3 hard gates.

These utterances are new development examples. They are not the frozen v3
blind set, and this module does not change that set, its scorer, or its thresholds.
"""

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


class GateV4DevRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intent-v4-dev-")
        root = Path(self.temporary.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "v4-dev",
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

    def compile(self, utterance, **kwargs):
        return self.compiler.compile(CompileRequest(
            utterance=utterance, semantic_mode="off", **kwargs
        ))

    @staticmethod
    def active(result):
        return {
            item["predicate"]
            for item in result["intent_contract"]["actions"]
            if item["active_now"]
        }

    @staticmethod
    def prohibited(result):
        return {item["action"] for item in result["intent_contract"]["prohibitions"]}

    def test_local_template_creation_keeps_create_predicate(self):
        result = self.compile("按列出的三列新建一个空白登记表。")
        self.assertEqual(result["mode"], "build")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("create", self.active(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_sensitive_online_sheet_is_not_executable_local_create(self):
        result = self.compile(
            "创建一份包含原始身份证号的在线共享表。",
            context="原始号码属于敏感信息，尚无外部上传确认凭证。",
            pending_action="在线共享。",
        )
        self.assertEqual(result["mode"], "build")
        self.assertEqual(result["intent_contract"]["effect"], "write_external")
        self.assertTrue({"create", "upload"} <= self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_named_internal_agent_dispatch_is_active(self):
        result = self.compile(
            "把本仓库的接口说明审校交给当前项目的文档子代理。",
            context="文档子代理已在本项目注册，材料路径已确定。",
        )
        self.assertEqual(result["mode"], "route")
        self.assertEqual(result["intent_contract"]["effect"], "write_internal")
        self.assertIn("route_internal_dispatch", self.active(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_readonly_internal_review_prohibits_change(self):
        result = self.compile("让内部核对代理只读看一遍这份名单。")
        self.assertIn("route_internal_dispatch", self.active(result))
        self.assertIn("change", self.prohibited(result))
        self.assertNotIn("change", self.active(result))

    def test_public_document_lookup_requests_network(self):
        result = self.compile("去官方文档检索当前版本的虚拟环境说明。")
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["intent_contract"]["effect"], "read_public")
        self.assertTrue({"search", "network_request"} <= self.active(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_howto_inside_a_lookup_is_not_creation(self):
        result = self.compile("查一下手册里如何新建一个说明页面。")
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["intent_contract"]["effect"], "read_public")
        self.assertNotIn("create", self.active(result))

    def test_download_folder_lookup_stays_local(self):
        result = self.compile("在下载目录找最新的成绩汇总 PDF。")
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["intent_contract"]["effect"], "read_local")
        self.assertIn("search", self.active(result))
        self.assertNotIn("network_request", self.active(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_two_named_files_require_clarification(self):
        result = self.compile(
            "把那个文件改一下。",
            context="上文同时提到 notes.md 和 plan.md，也没有说明改什么。",
        )
        self.assertTrue(result["clarification_required"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotIn("change", self.active(result))
        self.assertIn("target_artifact", result["intent_contract"]["required_slots"])

    def test_two_destinations_block_upload(self):
        result = self.compile(
            "帮我上传到云盘。",
            context="用户有两个目标云盘和两个同名报告，均未指明。",
            pending_action="上传报告。",
        )
        self.assertTrue(result["clarification_required"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertFalse(self.active(result))
        self.assertIn("destination", result["intent_contract"]["required_slots"])

    def test_stop_wording_withdraws_pending_delete(self):
        result = self.compile(
            "删除备份的操作停掉。",
            context="备份清理尚未开始。",
            pending_action="删除备份。",
        )
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotIn("delete", self.active(result))
        self.assertIn("delete", self.prohibited(result))

    def test_summary_of_a_change_log_does_not_edit(self):
        result = self.compile("把这段配置变更记录简要归纳：端口改为 8081，重试次数改为 4。")
        self.assertEqual(result["mode"], "compress")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertNotIn("change", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_future_preference_is_remembered(self):
        result = self.compile("以后聊到这门选修时，记得我手里是修订版教材。")
        self.assertEqual(result["mode"], "remember")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_named_project_agent_is_internal_route(self):
        result = self.compile(
            "请让当前仓库的审查代理看一遍这个补丁。",
            context="补丁已在本地，审查代理已注册。",
        )
        self.assertEqual(result["mode"], "route")
        self.assertIn("route_internal_dispatch", self.active(result))
        self.assertEqual(result["intent_contract"]["effect"], "write_internal")

    def test_existing_config_fix_is_a_local_change(self):
        result = self.compile("修正已有配置里重复的超时值。")
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_status_glance_stays_readonly(self):
        result = self.compile("只看当前分支的状态和差异，说明漏提交的原因。")
        self.assertEqual(result["mode"], "diagnose")
        self.assertEqual(result["intent_contract"]["effect"], "read_local")
        self.assertIn("change", self.prohibited(result))
        self.assertNotIn("change", self.active(result))

    def test_two_unnamed_objects_still_need_a_target(self):
        result = self.compile(
            "把它删了。",
            context="上文同时提到旧快照和旧日志，无法确定对象。",
            pending_action="删除本地材料。",
        )
        self.assertTrue(result["clarification_required"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])
        self.assertNotIn("delete", self.active(result))

    def test_revoked_pending_keeps_the_new_local_edit(self):
        result = self.compile(
            "先不要启动预览，只把现有配置里的间隔改成 15。",
            context="配置文件和键名都已经定位。",
            pending_action="启动预览。",
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))
        self.assertIn("start", self.prohibited(result))
        self.assertTrue(result["completion_contract"]["execute"])

    def test_edit_before_upload_veto_stays_local(self):
        result = self.compile(
            "把上一稿的本地说明改成脱敏版，但先别外发。",
            context="说明路径已确定。",
            pending_action="外发说明。",
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))
        self.assertFalse(result["clarification_required"])
        self.assertTrue(result["completion_contract"]["execute"])

    def test_spaced_numeric_alternatives_need_a_choice(self):
        result = self.compile(
            "把上限调成那个数。",
            context="候选上限写的是 30 和 80，还没选定。",
            pending_action="调整上限。",
        )
        self.assertTrue(result["clarification_required"])
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_named_new_checklist_is_not_an_unbound_pair(self):
        result = self.compile(
            "在当前仓库新建一份发布检查清单。",
            context="清单标题和输出目录都已确定。",
        )
        self.assertEqual(result["mode"], "build")
        self.assertIn("create", self.active(result))
        self.assertFalse(result["clarification_required"])
        self.assertTrue(result["completion_contract"]["execute"])

    def test_recent_decision_question_is_recall(self):
        result = self.compile("上回例会把试讲定在周几？")
        self.assertEqual(result["mode"], "recall")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_teaching_lookup_word_stays_learn(self):
        result = self.compile("教我用一张小卡片理解哈希查找的比较次数。")
        self.assertEqual(result["mode"], "learn")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertNotIn("search", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_workspace_lookup_stays_local_search(self):
        result = self.compile("从当前工作区搜出引用旧开关的模块。")
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["intent_contract"]["effect"], "read_local")
        self.assertIn("search", self.active(result))
        self.assertNotIn("network_request", self.active(result))

    def test_vendor_manual_lookup_requests_network(self):
        result = self.compile("上网查这个返回码在厂商官方手册里的含义。")
        self.assertEqual(result["mode"], "search")
        self.assertEqual(result["intent_contract"]["effect"], "read_public")
        self.assertTrue({"search", "network_request"} <= self.active(result))

    def test_reading_a_local_log_stays_diagnose(self):
        result = self.compile("对照两份本地运行日志，找出第一次超时出现在哪一行。")
        self.assertEqual(result["mode"], "diagnose")
        self.assertEqual(result["intent_contract"]["effect"], "read_local")
        self.assertIn("inspect", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_why_question_without_evidence_stays_answer(self):
        result = self.compile("为什么校验和通常不能还原出原文？")
        self.assertEqual(result["mode"], "answer")
        self.assertEqual(result["intent_contract"]["effect"], "none")

    def test_updating_an_existing_ignore_file_is_change(self):
        result = self.compile("更新项目现有的忽略规则，排除缓存目录。")
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "write_local")
        self.assertIn("change", self.active(result))

    def test_length_limited_notes_stay_compressed(self):
        result = self.compile("把这段访谈整理成不超过 40 字：主持人提问，嘉宾回答，下周三续谈。")
        self.assertEqual(result["mode"], "compress")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertFalse(result["completion_contract"]["execute"])

    def test_written_preference_is_executable_memory(self):
        result = self.compile("把我偏好短句这件事记下来。")
        self.assertEqual(result["mode"], "remember")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_duplicate_row_removal_binds_delete(self):
        result = self.compile(
            "从已有登记表里删掉重复行，每组只留第一条。",
            context="登记表已定位，但没有删除确认凭证。",
            pending_action="去重写回。",
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["effect"], "destructive")
        self.assertIn("delete", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])

    def test_past_publish_question_does_not_publish(self):
        result = self.compile(
            "我们以前是否同意公开发布这份草稿？",
            context="上文明确说等人工审核后再决定。",
            pending_action="公开发布草稿。",
        )
        self.assertEqual(result["mode"], "recall")
        self.assertEqual(result["intent_contract"]["effect"], "none")
        self.assertNotIn("publish", self.active(result))
        self.assertFalse(result["completion_contract"]["execute"])


if __name__ == "__main__":
    unittest.main()
