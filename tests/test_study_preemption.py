import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402


REGISTRY = {
    "skills": [
        {"name": "study-assistant", "description": "通用学习与考试编排器。"},
        {"name": "kaoyan-math", "description": "考研数学入口路由器。"},
        {"name": "kaoyan-english", "description": "考研英语入口路由器。"},
        {"name": "kaoyan-electronics", "description": "822 电子技术考研入口。"},
        {"name": "ielts", "description": "IELTS 备考入口路由器。"},
        {"name": "ielts-writing", "description": "IELTS 写作批改。"},
        {"name": "ielts-reading", "description": "IELTS 阅读精读。"},
        {"name": "ielts-listening", "description": "IELTS 听力精听。"},
        {"name": "ielts-speaking", "description": "IELTS 口语训练。"},
        {"name": "ielts-vocab", "description": "IELTS 词汇训练。"},
        {"name": "ielts-diagnosis", "description": "IELTS 诊断和备考计划。"},
        {"name": "code-review", "description": "审查 pull request、diff 和 commit。"},
        {"name": "agent-reach", "description": "搜索互联网公开信息。"},
        {"name": "skill-installer", "description": "安装 Skill。"},
        {"name": "diagnosing-bugs", "description": "诊断软件缺陷。"},
    ],
    "errors": [],
}


PROFILE = {
    "profile_id": "study-preemption-regressions",
    "language": "zh-CN",
    "phrase_mappings": {},
    "memory": {"adapter": "none", "location": ""},
    "student_state": {"enabled": False},
    "study": {
        "enabled": True,
        "goals": ["考研", "雅思"],
        "active_goal": "考研",
        "active_subject": "general-study",
        "routing": [
            {
                "subject": "math",
                "terms": ["math", "数学", "高数", "线代", "概率论"],
                "preferred_skills": ["kaoyan-math", "study-assistant"],
            },
            {
                "subject": "english",
                "terms": ["english", "英语", "ielts", "雅思", "阅读", "写作", "听力", "口语"],
                "preferred_skills": ["kaoyan-english", "study-assistant"],
            },
            {
                "subject": "professional-course",
                "terms": ["专业课", "电子技术", "模电", "数电", "822"],
                "preferred_skills": ["kaoyan-electronics", "study-assistant"],
            },
            {
                "subject": "general-study",
                "terms": ["复习", "学习计划", "错题", "测试我", "quiz", "review"],
                "preferred_skills": ["study-assistant"],
            },
            {
                "subject": "coursework",
                "terms": ["课程", "作业", "实验报告", "期中", "期末", "考试周"],
                "preferred_skills": ["study-assistant"],
            },
        ],
    },
}


STUDY_SKILLS = {
    "study-assistant",
    "kaoyan-math",
    "kaoyan-english",
    "kaoyan-electronics",
    "ielts",
    "ielts-writing",
    "ielts-reading",
    "ielts-listening",
    "ielts-speaking",
    "ielts-vocab",
    "ielts-diagnosis",
}


class StudyPreemptionTests(unittest.TestCase):
    def setUp(self):
        self.compiler = IntentCompiler(
            registry=REGISTRY,
            profile=PROFILE,
            profile_exists=True,
        )

    def compile(self, utterance: str, *, context: str = "", pending_action: str = ""):
        return self.compiler.compile(
            CompileRequest(
                utterance=utterance,
                context=context,
                pending_action=pending_action,
                semantic_mode="off",
            )
        )

    def assert_not_study_routed(self, result):
        self.assertFalse(result["study_context"]["enabled"])
        self.assertNotIn(result["routing"]["primary_skill"], STUDY_SKILLS)

    def test_technical_objects_containing_study_words_do_not_enable_study(self):
        cases = (
            "review Python 数学计算库的实现",
            "阅读英语语音识别 API 的配置",
            "重写写作插件的技术说明",
            "测试课程管理系统源码",
            "为作业调度器制定迁移计划",
            "生成雅思数据 MCP 适配器状态报告",
            "修复阅读器插件的路由问题",
            "审计考研英语 Skill 本身的版本来源",
            "review 考试监控后台 的实现与接口",
            "阅读 考试监控后台 并提取关键配置",
            "为 数学公式渲染组件 补充文档",
            "生成学习计划状态报告并核对版本",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_study_routed(self.compile(utterance))

    def test_explicit_non_study_negation_disables_study_routing(self):
        cases = (
            "review Python 数学计算库的实现；这不是学习任务",
            "阅读英语语音识别 API 的配置；不是复习任务",
            "测试课程管理系统源码；这是非学习任务",
            "生成雅思数据 MCP 适配器状态报告；not a study task",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                self.assert_not_study_routed(self.compile(utterance))

    def test_pending_technical_action_wins_over_earlier_study_context(self):
        old_context = "之前在复习考研数学和雅思，现在已切换到技术任务"
        cases = (
            "review Python 数学计算库的实现",
            "阅读英语语音识别 API 的配置",
            "测试课程管理系统源码",
            "生成雅思数据 MCP 适配器状态报告",
        )
        for pending_action in cases:
            with self.subTest(pending_action=pending_action):
                result = self.compile(
                    "继续",
                    context=old_context,
                    pending_action=pending_action,
                )
                self.assertEqual(
                    result["intent_contract"]["active_task_source"],
                    "pending",
                )
                self.assert_not_study_routed(result)

    def test_explicit_ielts_subdomain_uses_specialist_owner(self):
        cases = (
            ("雅思写作批改这篇作文", "ielts-writing"),
            ("雅思阅读精读并分析错题", "ielts-reading"),
            ("雅思听力错题分析和精听", "ielts-listening"),
            ("雅思口语素材和追问练习", "ielts-speaking"),
            ("雅思词汇复习和拼写检查", "ielts-vocab"),
        )
        for utterance, expected_skill in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertTrue(result["study_context"]["enabled"])
                self.assertEqual(result["routing"]["primary_skill"], expected_skill)

    def test_explicit_kaoyan_subject_uses_subject_owner(self):
        cases = (
            ("考研数学极限这题怎么做", "kaoyan-math"),
            ("考研英语阅读怎么复习", "kaoyan-english"),
            ("模电反馈电路怎么分析", "kaoyan-electronics"),
        )
        for utterance, expected_skill in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertTrue(result["study_context"]["enabled"])
                self.assertEqual(result["routing"]["primary_skill"], expected_skill)
                self.assertNotEqual(result["routing"]["primary_skill"], "study-assistant")

    def test_study_assistant_is_only_the_generic_study_fallback(self):
        cases = (
            "复习一下昨天的错题",
            "测试我今天背的内容",
            "给我安排今天的学习计划",
            "继续学习",
        )
        for utterance in cases:
            with self.subTest(utterance=utterance):
                result = self.compile(utterance)
                self.assertTrue(result["study_context"]["enabled"])
                self.assertEqual(result["routing"]["primary_skill"], "study-assistant")


if __name__ == "__main__":
    unittest.main()
