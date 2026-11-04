import unittest
from unittest.mock import Mock, patch

from Foundation import NSURL
from WebKit import WKNavigationActionPolicyAllow

from macos_grok_overlay import app, auth_browser


class ChatPreservationTests(unittest.TestCase):
    def setUp(self):
        self.delegate = app.AppDelegate.alloc().init()
        self.delegate.window = Mock()
        self.delegate.webview = Mock()
        self.delegate.loading_view = Mock()
        self.delegate.window_manifestation = Mock()
        self.delegate.drag_area = Mock()
        self.delegate.settings = Mock()
        self.delegate.settings.boolForKey_.return_value = True
        self.delegate.window.isVisible.return_value = False
        self.delegate.webview.isLoading.return_value = False
        self.delegate._webview_needs_reload = False

    def test_hiding_open_conversation_does_not_reset_page(self):
        self.delegate.webview.URL.return_value = NSURL.URLWithString_("https://grok.com/c/example")
        self.delegate.applicationDidHide_(None)

        self.delegate.window.orderOut_.assert_called_once_with(None)
        self.delegate.webview.stopLoading.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()
        self.delegate.loading_view.setHidden_.assert_not_called()
        self.delegate.window_manifestation.finish.assert_called_once_with()
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_hiding_home_preserves_page_and_draft(self):
        self.delegate.webview.URL.return_value = NSURL.URLWithString_(app.WEBSITE)
        self.delegate.applicationDidHide_(None)

        self.delegate.webview.stopLoading.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()
        self.delegate.loading_view.setHidden_.assert_not_called()
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_hiding_other_host_also_preserves_page(self):
        self.delegate.webview.URL.return_value = NSURL.URLWithString_("https://example.invalid/c/example")
        self.delegate.applicationDidHide_(None)

        self.delegate.webview.stopLoading.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_hiding_during_preload_does_not_interrupt_loading(self):
        self.delegate.webview.isLoading.return_value = True
        self.delegate.webview.URL.return_value = None
        self.delegate.applicationDidHide_(None)

        self.delegate.webview.stopLoading.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_home_load_starts_immediately_while_hidden(self):
        self.delegate._webview_needs_reload = True
        self.delegate.loadOverlayHomePage_(None)

        request = self.delegate.webview.loadRequest_.call_args.args[0]
        self.assertEqual(request.URL().absoluteString(), app.WEBSITE)
        self.delegate.loading_view.setHidden_.assert_called_once_with(False)
        self.delegate.window.makeKeyAndOrderFront_.assert_not_called()
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_showing_preserved_conversation_does_not_reload(self):
        self.delegate._move_window_to_cursor_screen = Mock()
        self.delegate.loadOverlayHomePage_ = Mock()
        self.delegate.updateAuthSessionForMainWebView = Mock()
        self.delegate.focusOverlayInput = Mock()
        with patch.object(app, "NSApp"):
            self.delegate.showWindow_(None)

        self.delegate.loadOverlayHomePage_.assert_not_called()
        self.delegate.window_manifestation.begin.assert_called_once_with()
        self.delegate.focusOverlayInput.assert_called_once_with()

    def test_showing_visible_preload_does_not_restart_manifestation(self):
        self.delegate._move_window_to_cursor_screen = Mock()
        self.delegate.updateAuthSessionForMainWebView = Mock()
        self.delegate.focusOverlayInput = Mock()
        self.delegate.window.isVisible.return_value = True
        self.delegate.webview.isLoading.return_value = True
        with patch.object(app, "NSApp"):
            self.delegate.showWindow_(None)

        self.delegate.window_manifestation.begin.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()

    def test_only_hidden_window_manifests_regardless_of_load_state(self):
        self.delegate._move_window_to_cursor_screen = Mock()
        self.delegate.loadOverlayHomePage_ = Mock()
        self.delegate.updateAuthSessionForMainWebView = Mock()
        self.delegate.focusOverlayInput = Mock()
        for needs_reload, loading in ((False, False), (True, False), (False, True)):
            for visible in (False, True):
                with self.subTest(needs_reload=needs_reload, loading=loading, visible=visible):
                    self.delegate._webview_needs_reload = needs_reload
                    self.delegate.webview.isLoading.return_value = loading
                    self.delegate.window.isVisible.return_value = visible
                    self.delegate.window_manifestation.reset_mock()
                    with patch.object(app, "NSApp"):
                        self.delegate.showWindow_(None)

                    if visible:
                        self.delegate.window_manifestation.begin.assert_not_called()
                    else:
                        self.delegate.window_manifestation.begin.assert_called_once_with()

    def test_animation_setting_can_disable_loaded_window_reveal(self):
        self.delegate._move_window_to_cursor_screen = Mock()
        self.delegate.updateAuthSessionForMainWebView = Mock()
        self.delegate.focusOverlayInput = Mock()
        self.delegate.settings.boolForKey_.return_value = False
        with patch.object(app, "NSApp"):
            self.delegate.showWindow_(None)

        self.delegate.window_manifestation.begin.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()
        self.delegate.window.makeKeyAndOrderFront_.assert_called_once_with(None)
        self.delegate.focusOverlayInput.assert_called_once_with()

    def test_showing_failed_initial_load_retries(self):
        self.delegate._move_window_to_cursor_screen = Mock()
        self.delegate.updateAuthSessionForMainWebView = Mock()
        self.delegate.focusOverlayInput = Mock()
        self.delegate._webview_needs_reload = True
        with patch.object(app, "NSApp"):
            self.delegate.showWindow_(None)

        request = self.delegate.webview.loadRequest_.call_args.args[0]
        self.assertEqual(request.URL().absoluteString(), app.WEBSITE)
        self.assertFalse(self.delegate._webview_needs_reload)

    def test_hidden_preserved_chat_navigation_is_allowed(self):
        self.delegate.window.isVisible.return_value = False
        action = Mock()
        action.request.return_value.URL.return_value = NSURL.URLWithString_("https://grok.com/c/example")
        navigation = auth_browser.WebNavigationDelegate.alloc().initWithAppDelegate_(self.delegate)

        result = navigation._navigation_policy_for_action(self.delegate.webview, action)

        self.assertEqual(result, WKNavigationActionPolicyAllow)

    def test_hidden_pending_retry_navigation_is_allowed(self):
        self.delegate.window.isVisible.return_value = False
        self.delegate._webview_needs_reload = True
        action = Mock()
        action.request.return_value.URL.return_value = NSURL.URLWithString_(app.WEBSITE)
        navigation = auth_browser.WebNavigationDelegate.alloc().initWithAppDelegate_(self.delegate)

        result = navigation._navigation_policy_for_action(self.delegate.webview, action)

        self.assertEqual(result, WKNavigationActionPolicyAllow)


if __name__ == "__main__":
    unittest.main()
