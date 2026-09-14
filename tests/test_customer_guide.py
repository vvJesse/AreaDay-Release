from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "docs" / "customer-guide"
GUIDE = GUIDE_DIR / "AreaDay-安装和使用指南.md"


class CustomerGuideTests(unittest.TestCase):
    def test_customer_guide_matches_release_version_and_deliverables(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        guide = GUIDE.read_text(encoding="utf-8")

        skill_match = re.search(r"(?m)^version:\s*([0-9]+\.[0-9]+\.[0-9]+)$", skill)
        guide_match = re.search(r"适用版本：AreaDay v([0-9]+\.[0-9]+\.[0-9]+)", guide)
        self.assertIsNotNone(skill_match)
        self.assertIsNotNone(guide_match)
        version = skill_match.group(1)
        self.assertEqual(guide_match.group(1), version)

        self.assertIn(f"AreaDay-macos-arm64-v{version}.zip", guide)
        self.assertIn(f"AreaDay-windows-x64-v{version}.zip", guide)
        self.assertIn(f"/releases/{version}/AreaDay-macos-arm64-v{version}.zip", guide)
        self.assertIn(f"/releases/{version}/AreaDay-windows-x64-v{version}.zip", guide)
        self.assertTrue((GUIDE_DIR / f"AreaDay-安装和使用指南-v{version}.pdf").is_file())

        required_phrases = (
            "https://github.com/vvJesse/AreaDay-Release",
            "帮我安装这个 Skill。",
            "安装包路径：",
            "许可证文件直接拖入输入框",
            "credentials.ini",
            "api_key =",
            "https://guide.areaday.app/",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, guide)

    def test_repository_readmes_point_to_the_canonical_guide(self) -> None:
        target = "docs/customer-guide/AreaDay-安装和使用指南.md"
        self.assertIn(target, (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn(target, (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
