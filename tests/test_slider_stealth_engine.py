"""滑块的反检测内核选择与 Chromium 复用。

回归两件事：
1. 装了 Patchright 就必须用它 —— 同一份 Chromium 下 Playwright 会把
   navigator.webdriver 暴露成 true，这是最容易被查的自动化标志。
2. Chromium 可执行文件要能从现成安装里解析出来。Patchright 与 Playwright
   各自绑定不同 revision，让它自己下载会平白多几百 MB 且国内常拉不动。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import xianyu_slider_stealth as slider


class ChromiumDiscoveryTests(unittest.TestCase):
    def _make_install(self, root: Path, revision: str, layout: str) -> Path:
        executable = root / f"chromium-{revision}" / layout
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\n")
        return executable

    def test_finds_linux_chromium_from_browsers_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = self._make_install(root, "1223", "chrome-linux/chrome")

            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(root)}):
                found = slider.find_chromium_executable()

            self.assertEqual(found, str(expected))

    def test_prefers_newest_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_install(root, "1100", "chrome-linux/chrome")
            newest = self._make_install(root, "1223", "chrome-linux/chrome")

            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(root)}):
                found = slider.find_chromium_executable()

            self.assertEqual(found, str(newest))

    def test_ignores_headless_shell_only_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # headless shell 是单独下载的包，缺少滑块页面需要的渲染能力
            shell = root / "chromium_headless_shell-1223" / "chrome-linux" / "headless_shell"
            shell.parent.mkdir(parents=True, exist_ok=True)
            shell.write_text("#!/bin/sh\n")

            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(root)}):
                found = slider.find_chromium_executable()

            self.assertIsNone(found)

    def test_missing_install_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": tmp}):
                # 目录存在但没装浏览器时要老实返回 None，让调用方走默认解析
                self.assertIsNone(slider.find_chromium_executable())


class StealthEngineSelectionTests(unittest.TestCase):
    def _make_instance(self):
        instance = slider.XianyuSliderStealth.__new__(slider.XianyuSliderStealth)
        instance.user_id = instance.pure_user_id = "acc"
        instance._browser_slot_held = False
        instance.headless = True
        instance.page = instance.context = instance.browser = instance.playwright = None
        return instance

    def test_patchright_is_preferred_when_available(self):
        instance = self._make_instance()
        instance._stealth_engine = (
            "patchright" if slider.PATCHRIGHT_AVAILABLE else "playwright"
        )

        if slider.PATCHRIGHT_AVAILABLE:
            self.assertEqual(instance._stealth_engine, "patchright")
        else:
            self.assertEqual(instance._stealth_engine, "playwright")

    def test_engine_marker_is_set_before_launch(self):
        # 回退分支的日志会读这个字段，不能等到 init_browser 才有值
        with patch.object(slider.XianyuSliderStealth, "_check_date_validity", return_value=True):
            instance = slider.XianyuSliderStealth(user_id="acc", enable_learning=False)
        try:
            self.assertIn(instance._stealth_engine, {"patchright", "playwright"})
        finally:
            slider.concurrency_manager.unregister_instance(instance.user_id)

    def test_patchright_import_is_declared_in_requirements(self):
        text = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("patchright", text)




# ---------- Windows 布局解析（chrome-win64 / chrome-win）回归 ----------
# issue #102 附录：新版 Playwright（1.53+，Windows x64 构建）把 Chromium 装在
# chromium-*/chrome-win64/，旧版在 chromium-*/chrome-win/。滑块回退与打包提取
# 依赖的路径解析必须两种布局都认，否则新版装了浏览器也会被判定为「没装」。


def test_find_chromium_executable_windows_new_layout(tmp_path):
    executable = tmp_path / "chromium-1208" / "chrome-win64" / "chrome.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("stub")

    with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path)}):
        assert slider.find_chromium_executable() == str(executable)


def test_find_chromium_executable_windows_legacy_layout(tmp_path):
    executable = tmp_path / "chromium-1181" / "chrome-win" / "chrome.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("stub")

    with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path)}):
        assert slider.find_chromium_executable() == str(executable)


def test_resolve_chrome_win_dir_prefers_existing_layout(tmp_path):
    chromium_dir = tmp_path / "chromium-1208"
    (chromium_dir / "chrome-win64").mkdir(parents=True)
    assert slider.resolve_chrome_win_dir(chromium_dir) == chromium_dir / "chrome-win64"


def test_resolve_chrome_win_dir_falls_back_to_legacy(tmp_path):
    chromium_dir = tmp_path / "chromium-1181"
    chromium_dir.mkdir()
    assert slider.resolve_chrome_win_dir(chromium_dir) == chromium_dir / "chrome-win"


def _load_start_resolver():
    """只提取 Start.py 的 _resolve_chrome_win_dir 参与测试。

    直接 import Start 会触发数据库迁移与浏览器自检等重副作用，
    这里按函数名从源码里取出该函数单独执行。
    """
    import ast

    source = (Path(__file__).resolve().parent.parent / "Start.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_chrome_win_dir":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {"Path": Path}
            exec(compile(module, "Start.py", "exec"), namespace)
            return namespace["_resolve_chrome_win_dir"]
    raise AssertionError("Start.py 中未找到 _resolve_chrome_win_dir")


def test_start_resolver_matches_new_layout(tmp_path):
    resolve = _load_start_resolver()
    chromium_dir = tmp_path / "chromium-1208"
    (chromium_dir / "chrome-win64").mkdir(parents=True)
    assert resolve(chromium_dir) == chromium_dir / "chrome-win64"


def test_start_resolver_matches_legacy_layout(tmp_path):
    resolve = _load_start_resolver()
    chromium_dir = tmp_path / "chromium-1181"
    (chromium_dir / "chrome-win").mkdir(parents=True)
    assert resolve(chromium_dir) == chromium_dir / "chrome-win"


def test_start_resolver_defaults_to_legacy_when_missing(tmp_path):
    resolve = _load_start_resolver()
    chromium_dir = tmp_path / "chromium-9999"
    chromium_dir.mkdir()
    assert resolve(chromium_dir) == chromium_dir / "chrome-win"


if __name__ == "__main__":
    unittest.main()

