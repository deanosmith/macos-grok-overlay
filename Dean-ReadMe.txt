
To install it to launch at login:
- source ...
- env/bin/macos-grok-overlay --install-startup



launchctl kickstart -kp "gui/$(id -u)/com.$(id -un).macosgrokoverlay"