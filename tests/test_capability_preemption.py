import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


SKILLS = [
    ("agent-reach", "Search and research public internet information."),
    ("apilayer-search", "Search and compare APIs in the APIlayer Marketplace."),
    ("zhihu-search", "搜索知乎站内内容，返回标题、链接、作者和摘要。"),
    ("kaoyan-navigator", "调研考研院校报录比、推免、复试线和爆热风险。"),
    ("obsidian-cli", "Search and manage notes in a local Obsidian vault."),
    ("obsidian-markdown", "Edit Obsidian Markdown wikilinks, callouts and properties."),
    ("fix-table-pipe", "修复 Obsidian Markdown callout 表格渲染和管道符错误。"),
    ("docx", "Read, create and edit .docx Word documents."),
    ("pdf", "Read, extract, merge and edit PDF files."),
    ("xlsx", "Read, create and edit Excel workbooks and .xlsx files."),
    ("word-template-generator", "Extract placeholders and generate documents from Word templates."),
    ("book-to-skill", "Convert PDF, EPUB and books into reusable Agent Skills."),
    ("career-ops", "Evaluate job offers and generate tailored CVs from job lists or JDs."),
    ("study-img", "Inspect scanned study material and teach from textbook or exam images."),
    ("parse-words", "Parse highlighted vocabulary in 考研英语 reading notes."),
    ("study-assistant", "Orchestrate systematic exam study."),
    ("kaoyan-math", "考研数学入口路由器。"),
    ("kaoyan-english", "考研英语入口路由器。"),
    ("ielts", "雅思备考入口路由器。"),
    ("ielts-reading", "分析雅思阅读错题、同义替换和 T/F/NG。"),
    ("mistake-book", "整理数学、英语或电子技术错题本。"),
    ("code-review", "Review a PR, commit, branch or diff."),
    ("ponytail-review", "Review a diff specifically for over-engineering."),
    ("scientific-critical-thinking", "Evaluate scientific evidence and experimental design."),
    ("grilling", "Stress-test a plan through adversarial questioning."),
    ("pua", "Optional high-agency governance and sharp review mode."),
    ("skill-lookup", "Search and retrieve Skills from a Skill registry."),
    ("skill-installer", "Install a selected Skill."),
]

REGISTRY = {
    "skills": [
        {"name": name, "description": description, "model_invoked": True}
        for name, description in SKILLS
    ],
    "errors": [],
}

BASE_PROFILE = {
    "profile_id": "capability-preemption-tests",
    "language": "zh-CN",
    "phrase_mappings": {},
    "memory": {"adapter": "none", "location": ""},
    "study": {"enabled": False},
}

STUDY_PROFILE = {
    **BASE_PROFILE,
    "study": {
        "enabled": True,
        "goals": ["考研", "雅思"],
        "active_goal": "考研",
        "routing": [
            {
                "subject": "math",
                "terms": ["数学", "高数", "线代", "概率论"],
                "preferred_skills": ["kaoyan-math", "study-assistant"],
            },
            {
                "subject": "english",
                "terms": ["考研英语", "雅思", "阅读", "词汇"],
                "preferred_skills": ["kaoyan-english", "study-assistant"],
            },
        ],
    },
}


class CapabilityPreemptionTests(unittest.TestCase):
    """Action owners must not be displaced by generic routing signals."""

    def compile(self, utterance: str, *, profile: dict | None = None) -> dict:
        compiler = IntentCompiler(
            registry=REGISTRY,
            profile=profile or BASE_PROFILE,
            profile_exists=True,
        )
        return compiler.compile(CompileRequest(utterance=utterance, semantic_mode="off"))

    def assert_primary(self, expected: str, utterance: str, *, profile: dict | None = None) -> None:
        result = self.compile(utterance, profile=profile)
        routing = result["routing"]
        candidates = [
            (item.get("name"), item.get("score"), item.get("evidence"))
            for item in routing.get("candidates", [])
        ]
        self.assertEqual(
            routing.get("primary_skill"),
            expected,
            msg=(
                f"utterance={utterance!r}; expected={expected!r}; "
                f"actual={routing.get('primary_skill')!r}; candidates={candidates!r}"
            ),
        )

    def test_explicit_skill_invocation_has_absolute_routing_priority(self):
        cases = [
            (
                "word-template-generator",
                "使用 word-template-generator Skill 从 contract.docx 模板中提取占位符并生成文档",
            ),
            (
                "skill-lookup",
                "使用 skill-lookup Skill 搜索并安装 prompts.chat 上的 Skill",
            ),
            (
                "scientific-critical-thinking",
                "使用 scientific-critical-thinking Skill 做实验设计评估",
            ),
        ]
        for expected, utterance in cases:
            with self.subTest(expected=expected, utterance=utterance):
                self.assert_primary(expected, utterance)

    def test_pua_is_governance_support_and_never_replaces_the_action_owner(self):
        cases = [
            (
                "scientific-critical-thinking",
                "使用 scientific-critical-thinking Skill 做尖锐反驳并评估实验设计",
            ),
            (
                "grilling",
                "使用 grilling Skill 做 adversarial review 压力测试我的方案",
            ),
            (
                "code-review",
                "使用 code-review Skill 做 adversarial review 这个 PR",
            ),
        ]
        for expected, utterance in cases:
            with self.subTest(expected=expected, utterance=utterance):
                result = self.compile(utterance)
                self.assertEqual(
                    result["routing"].get("primary_skill"),
                    expected,
                    msg=f"PUA replaced action owner for {utterance!r}: {result['routing']!r}",
                )
                self.assertTrue(result["conditional_review"].get("use_pua"))

    def test_file_medium_is_supporting_capability_not_business_owner(self):
        cases = [
            ("word-template-generator", "从 contract.docx 模板中提取占位符并生成合同"),
            ("book-to-skill", "把 handbook.pdf 转换成一个 Agent Skill"),
            ("career-ops", "读取岗位清单 jobs.xlsx，评估 offer 并定制简历"),
            ("study-img", "识别 exam.pdf 里的扫描试题并讲解"),
            ("parse-words", "解析 reading.pdf 中高亮的考研英语词汇"),
        ]
        for expected, utterance in cases:
            with self.subTest(expected=expected, utterance=utterance):
                self.assert_primary(expected, utterance)

    def test_search_routing_respects_platform_and_locality_boundaries(self):
        cases = [
            ("zhihu-search", "搜索知乎站内关于考研数学复习的回答"),
            ("apilayer-search", "搜索 APIlayer 市场里的 OCR API 并比较价格"),
            ("kaoyan-navigator", "搜索湖南大学控制工程报录比和推免比例并评估爆热风险"),
            ("obsidian-cli", "在本地 Obsidian vault 中搜索并更新这篇笔记"),
            ("agent-reach", "搜索全网关于新能源汽车的最新公开信息"),
        ]
        for expected, utterance in cases:
            with self.subTest(expected=expected, utterance=utterance):
                self.assert_primary(expected, utterance)

    def test_specialist_child_wins_over_parent_or_generic_owner(self):
        cases = [
            ("ielts-reading", "分析雅思阅读错题和同义替换", STUDY_PROFILE),
            ("mistake-book", "整理数学错题本", STUDY_PROFILE),
            ("parse-words", "解析考研英语阅读笔记的高亮词", STUDY_PROFILE),
            ("fix-table-pipe", "修复 Obsidian callout 里的 Markdown 表格管道符渲染错误", BASE_PROFILE),
            ("ponytail-review", "审查这个 diff 的过度工程，找出应删除的抽象", BASE_PROFILE),
        ]
        for expected, utterance, profile in cases:
            with self.subTest(expected=expected, utterance=utterance):
                self.assert_primary(expected, utterance, profile=profile)


if __name__ == "__main__":
    unittest.main()
