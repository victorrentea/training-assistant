import AppKit
import QuartzCore

class EmojiAnimator {
    private let hostLayer: CALayer

    static let emojiSet = ["❤️", "🔥", "👏", "😂", "🤯", "💡", "☕", "✅", "❌"]

    // Image-extracted ECG beat curve (64 points, normalized x∈[0,1], y∈[-1,1], R-spike at x≈0.3465)
    private static let beatCurve: [(Double, Double)] = [
        (0.0000,0.0000), (0.0157,0.0054), (0.0315,0.0291), (0.0472,0.0560),
        (0.0630,0.0891), (0.0787,0.1258), (0.0945,0.2001), (0.1102,0.2375),
        (0.1260,0.2755), (0.1417,0.2809), (0.1575,0.2320), (0.1732,0.1614),
        (0.1890,0.0915), (0.2047,0.0496), (0.2205,-0.0438), (0.2362,-0.1079),
        (0.2520,-0.1122), (0.2677,-0.1312), (0.2835,-0.1176), (0.2992,0.0083),
        (0.3150,0.3795), (0.3307,0.7897), (0.3465,0.9132), (0.3622,0.9064),
        (0.3780,0.6096), (0.3937,0.4664), (0.4094,0.1651), (0.4252,-0.2663),
        (0.4409,-0.3111), (0.4567,-0.2185), (0.4724,-0.0557), (0.4882,-0.0400),
        (0.5039,-0.0197), (0.5197,-0.0020), (0.5354,0.0116), (0.5512,0.0062),
        (0.5669,0.0112), (0.5827,0.0196), (0.5984,0.0198), (0.6142,0.0171),
        (0.6299,0.0115), (0.6457,0.0059), (0.6614,0.0090), (0.6772,0.0005),
        (0.6929,-0.0087), (0.7087,0.0039), (0.7244,0.0185), (0.7402,0.0268),
        (0.7559,0.1190), (0.7717,0.1651), (0.7874,0.1964), (0.8031,0.2486),
        (0.8189,0.3517), (0.8346,0.3388), (0.8504,0.3551), (0.8661,0.3484),
        (0.8819,0.3192), (0.9055,0.3217), (0.9213,0.1663), (0.9370,0.1384),
        (0.9528,0.0871), (0.9685,0.0368), (0.9843,0.0190), (1.0000,-0.0000)
    ]

    // Track active toggleable effects (danger, sepia, zorro) so clicking again cancels them
    private var activeEffects: [String: CALayer] = [:]

    // Applause: persistent timer for emoji spawning
    private var applauseTimer: Timer?

    // Pulse: layers stored so clicking again can stop it
    private var pulseRunning = false
    private var _pulseDimLayer: CALayer?
    private var _pulseEcgLayer: CALayer?

    init(hostLayer: CALayer) {
        self.hostLayer = hostLayer
    }

    /// Cancel a running toggleable effect. Returns true if it was running (and got cancelled).
    private func cancelIfRunning(_ key: String, sound: String? = nil) -> Bool {
        if let layer = activeEffects[key] {
            layer.removeAllAnimations()
            layer.removeFromSuperlayer()
            activeEffects.removeValue(forKey: key)
            if let sound = sound {
                SoundManager.shared.stop(sound)
            }
            return true
        }
        return false
    }

    /// Register a layer as an active toggleable effect, with auto-cleanup after duration.
    private func trackEffect(_ key: String, layer: CALayer, duration: Double, sound: String? = nil) {
        activeEffects[key] = layer
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) { [weak self, weak layer] in
            guard let self = self, let layer = layer else { return }
            // Only clean up if this layer is still the active one for this key
            if self.activeEffects[key] === layer {
                self.activeEffects.removeValue(forKey: key)
            }
            layer.removeFromSuperlayer()
            if let sound = sound {
                SoundManager.shared.stop(sound)
            }
        }
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
    func showVignette(key: String? = nil, color: NSColor, duration: Double = 2.5, pulses: Int = 2, soundToStop: String? = nil) {
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

        if let key = key {
            activeEffects[key] = vignetteLayer
        }

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak self, weak vignetteLayer] in
            if let key = key, let self = self, self.activeEffects[key] === vignetteLayer {
                self.activeEffects.removeValue(forKey: key)
            }
            vignetteLayer?.removeFromSuperlayer()
            if let sound = soundToStop {
                SoundManager.shared.stop(sound)
            }
        }
        vignetteLayer.add(group, forKey: "vignette")
        CATransaction.commit()
    }

    func showDanger() {
        if cancelIfRunning("danger", sound: "alarm.mp3") { return }
        SoundManager.shared.play("alarm.mp3")
        showVignette(key: "danger", color: .systemRed, duration: 3.0, pulses: 3, soundToStop: "alarm.mp3")
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
        if cancelIfRunning("zorro") { return }
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

        trackEffect("zorro", layer: container, duration: totalDuration + 0.2)
    }

    // MARK: - Fireworks

    private static let fireworkPalettes: [[NSColor]] = [
        [NSColor(red: 1, green: 0.2, blue: 0.2, alpha: 1),
         NSColor(red: 1, green: 0.5, blue: 0.1, alpha: 1),
         NSColor(red: 1, green: 0.85, blue: 0.2, alpha: 1)],
        [NSColor(red: 0.2, green: 0.6, blue: 1, alpha: 1),
         NSColor(red: 0.4, green: 0.9, blue: 1, alpha: 1),
         .white],
        [NSColor(red: 1, green: 0.2, blue: 0.6, alpha: 1),
         NSColor(red: 0.8, green: 0.3, blue: 1, alpha: 1),
         NSColor(red: 1, green: 0.6, blue: 0.9, alpha: 1)],
        [NSColor(red: 1, green: 0.85, blue: 0.1, alpha: 1),
         .white,
         NSColor(red: 1, green: 0.95, blue: 0.6, alpha: 1)],
        [NSColor(red: 0.1, green: 1, blue: 0.4, alpha: 1),
         NSColor(red: 0.3, green: 1, blue: 0.8, alpha: 1),
         .white],
    ]

    func showFireworks() {
        guard activeEffects["fireworks"] == nil else { return }
        let sentinel = CALayer()
        trackEffect("fireworks", layer: sentinel, duration: 8.0)
        SoundManager.shared.play("fireworks.mp3")

        let bounds = hostLayer.bounds
        let scale = NSScreen.screens.first?.backingScaleFactor ?? 2.0

        // Wave 1: 3 big ones
        for r in 0..<3 {
            let delay = Double(r) * 0.4
            let x = bounds.width * (0.2 + CGFloat(r) * 0.3) + CGFloat.random(in: -60...60)
            let y = CGFloat.random(in: bounds.height * 0.50...bounds.height * 0.80)
            let palette = EmojiAnimator.fireworkPalettes.randomElement()!
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.launchRocket(from: CGPoint(x: x, y: -10), to: CGPoint(x: x + CGFloat.random(in: -30...30), y: y),
                                   palette: palette, scale: scale, big: true)
            }
        }
        // Wave 2: 3-4 more, staggered
        for r in 0..<Int.random(in: 3...4) {
            let delay = 1.0 + Double(r) * 0.35
            let x = CGFloat.random(in: bounds.width * 0.1...bounds.width * 0.9)
            let y = CGFloat.random(in: bounds.height * 0.40...bounds.height * 0.75)
            let palette = EmojiAnimator.fireworkPalettes.randomElement()!
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.launchRocket(from: CGPoint(x: x, y: -10), to: CGPoint(x: x + CGFloat.random(in: -20...20), y: y),
                                   palette: palette, scale: scale, big: Bool.random())
            }
        }
        // Wave 3: grand finale — rapid burst of 4
        for r in 0..<4 {
            let delay = 2.5 + Double(r) * 0.15
            let x = CGFloat.random(in: bounds.width * 0.15...bounds.width * 0.85)
            let y = CGFloat.random(in: bounds.height * 0.45...bounds.height * 0.80)
            let palette = EmojiAnimator.fireworkPalettes.randomElement()!
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.launchRocket(from: CGPoint(x: x, y: -10), to: CGPoint(x: x, y: y),
                                   palette: palette, scale: scale, big: true)
            }
        }

        // Fade starts at 6.4s so sound ends completely at 6.7s — 300ms before animation ends (~7s)
        DispatchQueue.main.asyncAfter(deadline: .now() + 6.4) {
            SoundManager.shared.stop("fireworks.mp3")
        }
    }

    private func launchRocket(from start: CGPoint, to burst: CGPoint,
                              palette: [NSColor], scale: CGFloat, big: Bool) {
        let riseDuration = Double.random(in: 0.4...0.7)

        // Rocket — bright streak rising up
        let rocket = CAShapeLayer()
        let trailPath = CGMutablePath()
        trailPath.move(to: start)
        trailPath.addLine(to: CGPoint(x: start.x, y: start.y + 40))
        rocket.path = trailPath
        rocket.strokeColor = NSColor.white.cgColor
        rocket.lineWidth = 3
        rocket.lineCap = .round
        rocket.fillColor = nil
        rocket.shadowColor = palette[0].cgColor
        rocket.shadowOffset = .zero
        rocket.shadowRadius = 12
        rocket.shadowOpacity = 1.0
        hostLayer.addSublayer(rocket)

        // Rise animation
        let risePath = CGMutablePath()
        risePath.move(to: start)
        // Slight wobble on the way up
        let midX = (start.x + burst.x) / 2 + CGFloat.random(in: -15...15)
        let midY = (start.y + burst.y) / 2
        risePath.addQuadCurve(to: burst, control: CGPoint(x: midX, y: midY))

        let riseAnim = CAKeyframeAnimation(keyPath: "position")
        riseAnim.path = risePath
        riseAnim.duration = riseDuration
        riseAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)
        riseAnim.fillMode = .forwards
        riseAnim.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak self, weak rocket] in
            rocket?.removeFromSuperlayer()
            self?.explodeFirework(at: burst, palette: palette, scale: scale, big: big)
        }
        rocket.add(riseAnim, forKey: "rise")
        CATransaction.commit()
    }

    private func explodeFirework(at center: CGPoint, palette: [NSColor], scale: CGFloat, big: Bool) {
        let streakCount = big ? Int.random(in: 40...55) : Int.random(in: 24...32)
        let burstRadius = big ? CGFloat.random(in: 250...400) : CGFloat.random(in: 140...220)
        let duration = big ? Double.random(in: 1.8...2.5) : Double.random(in: 1.2...1.8)

        // Massive flash
        let flash = CALayer()
        let flashSize: CGFloat = big ? 120 : 60
        flash.frame = CGRect(x: center.x - flashSize/2, y: center.y - flashSize/2,
                              width: flashSize, height: flashSize)
        flash.cornerRadius = flashSize / 2
        flash.backgroundColor = NSColor.white.cgColor
        flash.shadowColor = palette[0].cgColor
        flash.shadowOffset = .zero
        flash.shadowRadius = big ? 80 : 40
        flash.shadowOpacity = 1.0
        flash.contentsScale = scale
        hostLayer.addSublayer(flash)

        let flashScale = CABasicAnimation(keyPath: "transform.scale")
        flashScale.fromValue = 0.5
        flashScale.toValue = big ? 3.0 : 2.0

        let flashFade = CABasicAnimation(keyPath: "opacity")
        flashFade.fromValue = 1.0
        flashFade.toValue = 0.0

        let flashGroup = CAAnimationGroup()
        flashGroup.animations = [flashScale, flashFade]
        flashGroup.duration = 0.3
        flashGroup.fillMode = .forwards
        flashGroup.isRemovedOnCompletion = false
        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak flash] in flash?.removeFromSuperlayer() }
        flash.add(flashGroup, forKey: "flash")
        CATransaction.commit()

        // Streaking lines — the real firework effect
        for i in 0..<streakCount {
            let baseAngle = (CGFloat(i) / CGFloat(streakCount)) * 2 * .pi
            let angle = baseAngle + CGFloat.random(in: -0.12...0.12)
            let dist = burstRadius * CGFloat.random(in: 0.6...1.0)
            let color = palette.randomElement()!

            // Each streak is a line (CAShapeLayer) that extends outward
            let endPoint = CGPoint(
                x: center.x + cos(angle) * dist,
                y: center.y + sin(angle) * dist
            )
            // Gravity droop at the end
            let droopEnd = CGPoint(x: endPoint.x, y: endPoint.y - dist * 0.25)

            let streakPath = CGMutablePath()
            streakPath.move(to: center)
            streakPath.addQuadCurve(to: droopEnd,
                                     control: endPoint)

            let streak = CAShapeLayer()
            streak.path = streakPath
            streak.strokeColor = color.cgColor
            streak.lineWidth = big ? CGFloat.random(in: 2.5...4.5) : CGFloat.random(in: 1.5...3.0)
            streak.lineCap = .round
            streak.fillColor = nil
            streak.shadowColor = color.cgColor
            streak.shadowOffset = .zero
            streak.shadowRadius = big ? 8 : 4
            streak.shadowOpacity = 1.0
            streak.strokeEnd = 0
            hostLayer.addSublayer(streak)

            // Draw the streak outward rapidly
            let drawDuration = duration * 0.35
            let draw = CABasicAnimation(keyPath: "strokeEnd")
            draw.fromValue = 0
            draw.toValue = 1
            draw.duration = drawDuration
            draw.timingFunction = CAMediaTimingFunction(name: .easeOut)
            draw.fillMode = .forwards
            draw.isRemovedOnCompletion = false

            // Then the tail follows (strokeStart catches up)
            let tail = CABasicAnimation(keyPath: "strokeStart")
            tail.fromValue = 0
            tail.toValue = 1
            tail.beginTime = drawDuration * 0.4
            tail.duration = duration - drawDuration * 0.4
            tail.timingFunction = CAMediaTimingFunction(name: .easeIn)
            tail.fillMode = .forwards
            tail.isRemovedOnCompletion = false

            // Fade at the end
            let fade = CABasicAnimation(keyPath: "opacity")
            fade.fromValue = 1.0
            fade.toValue = 0.0
            fade.beginTime = duration * 0.5
            fade.duration = duration * 0.5
            fade.fillMode = .forwards
            fade.isRemovedOnCompletion = false

            let group = CAAnimationGroup()
            group.animations = [draw, tail, fade]
            group.duration = duration
            group.fillMode = .forwards
            group.isRemovedOnCompletion = false

            CATransaction.begin()
            CATransaction.setCompletionBlock { [weak streak] in streak?.removeFromSuperlayer() }
            streak.add(group, forKey: "burst")
            CATransaction.commit()

            // Glowing dot at the tip of each streak
            if i % 2 == 0 {
                let dot = CALayer()
                let dotSize: CGFloat = big ? 6 : 4
                dot.frame = CGRect(x: center.x - dotSize/2, y: center.y - dotSize/2,
                                    width: dotSize, height: dotSize)
                dot.cornerRadius = dotSize / 2
                dot.backgroundColor = NSColor.white.cgColor
                dot.shadowColor = color.cgColor
                dot.shadowOffset = .zero
                dot.shadowRadius = 6
                dot.shadowOpacity = 1.0
                dot.contentsScale = scale
                hostLayer.addSublayer(dot)

                let dotPath = CGMutablePath()
                dotPath.move(to: center)
                dotPath.addQuadCurve(to: droopEnd, control: endPoint)

                let dotMove = CAKeyframeAnimation(keyPath: "position")
                dotMove.path = dotPath
                dotMove.timingFunction = CAMediaTimingFunction(name: .easeOut)

                let dotFade = CABasicAnimation(keyPath: "opacity")
                dotFade.fromValue = 1.0
                dotFade.toValue = 0.0
                dotFade.beginTime = duration * 0.4
                dotFade.duration = duration * 0.6
                dotFade.fillMode = .forwards

                let dotShrink = CABasicAnimation(keyPath: "transform.scale")
                dotShrink.fromValue = 1.5
                dotShrink.toValue = 0.2
                dotShrink.timingFunction = CAMediaTimingFunction(name: .easeIn)

                let dotGroup = CAAnimationGroup()
                dotGroup.animations = [dotMove, dotFade, dotShrink]
                dotGroup.duration = duration
                dotGroup.fillMode = .forwards
                dotGroup.isRemovedOnCompletion = false

                CATransaction.begin()
                CATransaction.setCompletionBlock { [weak dot] in dot?.removeFromSuperlayer() }
                dot.add(dotGroup, forKey: "tip")
                CATransaction.commit()
            }
        }

        // Secondary crackle sparks — tiny pops after main burst
        if big {
            for j in 0..<8 {
                let sparkDelay = Double.random(in: 0.3...1.0)
                let sparkCenter = CGPoint(
                    x: center.x + CGFloat.random(in: -burstRadius * 0.5...burstRadius * 0.5),
                    y: center.y + CGFloat.random(in: -burstRadius * 0.3...burstRadius * 0.5)
                )
                DispatchQueue.main.asyncAfter(deadline: .now() + sparkDelay) { [weak self] in
                    guard let self = self else { return }
                    let color = palette.randomElement()!
                    for _ in 0..<6 {
                        let spark = CALayer()
                        let sz: CGFloat = CGFloat.random(in: 2...4)
                        spark.frame = CGRect(x: sparkCenter.x, y: sparkCenter.y, width: sz, height: sz)
                        spark.cornerRadius = sz / 2
                        spark.backgroundColor = color.cgColor
                        spark.contentsScale = scale
                        self.hostLayer.addSublayer(spark)

                        let ang = CGFloat.random(in: 0...(2 * .pi))
                        let d = CGFloat.random(in: 20...50)
                        let end = CGPoint(x: sparkCenter.x + cos(ang) * d,
                                          y: sparkCenter.y + sin(ang) * d - 15)
                        let move = CABasicAnimation(keyPath: "position")
                        move.toValue = NSValue(point: end)
                        let fade = CABasicAnimation(keyPath: "opacity")
                        fade.fromValue = 1.0
                        fade.toValue = 0.0
                        let g = CAAnimationGroup()
                        g.animations = [move, fade]
                        g.duration = Double.random(in: 0.3...0.6)
                        g.fillMode = .forwards
                        g.isRemovedOnCompletion = false
                        CATransaction.begin()
                        CATransaction.setCompletionBlock { [weak spark] in spark?.removeFromSuperlayer() }
                        spark.add(g, forKey: "crackle")
                        CATransaction.commit()
                    }
                    _ = j // suppress warning
                }
            }
        }
    }

    // MARK: - Sepia / old film overlay

    func showSepia() {
        if cancelIfRunning("sepia", sound: "projector.mp3") { return }
        let bounds = hostLayer.bounds
        let totalDuration = 7.0

        SoundManager.shared.play("projector.mp3")

        let container = CALayer()
        container.frame = bounds
        hostLayer.addSublayer(container)

        // Warm sepia wash — visible yellowed center
        let sepiaLayer = CALayer()
        sepiaLayer.frame = bounds
        sepiaLayer.backgroundColor = NSColor(red: 0.50, green: 0.38, blue: 0.15, alpha: 0.45).cgColor
        sepiaLayer.opacity = 0
        container.addSublayer(sepiaLayer)

        // Vignette darkening at edges (keeps center visible/yellowed)
        let vignette = CAGradientLayer()
        vignette.type = .radial
        vignette.frame = bounds
        vignette.colors = [
            NSColor.clear.cgColor,
            NSColor.clear.cgColor,
            NSColor(white: 0, alpha: 0.45).cgColor,
            NSColor(white: 0, alpha: 0.75).cgColor,
        ]
        vignette.locations = [0.0, 0.35, 0.70, 1.0]
        vignette.startPoint = CGPoint(x: 0.5, y: 0.5)
        vignette.endPoint = CGPoint(x: 1.0, y: 1.0)
        vignette.opacity = 0
        container.addSublayer(vignette)

        // Film grain — flickering specks
        let grainLayer = CALayer()
        grainLayer.frame = bounds
        grainLayer.opacity = 0
        container.addSublayer(grainLayer)

        let scale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        for _ in 0..<60 {
            let speck = CALayer()
            let sz = CGFloat.random(in: 1.5...4)
            speck.frame = CGRect(
                x: CGFloat.random(in: 0...bounds.width),
                y: CGFloat.random(in: 0...bounds.height),
                width: sz, height: sz
            )
            speck.cornerRadius = sz / 2
            let bright = Bool.random() ? CGFloat.random(in: 0.8...1.0) : CGFloat.random(in: 0...0.15)
            speck.backgroundColor = NSColor(white: bright, alpha: CGFloat.random(in: 0.3...0.7)).cgColor
            speck.contentsScale = scale
            grainLayer.addSublayer(speck)

            let flicker = CAKeyframeAnimation(keyPath: "opacity")
            flicker.values = [1.0, 0.0, 1.0, 0.0, 0.7, 0.0, 1.0]
            flicker.duration = Double.random(in: 0.15...0.4)
            flicker.repeatCount = .infinity
            speck.add(flicker, forKey: "flicker")
        }

        // Vertical scratches — thick and visible
        for _ in 0..<8 {
            let scratch = CAShapeLayer()
            let sp = CGMutablePath()
            let x = CGFloat.random(in: bounds.width * 0.05...bounds.width * 0.95)
            sp.move(to: CGPoint(x: x + CGFloat.random(in: -3...3), y: 0))
            sp.addLine(to: CGPoint(x: x + CGFloat.random(in: -8...8), y: bounds.height))
            scratch.path = sp
            scratch.strokeColor = NSColor(white: 0.95, alpha: 0.6).cgColor
            scratch.lineWidth = CGFloat.random(in: 1.5...4.0)
            scratch.fillColor = nil
            scratch.opacity = 0
            container.addSublayer(scratch)

            let sf = CAKeyframeAnimation(keyPath: "opacity")
            sf.values = [0, 0, 0.8, 0, 0, 0.6, 0, 0]
            sf.duration = Double.random(in: 0.2...0.5)
            sf.repeatCount = .infinity
            scratch.add(sf, forKey: "scratch")
        }

        // Fade in over 1s, hold throughout, fade out in last 1s
        let fadeInEnd = 1.0 / totalDuration
        let fadeOutStart = 1.0 - (1.0 / totalDuration)

        for layer in [sepiaLayer, vignette, grainLayer] {
            let anim = CAKeyframeAnimation(keyPath: "opacity")
            anim.values = [0.0, 1.0, 1.0, 0.0]
            anim.keyTimes = [0.0, NSNumber(value: fadeInEnd),
                             NSNumber(value: fadeOutStart), 1.0]
            anim.duration = totalDuration
            anim.fillMode = .forwards
            anim.isRemovedOnCompletion = false
            layer.add(anim, forKey: "sepia")
        }

        // Projector jitter — gentle throughout
        let jitter = CAKeyframeAnimation(keyPath: "position")
        let c = CGPoint(x: bounds.midX, y: bounds.midY)
        var jitterValues: [NSValue] = []
        for _ in 0..<100 {
            jitterValues.append(NSValue(point: CGPoint(
                x: c.x + CGFloat.random(in: -1.5...1.5),
                y: c.y + CGFloat.random(in: -1.5...1.5)
            )))
        }
        jitter.values = jitterValues
        jitter.duration = totalDuration
        container.add(jitter, forKey: "jitter")

        trackEffect("sepia", layer: container, duration: totalDuration + 0.2, sound: "projector.mp3")
    }

    // MARK: - Confetti burst

    func spawnConfetti(count: Int = 80) {
        guard activeEffects["confetti"] == nil else { return }
        let sentinel = CALayer()
        trackEffect("confetti", layer: sentinel, duration: 6.0)
        SoundManager.shared.playOverlapping("confetti.mp3")
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

    // MARK: - Applause (toggleable: click to start, click again to stop)

    func showApplause() {
        guard applauseTimer == nil else { return }   // already running — ignore

        let duration = 6.0
        SoundManager.shared.playLooping("applause.mp3")

        // Initial burst, then steady stream
        for i in 0..<10 { DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.05) { [weak self] in self?.spawnApplauseClap() } }
        applauseTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in
            self?.spawnApplauseClap()
        }

        // Auto-stop after duration
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) { [weak self] in
            self?.applauseTimer?.invalidate()
            self?.applauseTimer = nil
            SoundManager.shared.stop("applause.mp3")
        }
    }

    private func spawnApplauseClap() {
        let bounds = hostLayer.bounds
        let isBig = Int.random(in: 0..<4) == 0   // ~25% chance of giant clap
        let size: CGFloat = isBig ? CGFloat.random(in: 108...216) : CGFloat.random(in: 36...72)
        // Spawn from random position across the bottom third, fly upward
        let spawnX = CGFloat.random(in: size ... bounds.width - size)
        let spawnY = CGFloat.random(in: 0 ... bounds.height * 0.35)

        let layer = CATextLayer()
        layer.string = "👏"
        layer.fontSize = size * 0.8
        layer.alignmentMode = .center
        layer.frame = CGRect(x: spawnX - size / 2, y: spawnY, width: size, height: size)
        layer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        hostLayer.addSublayer(layer)

        let duration = Double.random(in: 1.8...2.8)
        let riseHeight = bounds.height * CGFloat.random(in: 0.55...0.85)
        let drift = CGFloat.random(in: -80...80)

        // Rise path with wobble
        let path = CGMutablePath()
        let steps = 12
        let start = CGPoint(x: spawnX, y: spawnY + size / 2)
        path.move(to: start)
        for i in 1...steps {
            let t = CGFloat(i) / CGFloat(steps)
            let wobble = sin(t * 3 * .pi) * 20 * (1 - t)
            path.addLine(to: CGPoint(x: start.x + drift * t + wobble, y: start.y + riseHeight * t))
        }

        let pathAnim = CAKeyframeAnimation(keyPath: "position")
        pathAnim.path = path
        pathAnim.timingFunction = CAMediaTimingFunction(name: .easeOut)

        let scaleAnim = CABasicAnimation(keyPath: "transform.scale")
        scaleAnim.fromValue = 0.6
        scaleAnim.toValue = 1.1

        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.fromValue = 1.0
        fadeOut.toValue = 0.0
        fadeOut.beginTime = duration * 0.45
        fadeOut.duration = duration * 0.55
        fadeOut.fillMode = .forwards

        let group = CAAnimationGroup()
        group.animations = [pathAnim, scaleAnim, fadeOut]
        group.duration = duration
        group.fillMode = .forwards
        group.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak layer] in layer?.removeFromSuperlayer() }
        layer.add(group, forKey: "applauseClap")
        CATransaction.commit()
    }

    // MARK: - Pulse / heartbeat (one-shot: 2 QRS cycles then flatline)

    func showPulse() {
        if pulseRunning { _stopPulse(); return }
        pulseRunning = true

        let bounds = hostLayer.bounds
        // Timing: dying.mp3 total duration 4.598s; delay sound 0.172s so the first
        // audio R-spike (0.105s) coincides with the visual peak in the image (~23% through reveal).
        let totalDuration: Double = 4.598
        let soundDelay:    Double = 0.172

        // Dark overlay
        let dimLayer = CALayer()
        _pulseDimLayer = dimLayer
        dimLayer.frame = bounds
        dimLayer.backgroundColor = NSColor(white: 0, alpha: 0.75).cgColor
        dimLayer.opacity = 0
        hostLayer.addSublayer(dimLayer)

        // Fade in overlay
        let dimIn = CABasicAnimation(keyPath: "opacity")
        dimIn.fromValue = 0
        dimIn.toValue = 1
        dimIn.duration = 0.35
        dimIn.fillMode = .forwards
        dimIn.isRemovedOnCompletion = false
        dimLayer.add(dimIn, forKey: "dimIn")

        // ECG canvas — full screen (amplitude needs full height)
        // Load the extracted ECG image (green line, transparent background)
        guard let url = Bundle.module.url(forResource: "ecg_line", withExtension: "png", subdirectory: "Resources"),
              let nsImage = NSImage(contentsOf: url),
              let cgImage = nsImage.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            pulseRunning = false
            return
        }

        let ecgLayer = CALayer()
        _pulseEcgLayer = ecgLayer
        ecgLayer.contents = cgImage
        ecgLayer.contentsGravity = .resize   // stretch to fill — line spans full screen
        ecgLayer.frame = bounds
        ecgLayer.opacity = 0
        hostLayer.addSublayer(ecgLayer)

        // Fade in image
        let ecgFadeIn = CABasicAnimation(keyPath: "opacity")
        ecgFadeIn.fromValue = 0
        ecgFadeIn.toValue = 1
        ecgFadeIn.duration = 0.35
        ecgFadeIn.fillMode = .forwards
        ecgFadeIn.isRemovedOnCompletion = false
        ecgLayer.add(ecgFadeIn, forKey: "ecgFadeIn")

        // Left-to-right reveal mask (white rect grows from left edge)
        let maskLayer = CALayer()
        maskLayer.backgroundColor = NSColor.white.cgColor
        maskLayer.anchorPoint = CGPoint(x: 0, y: 0.5)
        maskLayer.position = CGPoint(x: 0, y: bounds.height / 2)
        maskLayer.bounds = CGRect(x: 0, y: 0, width: 0, height: bounds.height)
        ecgLayer.mask = maskLayer

        let reveal = CABasicAnimation(keyPath: "bounds.size.width")
        reveal.fromValue = 0
        reveal.toValue = bounds.width
        reveal.duration = totalDuration
        reveal.timingFunction = CAMediaTimingFunction(name: .linear)
        reveal.fillMode = .forwards
        reveal.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak self, weak dimLayer, weak ecgLayer] in
            NSAnimationContext.runAnimationGroup({ ctx in
                ctx.duration = 0.45
                dimLayer?.opacity = 0
                ecgLayer?.opacity = 0
            }, completionHandler: {
                dimLayer?.removeFromSuperlayer()
                ecgLayer?.removeFromSuperlayer()
                self?.pulseRunning = false
                self?._pulseDimLayer = nil
                self?._pulseEcgLayer = nil
            })
        }
        maskLayer.add(reveal, forKey: "reveal")
        CATransaction.commit()

        // Sound: delayed so visual R-spike (at 0.3465*0.8=0.277s) coincides with audio R-spike (0.172+0.105=0.277s)
        DispatchQueue.main.asyncAfter(deadline: .now() + soundDelay) {
            SoundManager.shared.play("dying.mp3")
        }
    }

    // MARK: - Pulse stop (called when button pressed while running)

    private func _stopPulse() {
        guard pulseRunning else { return }
        pulseRunning = false
        SoundManager.shared.stop("dying.mp3")
        let dim = _pulseDimLayer
        let ecg = _pulseEcgLayer
        _pulseDimLayer = nil
        _pulseEcgLayer = nil
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.3
            dim?.opacity = 0
            ecg?.opacity = 0
        }, completionHandler: {
            dim?.removeFromSuperlayer()
            ecg?.removeFromSuperlayer()
        })
    }
}
