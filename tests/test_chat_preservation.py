import unittest
from contextlib import ExitStack
from unittest.mock import Mock, mock_open, patch

from Foundation import NSURL
from WebKit import WKNavigationActionPolicyAllow, WKNavigationActionPolicyCancel, WKNavigationTypeLinkActivated

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
        self.delegate.auth_browser = Mock()
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

    def test_external_popup_opens_browser_without_resetting_chat(self):
        url = NSURL.URLWithString_("https://example.com/source")
        action = Mock()
        action.targetFrame.return_value = None
        action.request.return_value.URL.return_value = url
        self.delegate.loadOverlayHomePage_ = Mock()
        ui_delegate = auth_browser.WebUIDelegate.alloc().initWithAppDelegate_(self.delegate)

        result = ui_delegate.webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
            self.delegate.webview, None, action, None
        )

        self.assertIsNone(result)
        self.delegate.auth_browser.open_link_in_browser.assert_called_once_with(url)
        self.delegate.auth_browser.handle_user_auth_request.assert_not_called()
        self.delegate.loadOverlayHomePage_.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()

    def test_external_main_frame_link_opens_browser_without_resetting_chat(self):
        url = NSURL.URLWithString_("https://example.com/source")
        action = Mock()
        action.targetFrame.return_value.isMainFrame.return_value = True
        action.navigationType.return_value = WKNavigationTypeLinkActivated
        action.request.return_value.URL.return_value = url
        self.delegate.loadOverlayHomePage_ = Mock()
        navigation = auth_browser.WebNavigationDelegate.alloc().initWithAppDelegate_(self.delegate)

        result = navigation._navigation_policy_for_action(self.delegate.webview, action)

        self.assertEqual(result, WKNavigationActionPolicyCancel)
        self.delegate.auth_browser.open_link_in_browser.assert_called_once_with(url)
        self.delegate.auth_browser.handle_user_auth_request.assert_not_called()
        self.delegate.loadOverlayHomePage_.assert_not_called()
        self.delegate.webview.loadRequest_.assert_not_called()

    def test_grok_popup_navigates_in_overlay(self):
        action = Mock()
        action.targetFrame.return_value = None
        action.request.return_value.URL.return_value = NSURL.URLWithString_("https://grok.com/c/example")
        ui_delegate = auth_browser.WebUIDelegate.alloc().initWithAppDelegate_(self.delegate)

        ui_delegate.webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
            self.delegate.webview, None, action, None
        )

        self.delegate.webview.loadRequest_.assert_called_once_with(action.request.return_value)
        self.delegate.auth_browser.open_link_in_browser.assert_not_called()
        self.delegate.auth_browser.handle_user_auth_request.assert_not_called()

    def test_auth_popup_preserves_browser_sign_in_flow(self):
        action = Mock()
        action.targetFrame.return_value = None
        action.request.return_value.URL.return_value = NSURL.URLWithString_("https://accounts.google.com/signin")
        ui_delegate = auth_browser.WebUIDelegate.alloc().initWithAppDelegate_(self.delegate)

        ui_delegate.webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
            self.delegate.webview, None, action, None
        )

        self.delegate.auth_browser.handle_user_auth_request.assert_called_once_with(restore_overlay=True)
        self.delegate.auth_browser.open_link_in_browser.assert_not_called()

    def test_x_posts_are_not_sign_in_links(self):
        self.assertFalse(auth_browser.is_external_auth_url("https://x.com/example/status/123"))
        self.assertFalse(auth_browser.is_external_auth_url("https://twitter.com/example/status/123"))
        self.assertTrue(auth_browser.is_external_auth_url("https://x.com/i/oauth2/authorize"))

    def test_open_in_grok_passes_current_chat_without_reloading_overlay(self):
        url = NSURL.URLWithString_("https://grok.com/c/example?source=overlay")
        self.delegate.webview.URL.return_value = url

        self.delegate.openInGrok_(None)

        self.delegate.auth_browser.open_in_grok.assert_called_once_with(url)
        self.delegate.webview.loadRequest_.assert_not_called()

    def test_shared_chrome_app_launch_uses_registered_profile_and_chat_url(self):
        url = NSURL.URLWithString_("https://grok.com/c/example?source=overlay")
        app_id = "test-grok-app"
        info = {
            "CrBundleIdentifier": "com.google.Chrome",
            "CrAppModeShortcutURL": "https://grok.com/",
            "CrAppModeShortcutID": app_id,
            "CrAppModeUserDataDir": f"/test/Chrome/-/Web Applications/_crx_{app_id}",
        }
        state = {"app_shims": {app_id: {"installed_profiles": ["Profile 2"]}}}
        manager = auth_browser.AuthBrowserManager(self.delegate)
        with ExitStack() as contexts:
            contexts.enter_context(patch.object(auth_browser.glob, "glob", return_value=["/test/Grok.app"]))
            contexts.enter_context(patch.object(auth_browser, "open", mock_open(), create=True))
            contexts.enter_context(patch.object(auth_browser.plistlib, "load", return_value=info))
            contexts.enter_context(patch.object(auth_browser.json, "load", return_value=state))
            workspace_class = contexts.enter_context(patch.object(auth_browser, "NSWorkspace"))
            configuration_class = contexts.enter_context(patch.object(auth_browser, "NSWorkspaceOpenConfiguration"))
            alert = contexts.enter_context(patch.object(auth_browser, "NSAlert"))
            workspace = workspace_class.sharedWorkspace.return_value
            chrome_url = NSURL.fileURLWithPath_("/Applications/Google Chrome.app")
            workspace.URLForApplicationWithBundleIdentifier_.return_value = chrome_url

            manager.open_in_grok(url)

            configuration = configuration_class.configuration.return_value
            configuration.setArguments_.assert_called_once_with([
                "--user-data-dir=/test/Chrome",
                "--profile-directory=Profile 2",
                f"--app-id={app_id}",
                f"--app-launch-url-for-shortcuts-menu-item={url.absoluteString()}",
            ])
            configuration.setCreatesNewApplicationInstance_.assert_called_once_with(True)
            launch = workspace.openApplicationAtURL_configuration_completionHandler_
            launch.assert_called_once()
            self.assertEqual(launch.call_args.args[:2], (chrome_url, configuration))
            workspace.openURLs_withApplicationAtURL_configuration_completionHandler_.assert_not_called()
            alert.alloc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
