import AppKit
import QuartzCore

class EmojiAnimator {
    private let hostLayer: CALayer

    init(hostLayer: CALayer) {
        self.hostLayer = hostLayer
    }

    func spawnEmoji(_ emoji: String = "❤️") {
        let bounds = hostLayer.bounds

        // Spawn in bottom-right area with ±50pt random horizontal offset
        let baseX = bounds.maxX - 100
        let offsetX = CGFloat.random(in: -50...50)
        let spawnY: CGFloat = 80  // near bottom in layer coords (origin bottom-left)

        let layer = CATextLayer()
        layer.string = emoji
        layer.fontSize = 40
        layer.alignmentMode = .center
        layer.frame = CGRect(x: baseX + offsetX - 25, y: spawnY, width: 50, height: 50)
        layer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        hostLayer.addSublayer(layer)

        // Animate: float up 300pt + fade out, 2 seconds
        let moveUp = CABasicAnimation(keyPath: "position.y")
        moveUp.toValue = layer.position.y + 300

        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.toValue = 0.0

        let group = CAAnimationGroup()
        group.animations = [moveUp, fadeOut]
        group.duration = 2.0
        group.fillMode = .forwards
        group.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak layer] in
            layer?.removeFromSuperlayer()
        }
        layer.add(group, forKey: "floatAndFade")
        CATransaction.commit()
    }
}
