# -*- coding: utf-8 -*-
"""定时启动模块注册表与配置迁移测试（不创建 Qt 界面、不改系统任务计划）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QT_DIR = ROOT / "statgi_qt"
if str(QT_DIR) not in sys.path:
    sys.path.insert(0, str(QT_DIR))

import modules
import svc_autostart


class ModuleRegistryTests(unittest.TestCase):
    def test_every_builtin_module_has_ui_lifecycle(self):
        for item in modules.load_all():
            if item["key"] == "external":
                continue  # 声明式导入器不是 Python 模块 UI
            with self.subTest(module=item["key"]):
                info = modules.module_info(item["key"])
                ui_path = Path(info["path"]) / "ui.py"
                self.assertTrue(ui_path.is_file())
                source = ui_path.read_text(encoding="utf-8")
                for method in ("build", "collect", "apply", "toggle"):
                    self.assertIn(f"def {method}(", source, method)
                logic_path = Path(info["path"]) / "logic.py"
                self.assertTrue(logic_path.is_file())
                logic_source = logic_path.read_text(encoding="utf-8")
                self.assertIn("def steps(", logic_source)
                self.assertIn("def defaults(", logic_source)

    def test_old_enabled_fields_migrate_to_module_switches(self):
        cfg = svc_autostart.cfg({"autostart": {
            "live_enabled": False,
            "hang_enabled": True,
            "obs_exe": r"C:\\obs\\obs64.exe",
            "live_url": "https://example.invalid/live",
        }})
        self.assertFalse(cfg["modules"]["live"])
        self.assertTrue(cfg["modules"]["hang"])
        self.assertEqual(cfg["module_config"]["live"]["obs_exe"],
                         r"C:\\obs\\obs64.exe")
        self.assertEqual(cfg["module_config"]["hang"]["live_url"],
                         "https://example.invalid/live")

    def test_unknown_module_cannot_execute(self):
        self.assertEqual(svc_autostart.module_steps({}, "missing-module"), [])

    def test_disabled_module_has_no_steps(self):
        cfg = svc_autostart.cfg({})
        cfg["modules"]["live"] = False
        self.assertEqual(svc_autostart.module_steps(cfg, "live"), [])

    def test_each_builtin_configuration_is_namespaced(self):
        config = svc_autostart.cfg({"autostart": {
            "bgi_exe": r"C:\\BGI\\BetterGI.exe",
            "obs_exe": r"C:\\OBS\\obs64.exe",
            "live_url": "https://example.invalid/live",
        }})
        self.assertEqual(config["module_config"]["bgi"]["bgi_exe"],
                         r"C:\\BGI\\BetterGI.exe")
        self.assertEqual(config["module_config"]["live"]["obs_exe"],
                         r"C:\\OBS\\obs64.exe")
        self.assertEqual(config["module_config"]["hang"]["live_url"],
                         "https://example.invalid/live")
        for old_key in ("bgi_exe", "obs_exe", "live_url"):
            self.assertNotIn(old_key, config)

    def test_module_steps_read_only_their_namespaced_configuration(self):
        config = svc_autostart.cfg({"autostart": {
            "modules": {"bgi": True, "live": True, "hang": True},
            "module_config": {
                "bgi": {"bgi_exe": r"C:\\BGI\\BetterGI.exe",
                        "groups": ["测试组"]},
                "live": {"obs_exe": r"C:\\OBS\\obs64.exe",
                         "obs_start_stream": True, "obs_minimize": False},
                "hang": {"live_url": "https://example.invalid/live",
                         "chrome_exe": r"C:\\Chrome\\chrome.exe"},
            },
        }})
        bgi = svc_autostart.module_steps(config, "bgi")
        live = svc_autostart.module_steps(config, "live")
        hang = svc_autostart.module_steps(config, "hang")
        self.assertEqual(bgi[0]["args"], ["--startGroups", "测试组"])
        self.assertEqual(live[0]["exe"], r"C:\\OBS\\obs64.exe")
        self.assertEqual(live[0]["args"], ["--startstreaming"])
        self.assertEqual(hang[0]["url"], "https://example.invalid/live")
        self.assertEqual(hang[0]["exe"], r"C:\\Chrome\\chrome.exe")

    def test_startup_script_waits_before_the_configured_action(self):
        lines = svc_autostart.build_steps_bat_lines([
            {"label": "测试", "exe": "tool.exe", "delay": 7}
        ])
        self.assertLess(lines.index("timeout /t 7 /nobreak >nul"),
                        next(i for i, line in enumerate(lines)
                             if line.startswith('start ""')))


if __name__ == "__main__":
    unittest.main()
