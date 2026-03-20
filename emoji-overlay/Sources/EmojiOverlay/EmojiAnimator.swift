import AppKit
import QuartzCore

class EmojiAnimator {
    private let hostLayer: CALayer

    static let emojiSet = ["❤️", "🔥", "👏", "😂", "🤯", "💡", "☕"]

    init(hostLayer: CALayer) {
        self.hostLayer = hostLayer
    }

    func spawnEmoji(_ emoji: String = "❤️") {
        let bounds = hostLayer.bounds

        // Fixed spawn point: 200pt from right edge, near bottom
        let spawnX = bounds.maxX - 200
        let spawnY: CGFloat = 80

        let layer = CATextLayer()
        layer.string = emoji
        layer.fontSize = 78
        layer.alignmentMode = .center
        layer.frame = CGRect(x: spawnX - 45, y: spawnY, width: 91, height: 91)
        layer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        hostLayer.addSublayer(layer)

        // Randomize duration: 2.5–4 seconds
        let duration = Double.random(in: 2.5...4.0)
        let riseHeight: CGFloat = 540

        // Randomly pick animation style
        let style = Int.random(in: 0...2)

        var animations: [CAAnimation] = []

        switch style {
        case 0:
            // Curved path (bezier S-shape)
            let path = CGMutablePath()
            let startPoint = layer.position
            let endPoint = CGPoint(x: startPoint.x + CGFloat.random(in: -60...60),
                                   y: startPoint.y + riseHeight)
            let cp1 = CGPoint(x: startPoint.x + CGFloat.random(in: -80...80),
                              y: startPoint.y + riseHeight * 0.33)
            let cp2 = CGPoint(x: endPoint.x + CGFloat.random(in: -80...80),
                              y: startPoint.y + riseHeight * 0.73)
            path.move(to: startPoint)
            path.addCurve(to: endPoint, control1: cp1, control2: cp2)

            let pathAnim = CAKeyframeAnimation(keyPath: "position")
            pathAnim.path = path
            pathAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)
            animations.append(pathAnim)

        case 1:
            // Ease-out straight rise
            let moveUp = CABasicAnimation(keyPath: "position.y")
            moveUp.toValue = layer.position.y + riseHeight
            moveUp.timingFunction = CAMediaTimingFunction(name: .easeOut)
            animations.append(moveUp)

        default:
            // Curved path + ease-out combined
            let path = CGMutablePath()
            let startPoint = layer.position
            let endPoint = CGPoint(x: startPoint.x + CGFloat.random(in: -40...40),
                                   y: startPoint.y + riseHeight)
            let cp1 = CGPoint(x: startPoint.x + CGFloat.random(in: -100...100),
                              y: startPoint.y + riseHeight * 0.5)
            path.move(to: startPoint)
            path.addQuadCurve(to: endPoint, control: cp1)

            let pathAnim = CAKeyframeAnimation(keyPath: "position")
            pathAnim.path = path
            pathAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)
            animations.append(pathAnim)
        }

        // Fade out (start fading at 60% of duration)
        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.fromValue = 1.0
        fadeOut.toValue = 0.0
        fadeOut.beginTime = duration * 0.4
        fadeOut.duration = duration * 0.6
        fadeOut.fillMode = .forwards
        animations.append(fadeOut)

        let group = CAAnimationGroup()
        group.animations = animations
        group.duration = duration
        group.fillMode = .forwards
        group.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak layer] in
            layer?.removeFromSuperlayer()
        }
        layer.add(group, forKey: "floatAndFade")
        CATransaction.commit()
    }

    func spawnRandomEmoji() {
        spawnEmoji(EmojiAnimator.emojiSet.randomElement()!)
    }
}
