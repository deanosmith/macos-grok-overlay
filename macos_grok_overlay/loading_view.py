import objc
from AppKit import (
    NSColor,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
)


class LoadingView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(LoadingView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.setWantsLayer_(True)
        self.layer().setBackgroundColor_(NSColor.blackColor().CGColor())
        return self
