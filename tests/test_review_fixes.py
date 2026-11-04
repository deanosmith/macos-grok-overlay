import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from http.cookiejar import Cookie
from pathlib import Path
from unittest.mock import Mock, patch

from macos_grok_overlay import app, browser_cookies, launcher, listener


class CommandLineImportTests(unittest.TestCase):
    def test_package_import_does_not_load_overlay_ui(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys, macos_grok_overlay; print('macos_grok_overlay.app' in sys.modules)"],
            capture_output=True, text=True, check=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


class KeyboardListenerTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.event = object()
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.dict(
            listener.LAUNCHER_TRIGGER,
            {"flags": listener.NSEventModifierFlagOption, "key": 49},
            clear=True,
        ))
        self.contexts.enter_context(patch.object(listener, "handle_new_trigger", None))
        self.flags = self.contexts.enter_context(patch.object(listener, "CGEventGetFlags", return_value=0))
        self.keycode = self.contexts.enter_context(patch.object(listener, "CGEventGetIntegerValueField", return_value=49))
        self.contexts.enter_context(redirect_stdout(io.StringIO()))
        self.callback = listener.global_show_hide_listener(self.app)

    def test_unrelated_modifiers_skip_keycode_lookup(self):
        result = self.callback(None, listener.kCGEventKeyDown, self.event, None)

        self.assertIs(result, self.event)
        self.keycode.assert_not_called()
        self.app.showWindow_.assert_not_called()
        self.app.hideWindow_.assert_not_called()

    def test_matching_shortcut_still_toggles_window(self):
        self.flags.return_value = listener.LAUNCHER_TRIGGER["flags"]
        for is_key in (False, True):
            with self.subTest(is_key=is_key):
                self.app.reset_mock()
                self.app.window.isKeyWindow.return_value = is_key
                result = self.callback(None, listener.kCGEventKeyDown, self.event, None)

                self.assertIsNone(result)
                if is_key:
                    self.app.hideWindow_.assert_called_once_with(None)
                    self.app.showWindow_.assert_not_called()
                else:
                    self.app.showWindow_.assert_called_once_with(None)
                    self.app.hideWindow_.assert_not_called()

    def test_trigger_capture_still_receives_unmodified_keys(self):
        listener.LAUNCHER_TRIGGER.update({"flags": None, "key": None})
        with patch.object(listener, "handle_new_trigger") as capture:
            result = self.callback(None, listener.kCGEventKeyDown, self.event, None)

        self.assertIsNone(result)
        capture.assert_called_once_with(self.event, 0, 49)


class BrowserCookieSyncTests(unittest.TestCase):
    def test_collection_uses_worker_and_import_returns_to_main_queue(self):
        webview = Mock()
        completion = Mock()
        cookies = [object()]
        with ExitStack() as contexts:
            thread = contexts.enter_context(patch.object(browser_cookies, "Thread"))
            collect = contexts.enter_context(patch.object(browser_cookies, "_collect_cookies", return_value=cookies))
            operation_queue = contexts.enter_context(patch.object(browser_cookies, "NSOperationQueue"))
            import_cookies = contexts.enter_context(patch.object(browser_cookies, "_import_cookies_into_webview"))
            browser_cookies.sync_browser_cookies_to_webview(webview, completion)

            thread.return_value.start.assert_called_once_with()
            self.assertTrue(thread.call_args.kwargs["daemon"])
            collect.assert_not_called()
            thread.call_args.kwargs["target"]()
            collect.assert_called_once_with()
            import_cookies.assert_not_called()
            main_queue = operation_queue.mainQueue.return_value
            main_queue.addOperationWithBlock_.assert_called_once()
            main_queue.addOperationWithBlock_.call_args.args[0]()
            import_cookies.assert_called_once_with(webview, cookies, completion)

    def test_empty_cookie_import_completes_without_touching_webview(self):
        webview = Mock()
        completion = Mock()
        with redirect_stdout(io.StringIO()):
            browser_cookies._import_cookies_into_webview(webview, [], completion)

        completion.assert_called_once_with(0)
        webview.configuration.assert_not_called()


class StartupInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_home.cleanup)
        self.home = Path(temporary_home.name)
        self.log_path = self.home / "installer.log"
        self.program_args = [sys.executable, "-m", "macos_grok_overlay"]
        self.output = io.StringIO()
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.object(launcher.Path, "home", return_value=self.home))
        self.contexts.enter_context(patch.object(launcher, "LOG_PATH", self.log_path))
        self.contexts.enter_context(patch.object(launcher.getpass, "getuser", return_value="overlay-review"))
        self.contexts.enter_context(patch.object(launcher.os, "getuid", return_value=501))
        self.contexts.enter_context(patch.object(launcher, "get_executable", return_value=self.program_args))
        self.contexts.enter_context(patch.object(launcher, "reset_crash_counter"))
        self.nsapp = self.contexts.enter_context(patch.object(app, "NSApp"))
        self.contexts.enter_context(redirect_stdout(self.output))

    def test_menu_install_uses_independent_logged_process(self):
        with patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            app.AppDelegate.alloc().init().install_(None)

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], self.program_args + ["--install-startup"])
        self.assertTrue(run.call_args.kwargs["start_new_session"])
        self.assertEqual(Path(run.call_args.kwargs["stdout"].name), self.log_path)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.STDOUT)
        self.nsapp.terminate_.assert_called_once_with(None)

    def test_menu_does_not_terminate_on_reported_failure(self):
        with patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            app.AppDelegate.alloc().init().install_(None)

        self.nsapp.terminate_.assert_not_called()
        self.assertIn(str(self.log_path), self.output.getvalue())

    def test_menu_reports_installer_start_failure(self):
        with patch.object(launcher.subprocess, "run", side_effect=OSError("cannot start installer")):
            app.AppDelegate.alloc().init().install_(None)

        self.nsapp.terminate_.assert_not_called()
        self.assertIn("cannot start installer", self.output.getvalue())

    def test_installer_runs_in_separate_session(self):
        probe = (
            "import json, os, sys; "
            "print(json.dumps({'pid': os.getpid(), 'sid': os.getsid(0), 'pgid': os.getpgrp()})); "
            "print('installer stderr', file=sys.stderr)"
        )
        with patch.object(launcher, "get_executable", return_value=[sys.executable, "-c", probe]):
            self.assertTrue(launcher.install_startup_from_app())

        lines = self.log_path.read_text().splitlines()
        process_info = next(json.loads(line) for line in lines if line.startswith("{"))
        self.assertEqual(process_info["sid"], process_info["pid"])
        self.assertEqual(process_info["pgid"], process_info["pid"])
        self.assertNotEqual(process_info["pgid"], os.getpgrp())
        self.assertIn("installer stderr", lines)

    def test_cli_install_replaces_job_with_valid_plist(self):
        results = [
            subprocess.CompletedProcess([], 113, stderr="service not loaded"),
            subprocess.CompletedProcess([], 0, stderr=""),
            subprocess.CompletedProcess([], 0, stderr=""),
        ]
        with patch.object(launcher.subprocess, "run", side_effect=results) as run:
            self.assertTrue(launcher.install_startup())

        plist_path = self.home / "Library" / "LaunchAgents" / "com.overlay-review.macosgrokoverlay.plist"
        with plist_path.open("rb") as stream:
            configuration = plistlib.load(stream)
        self.assertEqual(configuration["ProgramArguments"], self.program_args)
        self.assertEqual(configuration["KeepAlive"], {"SuccessfulExit": False})
        self.assertTrue(configuration["RunAtLoad"])
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["launchctl", "bootout", "gui/501/com.overlay-review.macosgrokoverlay"],
                ["launchctl", "bootstrap", "gui/501", str(plist_path)],
                ["launchctl", "kickstart", "gui/501/com.overlay-review.macosgrokoverlay"],
            ],
        )

    def test_bootstrap_failure_stops_installation(self):
        results = [
            subprocess.CompletedProcess([], 0, stderr=""),
            subprocess.CompletedProcess([], 1, stderr="bootstrap failed"),
        ]
        with patch.object(launcher.subprocess, "run", side_effect=results) as run:
            self.assertFalse(launcher.install_startup())

        self.assertEqual(run.call_count, 2)
        self.assertIn("bootstrap failed", self.output.getvalue())

    def test_kickstart_failure_is_reported(self):
        results = [
            subprocess.CompletedProcess([], 0, stderr=""),
            subprocess.CompletedProcess([], 0, stderr=""),
            subprocess.CompletedProcess([], 1, stderr="kickstart failed"),
        ]
        with patch.object(launcher.subprocess, "run", side_effect=results):
            self.assertFalse(launcher.install_startup())

        self.assertIn("kickstart failed", self.output.getvalue())


class CookieConversionTests(unittest.TestCase):
    def make_cookie(self, secure, expires=None):
        return Cookie(
            version=0,
            name="synthetic-review-cookie",
            value="synthetic",
            port=None,
            port_specified=False,
            domain=".example.invalid",
            domain_specified=True,
            domain_initial_dot=True,
            path="/chat",
            path_specified=True,
            secure=secure,
            expires=expires,
            discard=expires is None,
            comment=None,
            comment_url=None,
            rest={},
        )

    def test_cookie_secure_flag_is_preserved(self):
        for secure in (True, False):
            with self.subTest(secure=secure):
                native = browser_cookies._ns_cookie_from_jar_cookie(self.make_cookie(secure))
                self.assertIsNotNone(native)
                self.assertEqual(bool(native.isSecure()), secure)

    def test_cookie_attributes_are_preserved(self):
        cookie = self.make_cookie(True, expires=int(time.time()) + 3600)
        native = browser_cookies._ns_cookie_from_jar_cookie(cookie)
        self.assertEqual(native.name(), cookie.name)
        self.assertEqual(native.value(), cookie.value)
        self.assertEqual(native.domain(), cookie.domain)
        self.assertEqual(native.path(), cookie.path)
        self.assertEqual(native.expiresDate().timeIntervalSince1970(), cookie.expires)

    def test_empty_cookie_path_defaults_to_root(self):
        cookie = self.make_cookie(False)
        cookie.path = ""
        native = browser_cookies._ns_cookie_from_jar_cookie(cookie)
        self.assertEqual(native.path(), "/")


if __name__ == "__main__":
    unittest.main()
