"""Regression checks for model preprocessing and trustworthy comparison metrics."""
import contextlib
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ilang_distill_router as router
import ilang_semantic_main as semantic_main
import ilang_compare_eval as evaluation
import ilang_step3_acceptance as acceptance


class IlangEvaluationTests(unittest.TestCase):
    def test_provenance_does_not_export_local_paths(self):
        versions = {name: "fixture-version" for name in
                    ("fastembed", "onnxruntime", "pydantic", "huggingface-hub")}
        with patch.dict(os.environ, {"ILANG_DISTILL_MODEL_PATH":
                                  str(Path.home() / "private-model")}), \
             patch.object(evaluation.importlib.metadata, "version", side_effect=versions.__getitem__):
            meta = evaluation.provenance()
        self.assertEqual(meta["packages"], versions)
        self.assertNotIn("executable", meta)
        self.assertNotIn("core_import", meta)
        self.assertNotIn("model_path", meta)
        self.assertTrue(meta["model_path_set"])
        self.assertFalse(Path(meta["core_import_ref"]).is_absolute())

    def test_ilang_requires_a_complete_expression(self):
        self.assertTrue(semantic_main.has_ilang_syntax("[DEL:@LOCAL]"))
        self.assertTrue(semantic_main.has_ilang_syntax("[SCAN:@GH]=>[OUT]"))
        for utterance in (
            "帮我看看 [DEL:@LOCAL] 这条语句写的对不对",
            "请解释 `[DEL:@LOCAL]` 的含义",
            "帮我看看这个 ilang 语句 [SCAN:@GH]=>[OUT] 语法有错吗",
            "[TODO]", "[PDF]", "[ERROR]",
        ):
            with self.subTest(utterance=utterance):
                self.assertFalse(semantic_main.has_ilang_syntax(utterance))

    def test_continuation_and_correction_use_pending_action(self):
        self.assertEqual(semantic_main.cascade_mode(
            "接着来", "上次正在写一个爬虫脚本", "完成价格监控爬虫")[:2],
            ("build", "continuation"))
        self.assertEqual(semantic_main.cascade_mode(
            "换成 gs", "上一轮讨论包管理器", "把依赖管理切换到 pnpm")[:2],
            ("change", "correction"))
        self.assertEqual(semantic_main.cascade_mode(
            "改为搜索官方文档", "", "创建一个爬虫脚本")[:2],
            ("search", "correction"))
        self.assertEqual(semantic_main.cascade_mode(
            "改为不要发布", "", "发布仓库到 GitHub")[:2],
            (None, "correction-unresolved"))
        self.assertEqual(semantic_main.cascade_mode("可以", "", "")[:2],
                         (None, "continuation-unresolved"))
        self.assertEqual(semantic_main.cascade_mode("先这样", "", "发布仓库到 GitHub")[:2],
                         (None, "continuation-unresolved"))
        self.assertFalse(semantic_main._is_meaningless("改代码"))
        self.assertFalse(semantic_main._is_meaningless("查资料"))
        self.assertTrue(semantic_main._is_meaningless("asdfjkl"))

    def test_external_pending_action_requires_review(self):
        proposal = semantic_main.cascade_proposal({
            "utterance": "可以", "pending_action": "发布仓库到 GitHub"})
        self.assertEqual(proposal["mode"], "build")
        self.assertTrue(proposal["clarification_recommended"])
        self.assertIn("external", proposal["risk_hints"])
        correction = semantic_main.cascade_proposal({
            "utterance": "换成 GitLab", "pending_action": "发布仓库到 GitHub"})
        self.assertEqual(correction["mode"], "build")
        self.assertTrue(correction["clarification_recommended"])
        self.assertIn("external", correction["risk_hints"])

    def test_punctuated_control_turns_do_not_guess_or_revive_cancelled_actions(self):
        self.assertEqual(
            semantic_main.cascade_mode("继续。", "没有未完成的下一步。", "")[:2],
            (None, "continuation-unresolved"),
        )
        self.assertEqual(
            semantic_main.cascade_mode("继续。", "", "修改 README 标题")[:2],
            ("change", "continuation"),
        )
        for utterance, pending in (
            ("先别上传那份文件了。", "上传指定文件"),
            ("不用买许可证，取消这一步。", "购买许可证"),
            ("那个目录别删，刚才的删除计划取消。", "删除指定目录"),
        ):
            with self.subTest(utterance=utterance):
                proposal = semantic_main.cascade_proposal({
                    "utterance": utterance, "pending_action": pending,
                })
                self.assertIsNone(proposal["mode"])
                self.assertEqual(proposal["control_status"], "revoke")
                self.assertFalse(proposal["clarification_recommended"])
                self.assertIn("refusal", proposal["interpretation"].lower())

    def test_unbound_references_and_teaching_continuation(self):
        for utterance in ("把它改好。", "就按刚才那个方案办。"):
            with self.subTest(utterance=utterance):
                proposal = semantic_main.cascade_proposal({"utterance": utterance})
                self.assertIsNone(proposal["mode"])
                self.assertTrue(proposal["clarification_recommended"])
        self.assertEqual(
            semantic_main.cascade_mode("往下讲吧。", "", "用一道例题演示链式法则")[:2],
            ("learn", "continuation"),
        )
        self.assertEqual(
            semantic_main.cascade_mode("接着讲上一题的第二步。", "", "讲解该题第二步")[:2],
            ("learn", "continuation"),
        )
        self.assertEqual(
            semantic_main.cascade_mode("好，就按刚才说的改。", "", "将首页标题改为项目概览")[:2],
            ("change", "continuation"),
        )

    def test_clear_primary_verbs_ignore_quoted_content(self):
        cases = (
            ("什么是幂等性？给个简单例子。", "answer"),
            ("日志出现“安装更新”，请分析失败原因。", "diagnose"),
            ("把按钮“Search web”改为“查找”。", "change"),
            ("新建一份团队交接模板。", "build"),
            ("在项目里找出 retry_limit 的定义文件。", "search"),
            ("请教我判断串联与并联，再让我练习。", "learn"),
            ("把“先给结论”记作我的固定偏好。", "remember"),
            ("上次约定的报告格式是什么？", "recall"),
            ("把这句话压缩成十个字：“搜索并删除文件”。", "compress"),
            ("请把工单分给数据组还是前端组？", "route"),
        )
        for utterance, expected in cases:
            with self.subTest(utterance=utterance):
                mode, decider, _ = semantic_main.cascade_mode(utterance)
                self.assertEqual((mode, decider), (expected, "clear-primary"))

    def test_explicit_primary_action_is_not_overridden_by_a_ban(self):
        cases = (
            ("搜索官方资料，但不要上传本地文件", "search"),
            ("总结这篇文章，别转发给任何人", "compress"),
            ("分析这份报错日志，先别修改配置", "diagnose"),
            ("帮我想想一个标题，不要编辑正文", "answer"),
        )
        for utterance, expected in cases:
            with self.subTest(utterance=utterance):
                proposal = semantic_main.cascade_proposal({"utterance": utterance})
                self.assertEqual(proposal["mode"], expected)
                self.assertTrue(proposal["clarification_recommended"])
                self.assertEqual(proposal["normalized_goal"], utterance)
        self.assertIsNone(semantic_main._constrained_primary_mode(
            "搜索并总结资料，但别发到群里"))

    def test_explicit_primary_modes_and_counterexamples(self):
        cases = (
            ("帮我搭个小程序", "build"),
            ("把配置里的重试次数调小一点", "change"),
            ("为什么服务反复超时", "diagnose"),
            ("教我怎么读这段代码", "learn"),
            ("规划一下先测哪个接口", "route"),
            ("帮我把用户故事转成开发任务清单", "route"),
            ("讲讲这个报错怎么回事", "diagnose"),
            ("我上次记的接口端口是多少", "recall"),
            ("搜搜这款设备的评测", "search"),
            ("把这段文字精简到三十字", "compress"),
            ("把这篇长文浓缩成一段话", "compress"),
            ("把表单里的姓名字段填好", "change"),
            ("以后回答都用表格", "remember"),
            ("帮我写个搜索评测的爬虫", "build"),
            ("帮我规划一下之前存的待办执行顺序", "route"),
            ("把上次会议纪要浓缩成三句话", "compress"),
            ("写个脚本处理收不到验证码的情况", "build"),
            ("这个命令是干嘛使的", "answer"),
            ("这条 SQL 是查什么的", "answer"),
            ("帮我给文档里的 TODO 项列个清单", "answer"),
            ("这些卡片还有几个没完", "answer"),
        )
        for utterance, expected in cases:
            with self.subTest(utterance=utterance):
                self.assertEqual(semantic_main._explicit_primary_mode(utterance), expected)
        for utterance in (
            "不要帮我写脚本", "先不要卸载包", "动态规划题怎么做",
            "帮我写个工具，然后发布到 GitHub",
            "帮我写个脚本，教我怎么运行",
            "查一查这条命令的官方文档怎么说",
            "把这份需求拆成任务清单",
            "把日志里的 ERROR 行抓出来",
            "请给这个类写一个方法列表",
        ):
            with self.subTest(utterance=utterance):
                self.assertIsNone(semantic_main._explicit_primary_mode(utterance))

    def test_acceptance_does_not_pass_wrong_mode_or_unrecognized_noise(self):
        proposal = {
            "normalized_goal": "example", "interpretation": "ordinary text",
            "mode": "change", "assumptions": [], "alternatives": [],
            "confidence": 0.5, "primary_skill": None, "risk_hints": [],
            "clarification_recommended": True, "language": "zh",
        }
        self.assertTrue(acceptance.check_case(
            {"utterance": "[TODO]", "expected_mode": "answer", "constraint": "plain-bracket"}, proposal))
        self.assertTrue(acceptance.check_case(
            {"utterance": "asdfjkl", "expected_mode": None, "constraint": "invalid"}, proposal))
        self.assertTrue(acceptance.check_case(
            {"utterance": "不要", "expected_mode": None, "constraint": "continuation-refusal"}, proposal))
        self.assertFalse(acceptance.check_case(
            {"utterance": "有效修改", "expected_mode": "change"}, proposal))
        quoted = dict(proposal, mode="answer", interpretation="[ilang] parsed")
        self.assertTrue(acceptance.check_case(
            {"utterance": "讨论 [DEL:@LOCAL]", "expected_mode": "answer", "constraint": "quoted-ilang"}, quoted))

    def test_e5_prefix_applies_to_queries_and_anchors(self):
        encoder = Mock(model_name="intfloat/multilingual-e5-large")
        encoder.embed.return_value = [[1.0, 0.0]]
        with patch.object(router, "_load_encoder", return_value=encoder):
            router._embed(["修复这个问题"])
            encoder.embed.assert_called_with(["query: 修复这个问题"], batch_size=1)
            router.build_centroids({"modes": {"change": {"utterances": ["修改文件"]}}})
            encoder.embed.assert_called_with(["query: 修改文件"], batch_size=1)

    def test_bge_inputs_remain_unprefixed(self):
        encoder = Mock(model_name="BAAI/bge-small-zh-v1.5")
        encoder.embed.return_value = [[1.0, 0.0]]
        with patch.object(router, "_load_encoder", return_value=encoder):
            router._embed(["修复这个问题"])
        encoder.embed.assert_called_once_with(["修复这个问题"])

    def test_offline_load_uses_explicit_snapshot_and_one_thread(self):
        constructor = Mock()
        module = types.SimpleNamespace(TextEmbedding=constructor)
        with patch.dict(sys.modules, {"fastembed": module}), \
             patch.dict(router._MODEL_CACHE, {}, clear=True), \
             patch.dict(os.environ, {"ILANG_DISTILL_MODEL_PATH": "snapshot",
                                     "ILANG_DISTILL_OFFLINE": "1",
                                     "ILANG_DISTILL_EMBED_MODEL": "intfloat/multilingual-e5-large"}):
            router._load_encoder()
        constructor.assert_called_once_with(
            model_name="intfloat/multilingual-e5-large", threads=1,
            specific_model_path="snapshot", local_files_only=True,
        )

    def test_accuracy_counts_abstentions_in_denominator(self):
        rows = [{"expected_mode": "change", "predictions": {"embed": mode}}
                for mode in ("change", None)]
        result = evaluation.metrics(rows, "embed")
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["selective_accuracy"], 1.0)
        self.assertEqual(result["coverage"], 0.5)

    def test_main_restores_environment_after_failure(self):
        key = "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON"
        with patch.dict(os.environ, {key: "original"}), \
             patch.object(evaluation, "_run", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                evaluation.main()
            self.assertEqual(os.environ[key], "original")

    def test_views_keep_historical_rows_and_remove_exact_overlaps(self):
        def row(text, overlap):
            return {"utterance": text, "anchor_overlap": overlap, "source": "fresh",
                    "expected_mode": "change",
                    "predictions": {name: "change" for name in evaluation.ROUTERS}}
        result = evaluation.views([row("one", True), row("one", True), row("two", False)])
        self.assertEqual(result["all"]["cascade"]["total"], 3)
        self.assertEqual(result["unique"]["cascade"]["total"], 2)
        self.assertEqual(result["unique_without_anchor_overlap"]["cascade"]["total"], 1)

    def test_actual_cascade_arbitration(self):
        cases = [
            ("change", 0.9, "change", "change", "agree"),
            ("answer", 0.5, "change", "change", "embed-rescue"),
            ("diagnose", 0.9, "change", "diagnose", "kw-prior"),
            ("answer", 0.8, "change", "answer", "kw-prior"),
            ("diagnose", 0.9, None, "diagnose", "kw-only"),
            (None, 0.0, "change", "change", "embed-only"),
            (None, 0.0, None, None, "none"),
        ]
        for kmode, kconf, emode, expected, decider in cases:
            with self.subTest(decider=decider), \
                 patch.object(semantic_main, "_keyword_compile", return_value={"mode": kmode, "confidence": kconf}), \
                 patch.object(semantic_main, "_embed_route", return_value={"mode": emode, "confidence": 0.7, "raw_score": 0.7}):
                mode, actual_decider, _ = semantic_main.cascade_mode("example")
                self.assertEqual((mode, actual_decider), (expected, decider))

    def test_evaluator_calls_production_cascade(self):
        case = {"utterance": "example", "expected_mode": "diagnose", "source": "fixture"}
        compiler = Mock()
        compiler.compile.return_value = {"mode": "answer", "confidence": 0.8}
        with patch.object(evaluation, "load_eval", return_value=[case]), \
             patch.object(evaluation, "provenance", return_value={"model": "fake", "python": "test", "offline": True, "scoring": "maxsim"}), \
             patch.object(evaluation.core, "IntentCompiler", return_value=compiler), \
             patch.object(router, "get_utterance_vecs"), \
             patch.object(router, "route", return_value={"mode": "change", "scores": {"change": 0.9}}), \
             patch.object(semantic_main, "cascade_mode", return_value=("diagnose", "kw-prior", 0.9)) as cascade, \
             patch.object(semantic_main, "_KW_COMPILER", None, create=True), \
             patch.object(sys, "argv", ["ilang_compare_eval.py"]), \
             contextlib.redirect_stdout(io.StringIO()):
            evaluation.main()
        cascade.assert_called_once_with("example")


if __name__ == "__main__":
    unittest.main()
