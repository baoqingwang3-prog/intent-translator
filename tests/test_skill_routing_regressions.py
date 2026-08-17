import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import semantic_payload  # noqa: E402


REGISTRY = {
    "skills": [
        {
            "name": "chapter-summary",
            "description": "整理考研数学或专业课章节笔记，生成结构化章节总结。",
        },
        {
            "name": "job-market-radar",
            "description": "搜索、标准化、比较并排名适合的职位和招聘机会。",
        },
        {
            "name": "kaoyan-english",
            "description": "考研英语入口路由器，用于英语阅读、词汇、写作与复习计划。",
        },
        {
            "name": "kaoyan-english-quiz",
            "description": "考研英语词汇测验和测试子模块。",
        },
        {
            "name": "agent-reach",
            "description": "搜索和调研互联网公开信息。",
        },
        {"name": "xlsx", "description": "编辑和生成 Excel xlsx 工作簿。"},
        {"name": "book-to-skill", "description": "将书籍、PDF、EPUB 或文档转换成 Skill。"},
        {"name": "code-review", "description": "审查 commit、branch、PR 或 diff 的代码改动。"},
        {"name": "skill-creator", "description": "创建和验证新的自定义 Skill。"},
        {"name": "study-assistant", "description": "学习、复习和考试任务协调器。"},
    ],
    "errors": [],
}


class SkillRoutingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.compiler = IntentCompiler(
            registry=REGISTRY,
            profile={
                "profile_id": "routing-regressions",
                "language": "zh-CN",
                "phrase_mappings": {},
                "memory": {"adapter": "none", "location": ""},
                "study": {"enabled": False},
            },
            profile_exists=True,
        )

    def compile_skill(self, utterance: str) -> str | None:
        result = self.compiler.compile(
            CompileRequest(utterance=utterance, semantic_mode="off")
        )
        return result["routing"]["primary_skill"]

    def test_general_task_summary_does_not_activate_chapter_summary(self):
        self.assertIsNone(
            self.compile_skill("总结一下主任务完成后都做了哪些事")
        )

    def test_audit_ledger_mention_does_not_activate_discussed_skill(self):
        self.assertIsNone(
            self.compile_skill(
                "把高风险 Skills 状态入账并更新审计总账，"
                "job-market-radar 来源仍未证明但因实际有用而保留"
            )
        )

    def test_meta_delegation_does_not_activate_study_router(self):
        self.assertIsNone(
            self.compile_skill("把路由器老乱路由的问题交给子任务")
        )

    def test_real_chapter_summary_still_uses_study_summary_skill(self):
        self.assertEqual(
            self.compile_skill("整理考研数学这一章"),
            "chapter-summary",
        )

    def test_real_job_search_uses_job_market_radar(self):
        self.assertEqual(
            self.compile_skill("帮我搜索并排名适合的职位"),
            "job-market-radar",
        )

    def test_real_kaoyan_english_request_uses_entry_router(self):
        self.assertEqual(
            self.compile_skill("考研英语阅读怎么复习"),
            "kaoyan-english",
        )

    def test_skill_source_audit_does_not_activate_discussed_skill(self):
        selected = self.compile_skill(
            "审计 job-market-radar Skill 的来源和版本，不要执行职位搜索"
        )
        self.assertNotEqual(selected, "job-market-radar")

    def test_confirmation_with_multi_selection_resumes_pending_action(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="可行，完成1和2",
                context="1) 审高风险执行型项目；2) 审纯文档型 Skill",
                pending_action="完成两阶段审计",
                semantic_mode="off",
            )
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["active_task_source"], "pending")
        self.assertIsNone(result["routing"]["primary_skill"])
        self.assertTrue(result["completion_contract"]["execute"])

    def test_confirmation_with_added_question_binds_pending_action(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="可以，然后告诉我所有skill是不是全部审查完了",
                pending_action="可恢复退役 word-template-generator",
                context="同时回答审计覆盖率",
                semantic_mode="off",
            )
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["active_task_source"], "pending")
        self.assertIn("word-template-generator", result["normalized_goal"])
        self.assertIn("全部审查完了", result["normalized_goal"])
        self.assertIsNone(result["routing"]["primary_skill"])

    def test_uuid_delegation_is_control_plane_work(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance=(
                    "把这次错误交给019ff547-de28-7b40-9239-d9cf22ec8414"
                    "让他的智能体看看是怎么回事"
                ),
                semantic_mode="off",
            )
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["operation"], "change")
        self.assertIsNone(result["routing"]["primary_skill"])
        self.assertTrue(result["completion_contract"]["execute"])

    def test_legacy_context_field_aliases_are_consumed(self):
        request = CompileRequest.model_validate(
            {
                "utterance": "可行，完成1和2",
                "recent_context": "两阶段审计",
                "last_proposed_action": "完成两阶段审计",
                "semantic_mode": "off",
            }
        )
        self.assertEqual(request.context, "两阶段审计")
        self.assertEqual(request.pending_action, "完成两阶段审计")

    def test_unknown_request_fields_fail_loudly(self):
        with self.assertRaises(ValidationError):
            CompileRequest.model_validate(
                {"utterance": "继续", "unknown_context_field": "silent-loss"}
            )

    def test_xlsx_local_edit_uses_file_capability_owner(self):
        self.assertEqual(
            self.compiler.compile(
                CompileRequest(
                    utterance="整理 inventory.xlsx 的库存列",
                    available_files=["inventory.xlsx"],
                    semantic_mode="off",
                )
            )["routing"]["primary_skill"],
            "xlsx",
        )

    def test_explicit_skill_invocation_overrides_reference_suppression(self):
        self.assertEqual(
            self.compile_skill("使用 job-market-radar Skill 执行职位搜索和排名"),
            "job-market-radar",
        )

    def test_explicit_child_skill_name_is_not_preempted_by_parent_prefix(self):
        registry = {
            "skills": [
                {"name": "ielts", "description": "IELTS entry router."},
                {"name": "ielts-reading", "description": "IELTS reading coach."},
                {"name": "bazi", "description": "Bazi analysis."},
                {"name": "bazi-career", "description": "Bazi career analysis."},
            ],
            "errors": [],
        }
        compiler = IntentCompiler(registry=registry, profile=self.compiler.profile, profile_exists=True)
        self.assertEqual(
            compiler.compile(
                CompileRequest(utterance="Use ielts-reading Skill", semantic_mode="off")
            )["routing"]["primary_skill"],
            "ielts-reading",
        )
        routed = compiler.compile(
            CompileRequest(utterance="Use ielts-reading Skill", semantic_mode="off")
        )["routing"]
        self.assertEqual(routed["primary_capability_role"]["role"], "specialist")
        self.assertEqual(routed["primary_capability_role"]["parent_skill"], "ielts")
        self.assertEqual(
            compiler.compile(
                CompileRequest(utterance="Use bazi-career Skill", semantic_mode="off")
            )["routing"]["primary_skill"],
            "bazi-career",
        )

    def test_real_book_conversion_uses_book_to_skill(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="把这本 EPUB 书转换成一个可用的 Skill",
                semantic_mode="off",
            )
        )
        self.assertEqual(result["mode"], "build")
        self.assertEqual(result["intent_contract"]["operation"], "create")
        self.assertEqual(result["routing"]["primary_skill"], "book-to-skill")
        self.assertTrue(result["completion_contract"]["execute"])

    def test_skill_maintenance_mention_does_not_activate_the_skill(self):
        self.assertIsNone(
            self.compile_skill("检查并修复 job-market-radar Skill 本身的路由问题")
        )

    def test_skill_source_audit_is_not_reactivated_by_study_profile(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研"],
                "routing": [
                    {
                        "subject": "career",
                        "terms": ["career"],
                        "preferred_skills": ["career-ops"],
                    }
                ],
            },
        }
        registry = {
            "skills": [
                {"name": "career-ops", "description": "Career operations router."},
            ],
            "errors": [],
        }
        compiler = IntentCompiler(registry=registry, profile=profile, profile_exists=True)
        for utterance in (
            "Audit the source and version of career-ops Skill; do not invoke it",
            "检查并修复 career-ops Skill 本身的路由问题",
            "把 career-ops 的状态记入退役台账，但不要调用",
        ):
            result = compiler.compile(CompileRequest(utterance=utterance, semantic_mode="off"))
            self.assertFalse(result["study_context"]["enabled"])
            self.assertIsNone(result["routing"]["primary_skill"])

    def test_user_invoked_skill_is_not_auto_selected(self):
        registry = {
            "skills": [
                {
                    "name": "manual-helper",
                    "description": "Analyze reports and generate summaries.",
                    "model_invoked": False,
                }
            ],
            "errors": [],
        }
        compiler = IntentCompiler(registry=registry, profile=self.compiler.profile, profile_exists=True)
        automatic = compiler.compile(
            CompileRequest(utterance="Analyze this report and generate a summary", semantic_mode="off")
        )
        explicit = compiler.compile(
            CompileRequest(utterance="Use manual-helper Skill to analyze this report", semantic_mode="off")
        )
        self.assertIsNone(automatic["routing"]["primary_skill"])
        self.assertEqual(explicit["routing"]["primary_skill"], "manual-helper")

    def test_semantic_payload_uses_relevant_tail_skill_not_alphabetic_first_80(self):
        skills = [
            {"name": f"skill-{index:03d}", "description": "generic capability"}
            for index in range(100)
        ]
        tail = {"name": "zz-tail-skill", "description": "the relevant late-sorted capability"}
        skills.append(tail)
        payload = semantic_payload(
            utterance="use the tail capability",
            context="",
            pending_action="",
            deterministic={},
            skills=skills,
            relevant_skills=[tail],
        )
        names = [item["name"] for item in payload["installed_skills"]]
        self.assertIn("zz-tail-skill", names)

    def test_normal_domain_task_with_task_word_is_not_control_plane(self):
        self.assertEqual(
            self.compile_skill("用 job-market-radar 处理职位搜索任务并排名"),
            "job-market-radar",
        )

    def test_pending_control_plane_action_is_not_overridden_by_recent_auto_review_context(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研", "雅思"],
                "active_goal": "考研",
                "active_subject": "general-study",
                "routing": [
                    {
                        "subject": "general-study",
                        "terms": ["复习", "测试我", "quiz", "review"],
                        "preferred_skills": ["study-assistant"],
                    }
                ],
            },
        }
        compiler = IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)
        result = compiler.compile(
            CompileRequest(
                utterance="继续",
                context=(
                    "intent-translator MCP 已注册；CC Switch 的 "
                    "codex-auto-review 503 已修复"
                ),
                pending_action=(
                    "完成最终闭环验收：核对注册结果与 MCP 列表，"
                    "在线复测关键正反路由案例，并确认自动审批修复持续稳定。"
                ),
                semantic_mode="off",
            )
        )
        self.assertEqual(result["mode"], "change")
        self.assertEqual(result["intent_contract"]["active_task_source"], "pending")
        self.assertFalse(result["study_context"]["enabled"])
        self.assertIsNone(result["routing"]["primary_skill"])

    def test_explicit_pending_study_action_still_uses_study_profile_owner(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研"],
                "active_goal": "考研",
                "active_subject": "general-study",
                "routing": [
                    {
                        "subject": "general-study",
                        "terms": ["复习", "review"],
                        "preferred_skills": ["study-assistant"],
                    }
                ],
            },
        }
        compiler = IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)
        result = compiler.compile(
            CompileRequest(
                utterance="继续",
                context="刚刚讨论过技术 review，也讨论过今天的学习安排",
                pending_action="继续复习考研数学并检查学习进度",
                semantic_mode="off",
            )
        )
        self.assertTrue(result["study_context"]["enabled"])
        self.assertEqual(result["routing"]["primary_skill"], "study-assistant")

    def test_generic_code_review_word_does_not_activate_study_owner(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研", "雅思"],
                "active_goal": "考研",
                "routing": [
                    {
                        "subject": "general-study",
                        "terms": ["复习", "quiz", "review"],
                        "preferred_skills": ["study-assistant"],
                    }
                ],
            },
        }
        compiler = IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)
        result = compiler.compile(
            CompileRequest(utterance="review 这个 pull request 的改动", semantic_mode="off")
        )
        self.assertFalse(result["study_context"]["enabled"])
        self.assertEqual(result["routing"]["primary_skill"], "code-review")
        self.assertNotIn(
            "local-study-profile",
            [
                term
                for candidate in result["routing"].get("candidates", [])
                for term in candidate.get("matched_terms", [])
            ],
        )

    def test_earlier_study_context_does_not_override_current_technical_pending_action(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["考研"],
                "active_goal": "考研",
                "routing": [
                    {
                        "subject": "general-study",
                        "terms": ["复习", "review"],
                        "preferred_skills": ["study-assistant"],
                    }
                ],
            },
        }
        compiler = IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)
        result = compiler.compile(
            CompileRequest(
                utterance="继续",
                context="更早在讨论考研复习，现在已切换到 Codex 修复",
                pending_action="review 自动审批映射的技术验收证据",
                semantic_mode="off",
            )
        )
        self.assertEqual(result["intent_contract"]["active_task_source"], "pending")
        self.assertFalse(result["study_context"]["enabled"])
        self.assertIsNone(result["routing"]["primary_skill"])

    def test_review_with_explicit_ielts_object_remains_study_relevant(self):
        profile = {
            "profile_id": "routing-regressions-study-enabled",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {
                "enabled": True,
                "goals": ["雅思"],
                "active_goal": "雅思",
                "routing": [
                    {
                        "subject": "english",
                        "terms": ["ielts", "雅思", "essay", "写作"],
                        "preferred_skills": ["study-assistant"],
                    },
                    {
                        "subject": "general-study",
                        "terms": ["review"],
                        "preferred_skills": ["study-assistant"],
                    },
                ],
            },
        }
        compiler = IntentCompiler(registry=REGISTRY, profile=profile, profile_exists=True)
        result = compiler.compile(
            CompileRequest(utterance="review my IELTS essay", semantic_mode="off")
        )
        self.assertTrue(result["study_context"]["enabled"])
        self.assertEqual(result["routing"]["primary_skill"], "study-assistant")

    def test_orchestration_prefers_bounded_parallel_subagents_without_expanding_authority(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="把能独立分工的部分交给子任务并行，主任务最后验收",
                semantic_mode="off",
            )
        )
        orchestration = result["orchestration"]
        self.assertEqual(
            orchestration["delegation_preference"],
            "parallel-subagents-when-independent",
        )
        self.assertEqual(
            orchestration["visible_task_policy"],
            "explicit-user-request-only",
        )
        self.assertTrue(orchestration["delegation_does_not_expand_authorization"])
        self.assertIn("final-acceptance", orchestration["main_task_retains"])


if __name__ == "__main__":
    unittest.main()
