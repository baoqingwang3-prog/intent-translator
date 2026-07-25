import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "agent-reach", "description": "Search GitHub and the public internet"},
        {"name": "skill-lookup", "description": "Search installed and registry Agent Skills"},
        {"name": "skill-installer", "description": "Install Agent Skills and their dependencies"},
        {"name": "skill-creator", "description": "Create and validate Agent Skills"},
        {"name": "browser", "description": "Run browser and Playwright tests"},
        {"name": "code-review", "description": "Review code changes and regressions"},
    ],
    "errors": [],
}


class RoleMatrixP0Tests(unittest.TestCase):
    def _compile(self, utterance: str, *, available_files=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = {
                "schema_version": 1,
                "profile_id": "role-matrix-user",
                "phrase_mappings": {},
                "memory": {"adapter": "none"},
                "study": {
                    "enabled": True,
                    "goals": ["资格考试", "语言认证"],
                    "active_goal": "资格考试",
                    "routing": [],
                },
            }
            with patch.dict(
                os.environ,
                {
                    "INTENT_TRANSLATOR_HOME": str(root),
                    "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                    "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
                },
                clear=False,
            ):
                return IntentCompiler(
                    registry=REGISTRY,
                    profile=profile,
                    profile_exists=True,
                ).compile(
                    CompileRequest(
                        utterance=utterance,
                        available_files=available_files or [],
                        semantic_mode="off",
                        include_prompt=False,
                    )
                )

    def test_profession_actions_are_consistent_across_chinese_english_and_mixed_language(self):
        cases = [
            {
                "role": "developer",
                "utterances": (
                    "用 Playwright 测试本地网页的登录流程",
                    "Use Playwright to test the local login flow",
                    "请用 Playwright test 本地 login flow",
                ),
                "expected": ("change", "test", "read_local", "none", "browser", False, True),
            },
            {
                "role": "product-manager",
                "utterances": (
                    "评估这个功能的产品价值，只回答结论",
                    "Evaluate the product value of this feature and answer with the conclusion",
                    "分析这个 feature 的产品价值，只 answer 结论",
                ),
                "expected": ("answer", "answer", "none", "none", None, False, False),
            },
            {
                "role": "designer",
                "utterances": (
                    "用浏览器验证 390x844 下按钮有没有重叠",
                    "Use the browser to verify that buttons do not overlap at 390x844",
                    "请用 browser 验证 390x844 的 button overlap",
                ),
                "expected": ("change", "test", "read_local", "none", "browser", False, True),
            },
            {
                "role": "researcher",
                "utterances": (
                    "搜索 GitHub 上公开的语义路由项目",
                    "Search GitHub for public semantic routing projects",
                    "帮我 search GitHub 上的 semantic router 项目",
                ),
                "expected": ("search", "search", "read_public", "public_query", "agent-reach", False, True),
            },
            {
                "role": "operations-admin",
                "utterances": (
                    "安装这个现成 Skill 的依赖",
                    "Install the dependencies for this existing Skill",
                    "帮我 install 这个 Skill dependency",
                ),
                "expected": (
                    "change",
                    "install",
                    "system_change",
                    "none",
                    "skill-installer",
                    True,
                    False,
                ),
            },
            {
                "role": "content-creator",
                "utterances": (
                    "把这份未公开稿件上传到 GitHub Pages",
                    "Upload this unpublished draft to GitHub Pages",
                    "把这个 private draft upload 到 GitHub Pages",
                ),
                "available_files": ["draft.md"],
                "expected": ("change", "transfer", "write_external", "private_file", None, True, False),
            },
            {
                "role": "finance",
                "utterances": (
                    "根据我的银行流水替我决定并执行一笔投资",
                    "Use my bank statements to choose and execute an investment",
                    "根据 bank statement 替我 decide and execute 一笔投资",
                ),
                "expected": ("answer", "answer", "none", "none", None, True, False),
                "high_stakes": True,
            },
            {
                "role": "legal-admin",
                "utterances": (
                    "删除离职员工账号和全部历史数据",
                    "Delete the former employee account and all historical data",
                    "删除 former employee account 和全部 history data",
                ),
                "expected": ("change", "delete", "destructive", "none", None, True, False),
            },
        ]

        for case in cases:
            for utterance in case["utterances"]:
                with self.subTest(role=case["role"], utterance=utterance):
                    result = self._compile(
                        utterance,
                        available_files=case.get("available_files"),
                    )
                    contract = result["intent_contract"]
                    actual = (
                        result["mode"],
                        contract["operation"],
                        contract["effect"],
                        contract["data_egress"],
                        result["routing"]["primary_skill"],
                        result["clarification_required"],
                        result["completion_contract"]["execute"],
                    )
                    self.assertEqual(actual, case["expected"])
                    self.assertFalse(result["study_context"]["enabled"])
                    self.assertEqual(result["current_status"]["goal"], utterance)
                    if case.get("high_stakes"):
                        self.assertTrue(result["risk"]["high_stakes"])

    def test_explicit_study_requests_are_consistent_across_languages(self):
        for utterance in (
            "帮我安排今天的资格考试复习",
            "Help me plan today's exam study session",
            "帮我 plan 今天的 exam 复习",
        ):
            with self.subTest(utterance=utterance):
                result = self._compile(utterance)
                self.assertTrue(result["study_context"]["enabled"])


if __name__ == "__main__":
    unittest.main()
