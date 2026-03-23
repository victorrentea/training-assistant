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

    // MARK: - Film burn (burning edges spreading across screen)

    func showFilmBurn() {
        let bounds = hostLayer.bounds
        let totalDuration = 4.5

        let container = CALayer()
        container.frame = bounds
        hostLayer.addSublayer(container)

        // Burn starts from edges/corners — like a real film melting
        // Use non-overlapping rectangular burn zones that tile the screen
        let cols = 3
        let rows = 2
        let cellW = bounds.width / CGFloat(cols)
        let cellH = bounds.height / CGFloat(rows)

        // Stagger order: corners first, then edges, then center
        let order: [(Int, Int)] = [(0,0), (2,1), (2,0), (0,1), (1,0), (1,1)]

        for (idx, (col, row)) in order.enumerated() {
            let startDelay = Double(idx) * 0.45
            let cellRect = CGRect(x: CGFloat(col) * cellW, y: CGFloat(row) * cellH,
                                  width: cellW, height: cellH)
            let center = CGPoint(x: cellRect.midX, y: cellRect.midY)

            // Burn edge — glowing ring that appears and flickers
            let edgePath = CGPath(ellipseIn: cellRect.insetBy(dx: -20, dy: -20), transform: nil)
            let ringLayer = CAShapeLayer()
            ringLayer.path = edgePath
            ringLayer.fillColor = nil
            ringLayer.strokeColor = NSColor(red: 1.0, green: 0.35, blue: 0.0, alpha: 0.9).cgColor
            ringLayer.lineWidth = 30
            ringLayer.shadowColor = NSColor(red: 1.0, green: 0.6, blue: 0.0, alpha: 1.0).cgColor
            ringLayer.shadowOffset = .zero
            ringLayer.shadowRadius = 20
            ringLayer.shadowOpacity = 1.0
            ringLayer.opacity = 0
            container.addSublayer(ringLayer)

            // Ring appears, flickers, shrinks to nothing
            let ringAppear = CABasicAnimation(keyPath: "opacity")
            ringAppear.fromValue = 0
            ringAppear.toValue = 1
            ringAppear.beginTime = startDelay
            ringAppear.duration = 0.15
            ringAppear.fillMode = .both
            ringAppear.isRemovedOnCompletion = false

            let smallPath = CGPath(ellipseIn: CGRect(x: center.x - 5, y: center.y - 5,
                                                      width: 10, height: 10), transform: nil)
            let ringShrink = CABasicAnimation(keyPath: "path")
            ringShrink.fromValue = edgePath
            ringShrink.toValue = smallPath
            ringShrink.beginTime = startDelay + 0.1
            ringShrink.duration = 1.5
            ringShrink.timingFunction = CAMediaTimingFunction(name: .easeIn)
            ringShrink.fillMode = .both
            ringShrink.isRemovedOnCompletion = false

            let flicker = CAKeyframeAnimation(keyPath: "lineWidth")
            flicker.values = [30, 40, 20, 45, 25, 35, 28]
            flicker.duration = 0.25
            flicker.repeatCount = .infinity

            let ringFade = CABasicAnimation(keyPath: "opacity")
            ringFade.fromValue = 1
            ringFade.toValue = 0
            ringFade.beginTime = startDelay + 1.2
            ringFade.duration = 0.5
            ringFade.fillMode = .both
            ringFade.isRemovedOnCompletion = false

            let ringGroup = CAAnimationGroup()
            ringGroup.animations = [ringAppear, ringShrink, flicker, ringFade]
            ringGroup.duration = totalDuration
            ringGroup.fillMode = .forwards
            ringGroup.isRemovedOnCompletion = false
            ringLayer.add(ringGroup, forKey: "ring")

            // Darkening layer — semi-transparent brown/dark that intensifies
            let darkLayer = CALayer()
            darkLayer.frame = cellRect
            darkLayer.backgroundColor = NSColor(red: 0.15, green: 0.05, blue: 0.0, alpha: 0.85).cgColor
            darkLayer.opacity = 0
            container.addSublayer(darkLayer)

            let darkAppear = CAKeyframeAnimation(keyPath: "opacity")
            darkAppear.values = [0, 0, 0.4, 0.7, 0.85, 0.85, 0]
            darkAppear.keyTimes = [0,
                                   NSNumber(value: startDelay / totalDuration),
                                   NSNumber(value: (startDelay + 0.5) / totalDuration),
                                   NSNumber(value: (startDelay + 1.0) / totalDuration),
                                   NSNumber(value: (startDelay + 1.5) / totalDuration),
                                   NSNumber(value: (totalDuration - 1.0) / totalDuration),
                                   1.0]
            darkAppear.duration = totalDuration
            darkAppear.fillMode = .forwards
            darkAppear.isRemovedOnCompletion = false
            darkLayer.add(darkAppear, forKey: "dark")

            // Fire sparks at ignition point
            DispatchQueue.main.asyncAfter(deadline: .now() + startDelay) { [weak self] in
                self?.spawnFireSparks(at: center, in: container)
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 0.2) { [weak container] in
            container?.removeFromSuperlayer()
        }
    }

    private func spawnFireSparks(at point: CGPoint, in container: CALayer, count: Int = 15) {
        let scale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        for _ in 0..<count {
            let spark = CALayer()
            let size: CGFloat = CGFloat.random(in: 3...8)
            spark.frame = CGRect(x: point.x - size/2, y: point.y - size/2, width: size, height: size)
            spark.cornerRadius = size / 2
            let g = CGFloat.random(in: 0.2...0.6)
            spark.backgroundColor = NSColor(red: 1.0, green: g, blue: 0.0, alpha: 1.0).cgColor
            spark.contentsScale = scale
            container.addSublayer(spark)

            // Rise upward like embers
            let angle = CGFloat.random(in: CGFloat.pi * 0.15 ... CGFloat.pi * 0.85) // mostly upward
            let dist = CGFloat.random(in: 50...200)
            let endPoint = CGPoint(x: point.x + cos(angle) * dist * 0.4,
                                   y: point.y + sin(angle) * dist)

            let move = CABasicAnimation(keyPath: "position")
            move.fromValue = NSValue(point: point)
            move.toValue = NSValue(point: endPoint)
            move.timingFunction = CAMediaTimingFunction(name: .easeOut)

            let fade = CABasicAnimation(keyPath: "opacity")
            fade.fromValue = 1.0
            fade.toValue = 0.0

            let duration = Double.random(in: 0.5...1.2)
            let group = CAAnimationGroup()
            group.animations = [move, fade]
            group.duration = duration
            group.fillMode = .forwards
            group.isRemovedOnCompletion = false

            CATransaction.begin()
            CATransaction.setCompletionBlock { [weak spark] in spark?.removeFromSuperlayer() }
            spark.add(group, forKey: "spark")
            CATransaction.commit()
        }
    }

    // MARK: - Zorro Z slash (fiery sword marks)

    func showZorro() {
        let bounds = hostLayer.bounds
        let totalDuration = 3.5

        let container = CALayer()
        container.frame = bounds
        // Tilt the whole Z ~8 degrees
        container.setAffineTransform(CGAffineTransform(rotationAngle: 0.14))
        hostLayer.addSublayer(container)

        let cx = bounds.midX
        let cy = bounds.midY
        let halfW: CGFloat = bounds.width * 0.22
        let halfH: CGFloat = bounds.height * 0.20

        // Organic Z path with bezier curves — sword slash marks, not straight lines
        let zPath = CGMutablePath()

        // Stroke 1: top slash (left to right, slight upward arc)
        let t1Start = CGPoint(x: cx - halfW - 30, y: cy + halfH + 15)
        let t1End   = CGPoint(x: cx + halfW + 20, y: cy + halfH - 10)
        let t1CP1   = CGPoint(x: cx - halfW * 0.3, y: cy + halfH + 40)
        let t1CP2   = CGPoint(x: cx + halfW * 0.4, y: cy + halfH + 25)
        zPath.move(to: t1Start)
        zPath.addCurve(to: t1End, control1: t1CP1, control2: t1CP2)

        // Stroke 2: diagonal slash (top-right to bottom-left, aggressive curve)
        let d1CP1 = CGPoint(x: cx + halfW * 0.5, y: cy + halfH * 0.3)
        let d1CP2 = CGPoint(x: cx - halfW * 0.4, y: cy - halfH * 0.2)
        let dEnd  = CGPoint(x: cx - halfW - 15, y: cy - halfH + 8)
        zPath.addCurve(to: dEnd, control1: d1CP1, control2: d1CP2)

        // Stroke 3: bottom slash (left to right, slight downward arc)
        let b1CP1 = CGPoint(x: cx - halfW * 0.2, y: cy - halfH - 30)
        let b1CP2 = CGPoint(x: cx + halfW * 0.3, y: cy - halfH - 20)
        let bEnd  = CGPoint(x: cx + halfW + 25, y: cy - halfH + 12)
        zPath.addCurve(to: bEnd, control1: b1CP1, control2: b1CP2)

        // Fire glow layer (wide, orange-red)
        let fireGlow = CAShapeLayer()
        fireGlow.path = zPath
        fireGlow.strokeColor = NSColor(red: 1.0, green: 0.3, blue: 0.0, alpha: 0.7).cgColor
        fireGlow.lineWidth = 35
        fireGlow.fillColor = nil
        fireGlow.lineCap = .round
        fireGlow.lineJoin = .round
        fireGlow.strokeEnd = 0
        fireGlow.shadowColor = NSColor(red: 1.0, green: 0.2, blue: 0.0, alpha: 1.0).cgColor
        fireGlow.shadowOffset = .zero
        fireGlow.shadowRadius = 40
        fireGlow.shadowOpacity = 1.0
        container.addSublayer(fireGlow)

        // Inner fire layer (bright orange-yellow)
        let innerFire = CAShapeLayer()
        innerFire.path = zPath
        innerFire.strokeColor = NSColor(red: 1.0, green: 0.6, blue: 0.1, alpha: 0.9).cgColor
        innerFire.lineWidth = 14
        innerFire.fillColor = nil
        innerFire.lineCap = .round
        innerFire.lineJoin = .round
        innerFire.strokeEnd = 0
        innerFire.shadowColor = NSColor(red: 1.0, green: 0.8, blue: 0.2, alpha: 1.0).cgColor
        innerFire.shadowOffset = .zero
        innerFire.shadowRadius = 15
        innerFire.shadowOpacity = 1.0
        container.addSublayer(innerFire)

        // White-hot core
        let coreLayer = CAShapeLayer()
        coreLayer.path = zPath
        coreLayer.strokeColor = NSColor(red: 1.0, green: 0.95, blue: 0.8, alpha: 1.0).cgColor
        coreLayer.lineWidth = 4
        coreLayer.fillColor = nil
        coreLayer.lineCap = .round
        coreLayer.lineJoin = .round
        coreLayer.strokeEnd = 0
        coreLayer.shadowColor = NSColor.white.cgColor
        coreLayer.shadowOffset = .zero
        coreLayer.shadowRadius = 6
        coreLayer.shadowOpacity = 0.8
        container.addSublayer(coreLayer)

        // Animate all three layers being drawn
        let drawDuration = 1.4
        for slashLayer in [fireGlow, innerFire, coreLayer] {
            let draw = CABasicAnimation(keyPath: "strokeEnd")
            draw.fromValue = 0
            draw.toValue = 1
            draw.duration = drawDuration
            draw.timingFunction = CAMediaTimingFunction(controlPoints: 0.1, 0.0, 0.3, 1.0)
            draw.fillMode = .forwards
            draw.isRemovedOnCompletion = false
            slashLayer.add(draw, forKey: "draw")
        }

        // Flicker the fire glow width for realism
        let glowFlicker = CAKeyframeAnimation(keyPath: "lineWidth")
        glowFlicker.values = [35, 45, 30, 50, 32, 42, 38]
        glowFlicker.duration = 0.2
        glowFlicker.repeatCount = .infinity
        fireGlow.add(glowFlicker, forKey: "flicker")

        // Sparks along the slash — burst at each stroke transition
        let sparkPoints = [t1Start, t1End, dEnd, bEnd]
        let sparkDelays = [0.0, 0.4, 0.85, 1.3]
        for (point, delay) in zip(sparkPoints, sparkDelays) {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.spawnFireSparks(at: point, in: container, count: 18)
            }
        }

        // Brief red-orange flash when Z completes
        let flash = CALayer()
        flash.frame = bounds
        flash.backgroundColor = NSColor(red: 1.0, green: 0.3, blue: 0.0, alpha: 1.0).cgColor
        flash.opacity = 0
        container.addSublayer(flash)

        let flashAnim = CAKeyframeAnimation(keyPath: "opacity")
        flashAnim.values = [0.0, 0.0, 0.2, 0.0]
        flashAnim.keyTimes = [0.0, NSNumber(value: drawDuration / totalDuration),
                              NSNumber(value: (drawDuration + 0.1) / totalDuration), 1.0]
        flashAnim.duration = totalDuration
        flashAnim.fillMode = .forwards
        flashAnim.isRemovedOnCompletion = false
        flash.add(flashAnim, forKey: "flash")

        // Fade out after the Z burns
        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.fromValue = 1.0
        fadeOut.toValue = 0.0
        fadeOut.beginTime = CACurrentMediaTime() + drawDuration + 0.8
        fadeOut.duration = totalDuration - drawDuration - 0.8
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
