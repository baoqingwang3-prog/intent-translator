import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


CONTROL_PLANE_SKILLS = {
    "intent-translator",
    "skill-creator",
    "skill-installer",
    "skill-lookup",
    "skill-refactor",
}

MANAGED_DOMAIN_SKILLS = (
    "job-market-radar",
    "research",
    "career-ops",
    "kaoyan-english",
    "docx",
    "xlsx",
)

REGISTRY = {
    "skills": [
        {
            "name": "intent-translator",
            "description": "Compile intent and govern Skill routing, registry, and maintenance work.",
        },
        {
            "name": "skill-creator",
            "description": "Create and validate a new custom Skill.",
        },
        {
            "name": "skill-installer",
            "description": "Install a selected Skill into the local Skill registry.",
        },
        {
            "name": "skill-lookup",
            "description": "Search the registry for an existing Skill.",
        },
        {
            "name": "skill-refactor",
            "description": "Refactor a named Skill directory and its implementation.",
        },
        {
            "name": "agent-reach",
            "description": "Search and research the public internet.",
        },
        {
            "name": "job-market-radar",
            "description": "Search, compare, and rank jobs and internships.",
        },
        {
            "name": "research",
            "description": "Research a question using high-trust primary sources.",
        },
        {
            "name": "career-ops",
            "description": "Manage job search, offers, CVs, and applications.",
        },
        {
            "name": "kaoyan-english",
            "description": "Route postgraduate English reading, vocabulary, and writing study.",
        },
        {
            "name": "ielts",
            "description": "Route IELTS subject training and exam preparation.",
        },
        {
            "name": "docx",
            "description": "Create, read, edit, or manipulate Word documents.",
        },
        {
            "name": "xlsx",
            "description": "Create, read, edit, or analyze spreadsheet workbooks.",
        },
    ],
    "errors": [],
}


class ControlPlanePreemptionTests(unittest.TestCase):
    def setUp(self):
        self.compiler = IntentCompiler(
            registry=REGISTRY,
            profile={
                "profile_id": "control-plane-preemption",
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

    def assert_control_plane_or_abstain(
        self,
        utterance: str,
        *,
        managed_skill: str,
        allowed_owners: set[str] | None = None,
    ) -> None:
        selected = self.compile_skill(utterance)
        self.assertNotEqual(
            selected,
            managed_skill,
            msg=f"managed object became its own execution owner: {utterance}",
        )
        allowed = {None, *(allowed_owners or CONTROL_PLANE_SKILLS)}
        self.assertIn(
            selected,
            allowed,
            msg=f"unexpected owner for control-plane work: {utterance}",
        )

    def test_negated_invocation_does_not_activate_managed_skill(self):
        templates = (
            "不要使用 {name} Skill，只审计它的版本",
            "不调用 {name} Skill，只核对它的来源",
        )
        for name in MANAGED_DOMAIN_SKILLS:
            for template in templates:
                utterance = template.format(name=name)
                with self.subTest(skill=name, utterance=utterance):
                    self.assert_control_plane_or_abstain(
                        utterance,
                        managed_skill=name,
                        allowed_owners={"intent-translator"},
                    )

    def test_registry_and_lifecycle_maintenance_does_not_activate_domain_owner(self):
        templates = (
            "更新 {name} Skill 的登记状态，不执行其领域能力",
            "评估是否退役 {name} Skill，不运行它的领域任务",
            "将 {name} Skill 标记为保留候选，不调用它",
        )
        for name in MANAGED_DOMAIN_SKILLS:
            for template in templates:
                utterance = template.format(name=name)
                with self.subTest(skill=name, utterance=utterance):
                    self.assert_control_plane_or_abstain(
                        utterance,
                        managed_skill=name,
                        allowed_owners={"intent-translator"},
                    )

    def test_skill_self_repair_and_refactor_use_refactor_owner_or_abstain(self):
        templates = (
            "检查并修复 {name} Skill 本身的路由问题，不运行其领域能力",
            "重构 {name} Skill 本身的实现结构，不执行其领域任务",
        )
        for name in MANAGED_DOMAIN_SKILLS:
            for template in templates:
                utterance = template.format(name=name)
                with self.subTest(skill=name, utterance=utterance):
                    self.assert_control_plane_or_abstain(
                        utterance,
                        managed_skill=name,
                        allowed_owners={"skill-refactor"},
                    )

    def test_delegation_and_ledger_are_meta_work_and_abstain(self):
        templates = (
            "把 {name} Skill 的审计交给子任务核对，不运行该 Skill",
            "把 {name} Skill 的状态写入审计台账，不执行它",
        )
        for name in MANAGED_DOMAIN_SKILLS:
            for template in templates:
                utterance = template.format(name=name)
                with self.subTest(skill=name, utterance=utterance):
                    self.assertIsNone(self.compile_skill(utterance))

    def test_affirmative_explicit_domain_invocation_still_works(self):
        self.assertEqual(
            self.compile_skill("使用 job-market-radar Skill 执行职位搜索和排名"),
            "job-market-radar",
        )

    def test_affirmative_explicit_control_plane_invocations_still_work(self):
        cases = {
            "明确调用 skill-creator Skill 创建一个自定义 Skill": "skill-creator",
            "明确调用 skill-installer Skill 安装指定 Skill": "skill-installer",
            "明确调用 skill-lookup Skill 查找已有 Skill": "skill-lookup",
            "明确调用 skill-refactor Skill 重构 named-helper Skill 本身": "skill-refactor",
            "明确调用 intent-translator Skill 编译这条短指令": "intent-translator",
        }
        for utterance, expected in cases.items():
            with self.subTest(utterance=utterance):
                self.assertEqual(self.compile_skill(utterance), expected)

    def test_ideation_using_existing_skills_does_not_route_to_skill_creator(self):
        negative_cases = (
            "再新建一个会话专门用来想创意，顺便看看intent会不会出错，应该让合适的skill找到创意点",
            "开个会话想点子",
            "用合适skill帮我发散方案",
            "找创意但不要新建skill",
        )
        for utterance in negative_cases:
            with self.subTest(utterance=utterance):
                result = self.compiler.compile(
                    CompileRequest(utterance=utterance, semantic_mode="off")
                )
                self.assertNotEqual(result["routing"]["primary_skill"], "skill-creator")
                self.assertNotIn("create-custom-last", result["routing"]["acquisition_policy"])
                self.assertEqual(result["intent_contract"]["data_egress"], "none")

        positive = self.compiler.compile(
            CompileRequest(
                utterance="帮我创建一个用于头脑风暴的新 Skill",
                semantic_mode="off",
            )
        )
        self.assertEqual(positive["routing"]["primary_skill"], "skill-creator")

    def test_local_coordination_audits_stay_on_read_thread_without_egress(self):
        cases = (
            "查任务",
            "找会话",
            "扫描线程寻找可疑点",
            "核对本地进程",
            "审计 Codex 调度",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                result = self.compiler.compile(
                    CompileRequest(utterance=utterance, semantic_mode="off")
                )
                contract = result["intent_contract"]
                self.assertEqual(result["mode"], "diagnose")
                self.assertEqual(contract["effect"], "read_local")
                self.assertEqual(contract["data_egress"], "none")
                self.assertEqual(contract["destination"]["kind"], "local")
                self.assertEqual(contract["action_owner"]["kind"], "host")
                self.assertEqual(contract["action_owner"]["name"], "read_thread")
                self.assertIsNone(result["routing"]["primary_skill"])

    def test_explicit_public_search_still_uses_agent_reach(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="搜索全网关于新能源汽车的最新公开信息",
                semantic_mode="off",
            )
        )
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "search")
        self.assertEqual(contract["effect"], "read_public")
        self.assertEqual(contract["data_egress"], "public_query")
        self.assertEqual(contract["destination"]["value"], "public web")
        self.assertEqual(result["routing"]["primary_skill"], "agent-reach")

    def test_public_information_and_materials_are_search_objects(self):
        for utterance in (
            "搜索全网的最新公开资料",
            "上网搜索相关公开信息",
        ):
            with self.subTest(utterance=utterance):
                result = self.compiler.compile(
                    CompileRequest(utterance=utterance, semantic_mode="off")
                )
                contract = result["intent_contract"]
                self.assertEqual(result["mode"], "search")
                self.assertEqual(contract["operation"], "search")
                self.assertEqual(contract["effect"], "read_public")
                self.assertEqual(contract["data_egress"], "public_query")
                self.assertEqual(contract["authorization"]["required_grants"], [])
                self.assertFalse(result["risk"]["confirmation_required"])
                self.assertEqual(result["routing"]["primary_skill"], "agent-reach")

    def test_explicit_publication_remains_protected_publish(self):
        result = self.compiler.compile(
            CompileRequest(
                utterance="公开发布这份已完成的结果报告",
                semantic_mode="off",
            )
        )
        contract = result["intent_contract"]
        self.assertEqual(result["mode"], "build")
        self.assertEqual(contract["operation"], "publish")
        self.assertEqual(contract["effect"], "write_external")
        self.assertIn("external", contract["authorization"]["required_grants"])
        self.assertTrue(result["risk"]["confirmation_required"])

    def test_project_governance_comparison_does_not_route_to_study_skill(self):
        compiler = IntentCompiler(
            registry=REGISTRY,
            profile={
                "profile_id": "project-governance-object-priority",
                "language": "zh-CN",
                "phrase_mappings": {},
                "memory": {"adapter": "none", "location": ""},
                "study": {
                    "enabled": True,
                    "active_goal": "西交085407",
                    "active_subject": "862",
                    "goals": ["考研", "雅思"],
                    "subjects": [
                        {
                            "name": "英语",
                            "terms": ["考研", "雅思", "英语"],
                            "preferred_skills": ["kaoyan-english", "ielts"],
                        }
                    ],
                },
            },
            profile_exists=True,
        )
        cases = (
            "确定考研项目和雅思项目流程一致了吗，没有的话交给总协调会话",
            "对比考研项目和雅思项目的流程",
            "检查两个学习项目的 AGENTS 和 README",
            "考研项目和雅思项目没一致就交给总协调会话",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                result = compiler.compile(
                    CompileRequest(utterance=utterance, semantic_mode="off")
                )
                contract = result["intent_contract"]
                selected = result["routing"]["primary_skill"]
                self.assertFalse(
                    selected == "ielts"
                    or (selected or "").startswith("ielts-")
                    or (selected or "").startswith("kaoyan-")
                )
                self.assertIsNone(selected)
                self.assertEqual(contract["effect"], "read_local")
                self.assertEqual(contract["data_egress"], "none")
                self.assertEqual(contract["destination"]["kind"], "local")
                self.assertEqual(contract["action_owner"]["name"], "read_thread")
                self.assertFalse(result["study_context"]["enabled"])
                self.assertNotIn("active_goal", result["study_context"])
                self.assertNotIn("subject", result["study_context"])
                self.assertIn("项目", contract["object"]["value"])


if __name__ == "__main__":
    unittest.main()
