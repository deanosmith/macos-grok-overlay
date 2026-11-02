import math
import random

import objc
from AppKit import (
    NSColor,
    NSMakeRect,
    NSView,
    NSWorkspace,
    NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification,
)
from Foundation import NSObject
from Quartz import (
    CAAnimationGroup,
    CAKeyframeAnimation,
    CALayer,
    CAShapeLayer,
    CATransaction,
    CACurrentMediaTime,
    CGAffineTransformMake,
    CGPathAddLineToPoint,
    CGPathCreateMutable,
    CGPathCreateWithRoundedRect,
    CGPathMoveToPoint,
    kCAAnimationPaced,
    kCAFillModeBackwards,
    kCALineCapRound,
    kCALineJoinRound,
)

from .constants import CORNER_RADIUS


class ParticleOverlay(NSView):
    def hitTest_(self, point):
        return None


class WindowManifestation(NSObject):
    def initWithWindow_(self, window):
        self = objc.super(WindowManifestation, self).init()
        if self is None:
            return None
        self._window = window
        self._mask = None
        self._sparks = None
        self._overlay = None
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

        columns = 12
        rows = max(8, min(16, round(height / width * columns)))
        tile_width, tile_height = width / columns, height / rows
        diameter = math.hypot(tile_width, tile_height) + 2
        tip_stretch = 2.0
        self._layer = layer
        self._previous_mask = layer.mask()
        self._had_shadow = self._window.hasShadow()
        self._mask = CALayer.layer()
        self._mask.setFrame_(bounds)
        clip = CAShapeLayer.layer()
        clip.setPath_(CGPathCreateWithRoundedRect(bounds, CORNER_RADIUS, CORNER_RADIUS, None))
        self._mask.setMask_(clip)
        self._overlay = ParticleOverlay.alloc().initWithFrame_(bounds)
        self._overlay.setWantsLayer_(True)
        self._sparks = self._overlay.layer()
        generation = self._generation

        def completed():
            if generation == self._generation:
                self.finish()

        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        CATransaction.setCompletionBlock_(completed)
        self._window.setHasShadow_(False)
        layer.setMask_(self._mask)
        self._window.contentView().addSubview_(self._overlay)
        now = CACurrentMediaTime()
        rng = random.Random(18)
        emission_order = list(range(rows * columns))
        rng.shuffle(emission_order)
        timings = [
            (order * 1.6 / len(emission_order), rng.uniform(1.6, 1.8))
            for order in emission_order
        ]
        time_scale = 1.8 / max(delay + duration for delay, duration in timings)
        mask_color = NSColor.whiteColor().CGColor()
        spark_color = NSColor.colorWithCalibratedWhite_alpha_(0.65, 1).CGColor()
        # Core Animation interpolates these fixed paths; no Python frame loop or timer.
        for row in range(rows):
            for column in range(columns):
                target_x = (column + 0.5) * tile_width
                target_y = (row + 0.5) * tile_height
                angle = math.atan2(target_y - height / 2, target_x - width / 2)
                direction_x, direction_y = math.cos(angle), math.sin(angle)
                tip_x = target_x + direction_x * diameter
                tip_y = target_y + direction_y * diameter
                path = CGPathCreateMutable()
                CGPathMoveToPoint(path, None, width / 2, height / 2)
                CGPathAddLineToPoint(path, None, tip_x, tip_y)
                delay, duration = timings[row * columns + column]
                delay *= time_scale
                duration *= time_scale
                motion = CAKeyframeAnimation.animationWithKeyPath_("position")
                motion.setPath_(path)
                motion.setCalculationMode_(kCAAnimationPaced)
                motion.setDuration_(duration)

                # Reveal the live window through growing particles, not a captured image.
                wake_path = CGPathCreateMutable()
                CGPathMoveToPoint(wake_path, None, width / 2, height / 2)
                CGPathAddLineToPoint(
                    wake_path, None,
                    width / 2 + (tip_x - width / 2) / tip_stretch - direction_x * diameter / 2,
                    height / 2 + (tip_y - height / 2) / tip_stretch - direction_y * diameter / 2,
                )
                cell = CAShapeLayer.layer()
                cell.setFrame_(bounds)
                # Taper the round cap along travel without letting it overtake its particle.
                cell.setAffineTransform_(CGAffineTransformMake(
                    1 + (tip_stretch - 1) * direction_x * direction_x,
                    (tip_stretch - 1) * direction_x * direction_y,
                    (tip_stretch - 1) * direction_x * direction_y,
                    1 + (tip_stretch - 1) * direction_y * direction_y,
                    0, 0,
                ))
                cell.setPath_(wake_path)
                cell.setFillColor_(NSColor.clearColor().CGColor())
                cell.setStrokeColor_(mask_color)
                cell.setLineCap_(kCALineCapRound)
                cell.setLineJoin_(kCALineJoinRound)
                cell.setLineWidth_(diameter)
                self._mask.addSublayer_(cell)
                growth = CAKeyframeAnimation.animationWithKeyPath_("strokeEnd")
                growth.setValues_([0, 1])
                growth.setKeyTimes_([0, 1])
                spread = CAKeyframeAnimation.animationWithKeyPath_("lineWidth")
                spread.setValues_([3 / tip_stretch, diameter])
                spread.setKeyTimes_([0, 1])
                opacity = CAKeyframeAnimation.animationWithKeyPath_("opacity")
                opacity.setValues_([0, 1, 1])
                opacity.setKeyTimes_([0, 0.12, 1])
                for animation in (growth, spread, opacity):
                    animation.setDuration_(duration)
                assembly = CAAnimationGroup.animation()
                assembly.setAnimations_([growth, spread, opacity])
                assembly.setBeginTime_(now + delay)
                assembly.setDuration_(duration)
                assembly.setFillMode_(kCAFillModeBackwards)
                cell.addAnimation_forKey_(assembly, "manifest")

                spark = CALayer.layer()
                spark.setBounds_(NSMakeRect(0, 0, 3, 3))
                spark.setCornerRadius_(1.5)
                spark.setPosition_((tip_x, tip_y))
                spark.setBackgroundColor_(spark_color)
                spark.setOpacity_(0)
                self._sparks.addSublayer_(spark)
                shimmer = CAKeyframeAnimation.animationWithKeyPath_("opacity")
                shimmer.setValues_([0, 0.95, 0.7, 0])
                shimmer.setKeyTimes_([0, 0.12, 0.98, 1])
                shimmer.setDuration_(duration)
                glint = CAAnimationGroup.animation()
                glint.setAnimations_([motion, shimmer])
                glint.setBeginTime_(now + delay)
                glint.setDuration_(duration)
                glint.setFillMode_(kCAFillModeBackwards)
                spark.addAnimation_forKey_(glint, "manifest")
        CATransaction.commit()

    @objc.python_method
    def finish(self):
        self._generation += 1
        if self._mask is None:
            return
        mask, sparks = self._mask, self._sparks
        self._mask = None
        self._sparks = None
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._layer.setMask_(self._previous_mask)
        self._overlay.removeFromSuperview()
        self._overlay = None
        for container in (mask, sparks):
            for child in container.sublayers() or ():
                child.removeAllAnimations()
            container.setSublayers_(None)
        self._window.setHasShadow_(self._had_shadow)
        self._window.invalidateShadow()
        self._layer = None
        self._previous_mask = None
        CATransaction.commit()

    def accessibilityDisplayOptionsChanged_(self, notification):
        if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion():
            self.finish()
