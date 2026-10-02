"""Contrast current actions with object words and destinations that resemble other actions."""

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


class ActionEffectContrastTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="intent-effects-v3-")
        root = Path(self.temporary.name)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "effects-v3",
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

    def compile(self, utterance, *, context=""):
        return self.compiler.compile(CompileRequest(utterance=utterance, context=context, semantic_mode="off"))

    def assert_action(self, utterance, mode, effect, *, operation=None, predicate=None, context=""):
        result = self.compile(utterance, context=context)
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], mode, msg=utterance)
        self.assertEqual(contract["effect"], effect, msg=utterance)
        if operation is not None:
            self.assertEqual(contract["operation"], operation, msg=utterance)
        active = {item["predicate"] for item in contract["actions"] if item["active_now"]}
        if predicate is not None:
            self.assertIn(predicate, active, msg=utterance)
        if effect != "write_external":
            self.assertNotIn("external", contract["required_grants"], msg=utterance)
        return result

    def test_local_display_and_publication_are_distinct(self):
        self.assert_action("做一个本地状态页，页面里显示队列长度。", "build", "write_local", operation="create")
        self.assert_action("把这个状态页发布到公网。", "build", "write_external", operation="publish", predicate="publish")

    def test_looking_up_a_publication_page_does_not_publish(self):
        self.assert_action("检索政府公告的发布页面，只要链接。", "search", "read_public", operation="search")
        self.assert_action("把这份公告发布到官网。", "build", "write_external", operation="publish", predicate="publish")

    def test_test_coverage_does_not_overwrite_a_file(self):
        self.assert_action("编写测试，覆盖空数组和非空数组。", "build", "write_local", operation="create")
        self.assert_action("覆盖现有settings.toml的内容。", "change", "destructive")

    def test_copying_locally_does_not_egress(self):
        self.assert_action("将报告复制到本地归档目录。", "change", "write_local", operation="change")
        self.assert_action("把分析结果发送到客户邮箱。", "change", "write_external", operation="transfer", predicate="transfer")

    def test_local_output_does_not_egress_but_external_secret_does(self):
        self.assert_action("读取本地日志并在终端输出摘要。", "diagnose", "read_local", operation="diagnose")
        external = self.assert_action("输出密钥到外部工单。", "change", "write_external", operation="transfer")
        active_grants = {
            grant
            for item in external["intent_contract"]["actions"] if item["active_now"]
            for grant in item["required_grants"]
        }
        self.assertIn("sensitive", active_grants)
        self.assertFalse(external["completion_contract"]["execute"])

    def test_internal_delegate_and_external_delivery_are_distinct(self):
        self.assert_action("把分析结果交给内部审阅代理处理。", "route", "write_internal")
        self.assert_action("让内部视觉代理审核这份图。", "route", "write_internal")
        self.assert_action("把分析结果发送到客户邮箱。", "change", "write_external", operation="transfer")

    def test_subsequent_publication_keeps_external_effect(self):
        self.assert_action("先创建一个本地页面，再将它发布到公网。", "build", "write_external", operation="publish", predicate="publish")

    def test_preference_text_does_not_become_an_output_action(self):
        self.assert_action("把我的偏好记为：输出使用纯文本。", "remember", "none", operation="answer")

    def test_fault_diagnosis_and_explicit_configuration_edit(self):
        self.assert_action(
            "只读比对 bot_worker.log 与 backlog.csv，找出队列从午后开始积压的原因。",
            "diagnose", "none", operation="diagnose",
        )
        self.assert_action("队列积压了，把现有 worker.yaml 的并发上限改为 16。", "change", "write_local")

    def test_new_named_document_and_existing_document_edit(self):
        self.assert_action("从空白起草 ops_calendar.md，列出轮值日期和联系人占位。", "build", "write_local", operation="create")
        self.assert_action("在已有 ops_calendar.md 里更新联系人。", "change", "write_local")

    def test_delegation_request_and_quoted_delegation_text(self):
        self.assert_action("请让内部 GIS QA 角色接手投影精度复核，完成后把结果交回主任务。", "route", "write_internal")
        self.assert_action("文档中写着“让 GIS QA 接手投影精度复核”，请解释这句安排。", "answer", "none")

    def test_recall_prior_decision_and_general_knowledge_question(self):
        self.assert_action(
            "你能复述我上一轮约定的图表配色顺序吗？", "recall", "none",
            context="上一轮用户确定图表配色顺序为蓝色、橙色、绿色。",
        )
        self.assert_action("图表配色顺序一般怎么定？", "answer", "none")

    def test_direct_fact_answer_and_public_document_lookup(self):
        self.assert_action("列出 TCP 三次握手各阶段的名称，直接回答。", "answer", "none")
        self.assert_action("搜索 IETF 官方文档里的握手字段定义并附链接。", "search", "read_public", operation="search")

    def test_summarizing_text_and_teaching_summarization(self):
        self.assert_action("把下面的日志事件记录浓缩为一句值班简报，不发送。", "compress", "none")
        self.assert_action("把日志事件记录浓缩成一句的技巧教我，先让我试做。", "learn", "none")


if __name__ == "__main__":
    unittest.main()
