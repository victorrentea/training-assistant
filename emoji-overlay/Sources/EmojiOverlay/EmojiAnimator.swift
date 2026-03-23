import AppKit
import QuartzCore

class EmojiAnimator {
    private let hostLayer: CALayer

    static let emojiSet = ["❤️", "🔥", "👏", "😂", "🤯", "💡", "☕", "✅", "❌"]

    init(hostLayer: CALayer) {
        self.hostLayer = hostLayer
    }

    func spawnEmoji(_ emoji: String = "❤️") {
        let bounds = hostLayer.bounds

        // Fixed spawn point: left-bottom corner
        let spawnX: CGFloat = 100
        let spawnY: CGFloat = 80

        let layer = CATextLayer()
        layer.string = emoji
        layer.fontSize = 78
        layer.alignmentMode = .center
        layer.frame = CGRect(x: spawnX - 45, y: spawnY, width: 91, height: 91)
        layer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        hostLayer.addSublayer(layer)

        // Randomize duration: 2.5–4 seconds (matches browser host.js)
        let duration = Double.random(in: 2.5...4.0)
        let riseHeight: CGFloat = 540

        var animations: [CAAnimation] = []

        // Rise with wobble (matches browser's sinusoidal wobble)
        let wobbleAmp = CGFloat.random(in: 15...25)
        let wobbleFreq = CGFloat.random(in: 3...5)
        let steps = 20
        let startPoint = layer.position

        let path = CGMutablePath()
        path.move(to: startPoint)
        for i in 1...steps {
            let t = CGFloat(i) / CGFloat(steps)
            let y = startPoint.y + riseHeight * t
            let wobble = sin(t * wobbleFreq * .pi * 2) * wobbleAmp * (1 - t * 0.5)
            path.addLine(to: CGPoint(x: startPoint.x + wobble, y: y))
        }

        let pathAnim = CAKeyframeAnimation(keyPath: "position")
        pathAnim.path = path
        pathAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)
        animations.append(pathAnim)

        // Scale growth (1.0 → 1.3, matches browser)
        let scaleAnim = CABasicAnimation(keyPath: "transform.scale")
        scaleAnim.fromValue = 1.0
        scaleAnim.toValue = 1.3
        scaleAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)
        animations.append(scaleAnim)

        // Fade out (start fading at 40% of duration, matches browser)
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

    // MARK: - Confetti burst

    private static let confettiColors: [NSColor] = [
        .systemRed, .systemOrange, .systemYellow, .systemGreen,
        .systemBlue, .systemPurple, .systemPink, .systemTeal,
    ]

    // MARK: - Screen vignette effects

    /// Radial gradient vignette that pulses then fades — used for danger/success moods.
    func showVignette(color: NSColor, duration: Double = 2.5, pulses: Int = 2) {
        let bounds = hostLayer.bounds

        let vignetteLayer = CALayer()
        vignetteLayer.frame = bounds
        vignetteLayer.opacity = 0

        // Build radial gradient: transparent center → colored edges
        let gradientLayer = CAGradientLayer()
        gradientLayer.type = .radial
        gradientLayer.frame = bounds
        gradientLayer.colors = [
            NSColor.clear.cgColor,
            color.withAlphaComponent(0.0).cgColor,
            color.withAlphaComponent(0.35).cgColor,
            color.withAlphaComponent(0.7).cgColor,
        ]
        gradientLayer.locations = [0.0, 0.35, 0.7, 1.0]
        gradientLayer.startPoint = CGPoint(x: 0.5, y: 0.5)
        gradientLayer.endPoint = CGPoint(x: 1.0, y: 1.0)

        vignetteLayer.addSublayer(gradientLayer)
        hostLayer.addSublayer(vignetteLayer)

        // Pulse in, hold, fade out
        let pulseDuration = duration / Double(pulses * 2 + 1)
        let fadeIn = CABasicAnimation(keyPath: "opacity")
        fadeIn.fromValue = 0.0
        fadeIn.toValue = 1.0
        fadeIn.duration = pulseDuration
        fadeIn.autoreverses = true
        fadeIn.repeatCount = Float(pulses)

        let totalPulse = pulseDuration * 2 * Double(pulses)
        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.fromValue = 0.8
        fadeOut.toValue = 0.0
        fadeOut.beginTime = totalPulse
        fadeOut.duration = duration - totalPulse
        fadeOut.fillMode = .forwards

        let group = CAAnimationGroup()
        group.animations = [fadeIn, fadeOut]
        group.duration = duration
        group.fillMode = .forwards
        group.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak vignetteLayer] in
            vignetteLayer?.removeFromSuperlayer()
        }
        vignetteLayer.add(group, forKey: "vignette")
        CATransaction.commit()
    }

    func showDanger() {
        showVignette(color: .systemRed, duration: 3.0, pulses: 3)
    }

    // MARK: - Earthquake (screen shake + cracks + blackout)

    func showEarthquake() {
        let bounds = hostLayer.bounds
        let totalDuration = 3.5

        // Container for all earthquake layers
        let container = CALayer()
        container.frame = bounds
        hostLayer.addSublayer(container)

        // 1. Screen shake — rapid position oscillation on the host layer
        let shakeAnim = CAKeyframeAnimation(keyPath: "position")
        let center = CGPoint(x: bounds.midX, y: bounds.midY)
        var shakePoints: [NSValue] = []
        let shakeSteps = 30
        for i in 0..<shakeSteps {
            let t = Double(i) / Double(shakeSteps)
            let intensity: CGFloat = CGFloat(1.0 - t * 0.7) * 12 // decay
            let dx = CGFloat.random(in: -intensity...intensity)
            let dy = CGFloat.random(in: -intensity...intensity)
            shakePoints.append(NSValue(point: CGPoint(x: center.x + dx, y: center.y + dy)))
        }
        shakePoints.append(NSValue(point: center)) // return to center
        shakeAnim.values = shakePoints
        shakeAnim.duration = 1.5
        hostLayer.add(shakeAnim, forKey: "shake")

        // 2. Crack lines — draw branching cracks from impact point
        let impactPoint = CGPoint(
            x: bounds.width * CGFloat.random(in: 0.3...0.7),
            y: bounds.height * CGFloat.random(in: 0.3...0.7)
        )

        for _ in 0..<8 {
            let crackPath = CGMutablePath()
            crackPath.move(to: impactPoint)

            var currentPoint = impactPoint
            let segments = Int.random(in: 5...10)
            let angle = CGFloat.random(in: 0...(2 * .pi))

            for j in 0..<segments {
                let segLen = CGFloat.random(in: 40...120)
                let jitter = CGFloat.random(in: -0.5...0.5)
                let dir = angle + jitter
                let nextPoint = CGPoint(
                    x: currentPoint.x + cos(dir) * segLen,
                    y: currentPoint.y + sin(dir) * segLen
                )
                crackPath.addLine(to: nextPoint)
                currentPoint = nextPoint

                // Branch occasionally
                if Bool.random() && j > 1 {
                    let branchPath = CGMutablePath()
                    branchPath.move(to: currentPoint)
                    let branchAngle = dir + CGFloat.random(in: -1.0...1.0)
                    let branchLen = CGFloat.random(in: 30...80)
                    branchPath.addLine(to: CGPoint(
                        x: currentPoint.x + cos(branchAngle) * branchLen,
                        y: currentPoint.y + sin(branchAngle) * branchLen
                    ))
                    let branchLayer = CAShapeLayer()
                    branchLayer.path = branchPath
                    branchLayer.strokeColor = NSColor.white.cgColor
                    branchLayer.lineWidth = CGFloat.random(in: 1...2)
                    branchLayer.fillColor = nil
                    branchLayer.strokeEnd = 0
                    container.addSublayer(branchLayer)

                    let draw = CABasicAnimation(keyPath: "strokeEnd")
                    draw.fromValue = 0
                    draw.toValue = 1
                    draw.beginTime = CACurrentMediaTime() + 0.3 + Double(j) * 0.08
                    draw.duration = 0.15
                    draw.fillMode = .forwards
                    draw.isRemovedOnCompletion = false
                    branchLayer.add(draw, forKey: "draw")
                }
            }

            let crackLayer = CAShapeLayer()
            crackLayer.path = crackPath
            crackLayer.strokeColor = NSColor.white.cgColor
            crackLayer.lineWidth = CGFloat.random(in: 2...4)
            crackLayer.fillColor = nil
            crackLayer.lineCap = .round
            crackLayer.lineJoin = .round
            crackLayer.strokeEnd = 0
            crackLayer.shadowColor = NSColor.white.cgColor
            crackLayer.shadowOffset = .zero
            crackLayer.shadowRadius = 3
            crackLayer.shadowOpacity = 0.8
            container.addSublayer(crackLayer)

            // Animate crack drawing
            let drawCrack = CABasicAnimation(keyPath: "strokeEnd")
            drawCrack.fromValue = 0
            drawCrack.toValue = 1
            drawCrack.beginTime = CACurrentMediaTime() + Double.random(in: 0.1...0.5)
            drawCrack.duration = Double.random(in: 0.3...0.8)
            drawCrack.fillMode = .forwards
            drawCrack.isRemovedOnCompletion = false
            crackLayer.add(drawCrack, forKey: "draw")
        }

        // 3. Brief blackout flash then recovery
        let blackout = CALayer()
        blackout.frame = bounds
        blackout.backgroundColor = NSColor.black.cgColor
        blackout.opacity = 0
        container.addSublayer(blackout)

        let flash = CAKeyframeAnimation(keyPath: "opacity")
        flash.values = [0, 0, 0.8, 0.9, 0.6, 0.85, 0]
        flash.keyTimes = [0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
        flash.duration = totalDuration
        flash.fillMode = .forwards
        flash.isRemovedOnCompletion = false
        blackout.add(flash, forKey: "blackout")

        // 4. Cleanup
        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 0.2) { [weak container] in
            container?.removeFromSuperlayer()
        }
    }

    // MARK: - Film burn (multiple burn holes consuming the screen)

    func showFilmBurn() {
        let bounds = hostLayer.bounds
        let totalDuration = 4.0

        let container = CALayer()
        container.frame = bounds
        hostLayer.addSublayer(container)

        // Burn points scattered across the screen
        let burnPoints: [CGPoint] = [
            CGPoint(x: bounds.width * 0.25, y: bounds.height * 0.7),
            CGPoint(x: bounds.width * 0.7,  y: bounds.height * 0.55),
            CGPoint(x: bounds.width * 0.45, y: bounds.height * 0.25),
            CGPoint(x: bounds.width * 0.8,  y: bounds.height * 0.85),
        ]

        // Each burn hole starts at a staggered time and expands
        for (i, center) in burnPoints.enumerated() {
            let startDelay = Double(i) * 0.35
            let maxRadius = max(bounds.width, bounds.height) * 0.6

            let smallRect = CGRect(x: center.x - 3, y: center.y - 3, width: 6, height: 6)
            let bigRect = CGRect(
                x: center.x - maxRadius, y: center.y - maxRadius,
                width: maxRadius * 2, height: maxRadius * 2
            )
            let smallCircle = CGPath(ellipseIn: smallRect, transform: nil)
            let bigCircle = CGPath(ellipseIn: bigRect, transform: nil)

            // Black fill (the burnt-away area)
            let fillLayer = CAShapeLayer()
            fillLayer.path = smallCircle
            fillLayer.fillColor = NSColor.black.cgColor
            fillLayer.opacity = 0
            container.addSublayer(fillLayer)

            let fillExpand = CABasicAnimation(keyPath: "path")
            fillExpand.fromValue = smallCircle
            fillExpand.toValue = bigCircle
            fillExpand.beginTime = startDelay + 0.15
            fillExpand.duration = 1.8
            fillExpand.timingFunction = CAMediaTimingFunction(name: .easeIn)
            fillExpand.fillMode = .both
            fillExpand.isRemovedOnCompletion = false

            let fillAppear = CABasicAnimation(keyPath: "opacity")
            fillAppear.fromValue = 0
            fillAppear.toValue = 0.95
            fillAppear.beginTime = startDelay + 0.1
            fillAppear.duration = 0.2
            fillAppear.fillMode = .both
            fillAppear.isRemovedOnCompletion = false

            let fillGroup = CAAnimationGroup()
            fillGroup.animations = [fillExpand, fillAppear]
            fillGroup.duration = totalDuration
            fillGroup.fillMode = .forwards
            fillGroup.isRemovedOnCompletion = false
            fillLayer.add(fillGroup, forKey: "fill")

            // Glowing orange ring (the burning edge)
            let ringLayer = CAShapeLayer()
            ringLayer.path = smallCircle
            ringLayer.fillColor = nil
            ringLayer.strokeColor = NSColor(red: 1.0, green: 0.4, blue: 0.0, alpha: 0.95).cgColor
            ringLayer.lineWidth = 20
            ringLayer.shadowColor = NSColor.orange.cgColor
            ringLayer.shadowOffset = .zero
            ringLayer.shadowRadius = 15
            ringLayer.shadowOpacity = 1.0
            ringLayer.opacity = 0
            container.addSublayer(ringLayer)

            let ringExpand = CABasicAnimation(keyPath: "path")
            ringExpand.fromValue = smallCircle
            ringExpand.toValue = bigCircle
            ringExpand.beginTime = startDelay
            ringExpand.duration = 2.0
            ringExpand.timingFunction = CAMediaTimingFunction(name: .easeIn)
            ringExpand.fillMode = .both
            ringExpand.isRemovedOnCompletion = false

            let ringAppear = CABasicAnimation(keyPath: "opacity")
            ringAppear.fromValue = 0
            ringAppear.toValue = 1
            ringAppear.beginTime = startDelay
            ringAppear.duration = 0.1
            ringAppear.fillMode = .both
            ringAppear.isRemovedOnCompletion = false

            // Flicker the ring width for realism
            let flicker = CAKeyframeAnimation(keyPath: "lineWidth")
            flicker.values = [20, 28, 16, 32, 18, 26, 22, 14]
            flicker.duration = 0.3
            flicker.repeatCount = .infinity

            let ringGroup = CAAnimationGroup()
            ringGroup.animations = [ringExpand, ringAppear, flicker]
            ringGroup.duration = totalDuration
            ringGroup.fillMode = .forwards
            ringGroup.isRemovedOnCompletion = false
            ringLayer.add(ringGroup, forKey: "ring")
        }

        // Fade everything out at the end
        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.fromValue = 1.0
        fadeOut.toValue = 0.0
        fadeOut.beginTime = totalDuration - 0.8
        fadeOut.duration = 0.8
        fadeOut.fillMode = .forwards
        fadeOut.isRemovedOnCompletion = false
        container.add(fadeOut, forKey: "fadeAll")

        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 0.2) { [weak container] in
            container?.removeFromSuperlayer()
        }
    }

    // MARK: - Confetti burst

    func spawnConfetti(count: Int = 80) {
        let bounds = hostLayer.bounds
        let screenW = bounds.width
        let screenH = bounds.height
        let scale = NSScreen.screens.first?.backingScaleFactor ?? 2.0

        for i in 0..<count {
            let delay = Double(i) * 0.012 // stagger over ~1s

            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self = self else { return }

                let color = EmojiAnimator.confettiColors.randomElement()!
                let layer = CALayer()

                // Larger confetti pieces
                let w = CGFloat.random(in: 14...26)
                let h = CGFloat.random(in: 8...26)
                let startX = CGFloat.random(in: 0...screenW)
                let startY = screenH + 20 // start above top edge

                layer.frame = CGRect(x: startX, y: startY, width: w, height: h)
                layer.backgroundColor = color.cgColor
                layer.cornerRadius = Bool.random() ? w / 2 : 1 // round or rectangular
                layer.contentsScale = scale
                self.hostLayer.addSublayer(layer)

                let duration = Double.random(in: 2.5...4.5)

                // Fall down with horizontal drift
                let endY: CGFloat = -30
                let drift = CGFloat.random(in: -200...200)

                let path = CGMutablePath()
                let start = layer.position
                let end = CGPoint(x: start.x + drift, y: endY)
                let cp1 = CGPoint(x: start.x + drift * 0.3 + CGFloat.random(in: -80...80),
                                  y: start.y - (start.y - endY) * 0.3)
                let cp2 = CGPoint(x: end.x + CGFloat.random(in: -60...60),
                                  y: start.y - (start.y - endY) * 0.7)
                path.move(to: start)
                path.addCurve(to: end, control1: cp1, control2: cp2)

                let pathAnim = CAKeyframeAnimation(keyPath: "position")
                pathAnim.path = path
                pathAnim.timingFunction = CAMediaTimingFunction(name: .easeIn)

                // Spin
                let spin = CABasicAnimation(keyPath: "transform.rotation.z")
                spin.fromValue = 0
                spin.toValue = Double.random(in: -6...6) * .pi

                // Fade near end
                let fade = CABasicAnimation(keyPath: "opacity")
                fade.fromValue = 1.0
                fade.toValue = 0.0
                fade.beginTime = duration * 0.6
                fade.duration = duration * 0.4
                fade.fillMode = .forwards

                let group = CAAnimationGroup()
                group.animations = [pathAnim, spin, fade]
                group.duration = duration
                group.fillMode = .forwards
                group.isRemovedOnCompletion = false

                CATransaction.begin()
                CATransaction.setCompletionBlock { [weak layer] in
                    layer?.removeFromSuperlayer()
                }
                layer.add(group, forKey: "confetti")
                CATransaction.commit()
            }
        }
    }
}
