import io
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import Mock, patch

from Foundation import NSError, NSURLErrorCancelled, NSURLErrorDomain, NSURL

from macos_grok_overlay import auth_browser


class LoadingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.webview = self.app.webview
        self.webview.isLoading.return_value = False
        self.webview.URL.return_value = NSURL.URLWithString_("https://grok.com/")
        self.app.window.isVisible.return_value = True
        self.delegate = auth_browser.WebNavigationDelegate.alloc().initWithAppDelegate_(self.app)
        self.error = NSError.errorWithDomain_code_userInfo_(NSURLErrorDomain, -1100, None)
        self.output = io.StringIO()
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(redirect_stdout(self.output))
        self.alert_class = self.contexts.enter_context(patch.object(auth_browser, "NSAlert"))
        self.alert = self.alert_class.alloc.return_value.init.return_value

    def fail_provisionally(self, error=None):
        self.delegate.webView_didFailProvisionalNavigation_withError_(
            self.webview, None, self.error if error is None else error
        )

    def test_failed_reload_restores_existing_page_and_reports_error(self):
        self.fail_provisionally()

        self.app.loading_view.setHidden_.assert_called_once_with(True)
        self.app.focusOverlayInput.assert_called_once_with()
        self.assertIn(str(self.error.localizedDescription()), self.output.getvalue())
        self.alert.runModal.assert_called_once_with()
        self.assertIn("Home", self.alert.setInformativeText_.call_args.args[0])

    def test_failure_after_commit_also_restores_page(self):
        self.delegate.webView_didFailNavigation_withError_(self.webview, None, self.error)

        self.app.loading_view.setHidden_.assert_called_once_with(True)
        self.alert.runModal.assert_called_once_with()

    def test_first_load_failure_keeps_empty_page_black(self):
        for url in (None, NSURL.URLWithString_("about:blank")):
            with self.subTest(url=url):
                self.webview.URL.return_value = url
                self.fail_provisionally()

        self.app.loading_view.setHidden_.assert_not_called()
        self.assertEqual(self.alert.runModal.call_count, 2)

    def test_cancellation_restores_existing_page_without_alert(self):
        cancelled = NSError.errorWithDomain_code_userInfo_(
            NSURLErrorDomain, NSURLErrorCancelled, None
        )
        self.fail_provisionally(cancelled)

        self.app.loading_view.setHidden_.assert_called_once_with(True)
        self.alert.runModal.assert_not_called()

    def test_old_failure_does_not_uncover_replacement_load(self):
        self.webview.isLoading.return_value = True
        self.fail_provisionally()

        self.app.loading_view.setHidden_.assert_not_called()
        self.alert.runModal.assert_not_called()

    def test_hidden_failure_does_not_uncover_blank_or_show_alert(self):
        self.app.window.isVisible.return_value = False
        self.fail_provisionally()

        self.app.loading_view.setHidden_.assert_not_called()
        self.alert.runModal.assert_not_called()

    def test_other_webview_failure_is_ignored(self):
        self.delegate.webView_didFailProvisionalNavigation_withError_(Mock(), None, self.error)

        self.app.loading_view.setHidden_.assert_not_called()
        self.alert.runModal.assert_not_called()

    def test_successful_page_reveals_content_and_focuses_input(self):
        self.delegate.webView_didFinishNavigation_(self.webview, None)

        self.app.loading_view.setHidden_.assert_called_once_with(True)
        self.app.focusOverlayInput.assert_called_once_with()

    def test_blank_navigation_does_not_reveal_white_empty_page(self):
        self.webview.URL.return_value = NSURL.URLWithString_("about:blank")
        self.delegate.webView_didFinishNavigation_(self.webview, None)

        self.app.loading_view.setHidden_.assert_not_called()


if __name__ == "__main__":
    unittest.main()
