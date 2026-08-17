import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest, CurrentGoalLock  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "kaoyan-english", "description": "考研英语学习入口。"},
        {"name": "obsidian-cli", "description": "管理本地 Obsidian 笔记。"},
        {"name": "intent-translator", "description": "编译意图并维护路由规则。"},
    ],
    "errors": [],
}

PROFILE = {
    "profile_id": "goal-lock-regression",
    "language": "zh-CN",
    "phrase_mappings": {},
    "memory": {"adapter": "none", "location": ""},
    "student_state": {"enabled": False},
    "study": {
        "enabled": True,
        "goals": ["考研", "雅思"],
        "active_goal": "考研",
        "routing": [
            {
                "subject": "english",
                "terms": ["雅思", "英语", "阅读"],
                "preferred_skills": ["kaoyan-english"],
            }
        ],
    },
}

LOCK = CurrentGoalLock(
    current_goal="完成 IELTS Hermes→Codex→Obsidian 端到端验收",
    completion_gate=[
        "真实 Hermes agent 轮次",
        "真实 Codex session/PID",
        "目标文件存在",
        "Obsidian CLI read 成功",
    ],
    owner="codex-session-81601",
    allowed_actions=["poll-owner", "verify-session", "verify-pid", "verify-artifact", "obsidian-read"],
    dedupe_key="ielts-hermes-codex-obsidian-e2e",
)


class GoalLockSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.compiler = IntentCompiler(registry=REGISTRY, profile=PROFILE, profile_exists=True)

    def compile(self, utterance: str):
        return self.compiler.compile(
            CompileRequest(
                utterance=utterance,
                semantic_mode="off",
                current_goal_lock=LOCK,
            )
        )

    def assert_queued(self, utterance: str):
        result = self.compile(utterance)
        self.assertEqual(result["scheduling"]["decision"], "queued")
        self.assertFalse(result["scheduling"]["execute"])
        self.assertFalse(result["scheduling"]["handoff"])
        self.assertFalse(result["scheduling"]["announce"])
        self.assertFalse(result["completion_contract"]["execute"])

    def assert_not_current_goal(self, utterance: str):
        result = self.compile(utterance)
        self.assertEqual(result["scheduling"]["decision"], "queued")
        self.assertFalse(
            result["scheduling"]["current_goal_action"],
            msg=f"mere mention was treated as the active goal: {utterance}",
        )

    def test_memory_and_correction_are_queued_before_p0_pass(self):
        self.assert_queued("顺便让 intent 记住这种会话并持久化 correction")

    def test_research_return_is_queued_before_p0_pass(self):
        self.assert_queued("Obsidian 官方研究回流完成，立即转交结果")

    def test_side_route_completion_notice_is_queued_before_p0_pass(self):
        self.assert_queued("后台 OpenWork 修复完成，播报完成通知")
        self.assert_queued("background OpenWork task completed; announce the result")

    def test_generic_words_and_p1_masquerades_do_not_match_current_goal(self):
        cases = (
            "OpenWork 完成了另一条 IELTS 研究，播报结果",
            "后台 Hermes 规则研究完成，立即转交 correction",
            "旁路 Codex 调研结束，更新 memory",
            "Obsidian 插件研究回流完成，整理规则",
            "研究报告标题：IELTS 验收完成情况",
            "OpenWork: Hermes agent 调研完成通知",
            "background Obsidian CLI read research finished; announce",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_current_goal(utterance)

    def test_mentions_negation_history_quotes_and_titles_are_not_asserted_actions(self):
        cases = (
            "不要执行 IELTS Hermes Codex Obsidian 端到端验收",
            '引用原话："继续核验 Hermes agent 轮次和 Codex session PID"',
            "历史记录显示昨天完成了 IELTS Hermes 到 Obsidian 验收",
            "报告标题：《真实 Codex session/PID 核验》",
            "这不是当前 IELTS 端到端验收动作，只是复盘",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_current_goal(utterance)

    def test_owner_dedupe_path_and_object_mismatch_do_not_match_current_goal(self):
        cases = (
            "轮询 owner=codex-session-99999 的 IELTS 项目",
            "核验 dedupe_key=ielts-hermes-codex-obsidian-e2e-copy 的 session PID",
            r"读取 D:\other-vault\IELTS.md 的 Obsidian 文件",
            r"核验同名项目 path=D:\archive\ielts owner=codex-session-00001 的产物",
            "查看另一个会话 codex-session-22222 的进度",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_current_goal(utterance)

    def test_mixed_p1_object_does_not_inherit_current_goal_identity(self):
        cases = (
            "完成当前规则研究，并把 OpenWork correction 交给 codex-session-99999",
            "IELTS 验收先别动；完成后台 Hermes 规则研究",
            "对当前目标做历史报告，同时播报旁路 Obsidian 研究完成",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_current_goal(utterance)

    def test_lock_exposes_required_control_fields_and_takeover_gate(self):
        scheduling = self.compile("核验现有 session PID 和产物")["scheduling"]
        self.assertEqual(scheduling["decision"], "execute")
        self.assertTrue(scheduling["current_goal_action"])
        self.assertEqual(
            set(scheduling["current_goal_lock"]),
            {"current_goal", "completion_gate", "owner", "allowed_actions", "dedupe_key", "status"},
        )
        self.assertEqual(scheduling["takeover_requires"], ["command", "session", "pid", "artifact"])
        self.assertTrue(scheduling["single_active_owner_per_dedupe_key"])

    def test_explicit_cancel_can_preempt_the_lock(self):
        result = self.compile("取消当前目标，改为处理安全事件")
        self.assertEqual(result["scheduling"]["decision"], "execute")
        self.assertIn("explicit-user-cancel-or-replace", result["scheduling"]["allowed_preemption"])

    def test_unrelated_foreground_work_is_also_queued(self):
        self.assert_queued("现在顺便安装另一个应用")

    def test_current_goal_completion_checks_continue_to_execute(self):
        for utterance in (
            "继续核验 Hermes agent 轮次和 Codex session PID",
            "目标文件存在，执行 Obsidian CLI read",
            "对 dedupe_key=ielts-hermes-codex-obsidian-e2e 继续核验 Codex session PID",
            "owner=codex-session-81601：轮询 Hermes agent 轮次",
        ):
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertEqual(result["scheduling"]["decision"], "execute")
                self.assertTrue(result["scheduling"]["current_goal_action"])

    def test_safety_or_required_authorization_can_preempt(self):
        for utterance in ("发生安全事件，需要立即处置", "当前步骤需要授权才能继续"):
            with self.subTest(utterance=utterance):
                self.assertEqual(self.compile(utterance)["scheduling"]["decision"], "execute")

    def test_control_plane_request_does_not_inherit_study_route(self):
        result = self.compile("审计 Codex 调度并修复 CURRENT_GOAL_LOCK，不是学习任务")
        self.assertFalse(result["study_context"]["enabled"])
        self.assertNotEqual(result["routing"]["primary_skill"], "kaoyan-english")
        self.assertNotEqual(result["routing"]["primary_skill"], "obsidian-cli")


if __name__ == "__main__":
    unittest.main()
