import objc
from AppKit import (
    NSWorkspace,
    NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification,
)
from Foundation import NSObject, NSValue
from Quartz import (
    CAAnimationGroup,
    CABasicAnimation,
    CAMediaTimingFunction,
    CATransaction,
    CGAffineTransformMake,
    CATransform3DConcat,
    CATransform3DMakeAffineTransform,
)


class WindowManifestation(NSObject):
    def initWithWindow_(self, window):
        self = objc.super(WindowManifestation, self).init()
        if self is None:
            return None
        self._window = window
        self._layer = None
        self._generation = 0
        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self, "accessibilityDisplayOptionsChanged:",
            NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification, None
        )
        return self

    @objc.python_method
    def begin(self):
        self.finish()
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion():
            return
        layer = self._window.contentView().layer()
        bounds = layer.bounds()
        width, height = bounds.size.width, bounds.size.height
        if width <= 0 or height <= 0:
            print("Unable to animate the overlay: its window has empty bounds.", flush=True)
            return

        self._layer = layer
        generation = self._generation

        def completed():
            if generation == self._generation:
                self.finish()

        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        CATransaction.setCompletionBlock_(completed)
        # Keep the gentle scale centred even on AppKit's non-centred layer anchors.
        scale = 0.985
        anchor = layer.anchorPoint()
        start = CATransform3DMakeAffineTransform(CGAffineTransformMake(
            scale, 0, 0, scale,
            width * (0.5 - anchor.x) * (1 - scale),
            height * (0.5 - anchor.y) * (1 - scale),
        ))
        settle = CABasicAnimation.animationWithKeyPath_("transform")
        settle.setFromValue_(NSValue.valueWithCATransform3D_(
            CATransform3DConcat(start, layer.transform())
        ))
        settle.setToValue_(NSValue.valueWithCATransform3D_(layer.transform()))

        # Reveal the live window directly, not a captured image.
        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0)
        fade.setToValue_(layer.opacity())
        # Core Animation interpolates the live layer; no Python frame loop or timer.
        appearance = CAAnimationGroup.animation()
        appearance.setAnimations_([settle, fade])
        appearance.setDuration_(0.18)
        appearance.setTimingFunction_(
            CAMediaTimingFunction.functionWithControlPoints____(0.16, 1, 0.3, 1)
        )
        layer.addAnimation_forKey_(appearance, "manifest")
        CATransaction.commit()

    @objc.python_method
    def finish(self):
        self._generation += 1
        if self._layer is None:
            return
        self._layer.removeAnimationForKey_("manifest")
        self._layer = None

    def accessibilityDisplayOptionsChanged_(self, notification):
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion():
            self.finish()
