# Design System Document: The Intellectual Sanctuary

## 1. Overview & Creative North Star
**Creative North Star: "The Zen Editorial"**
This design system moves away from the cluttered, "dashboard-heavy" aesthetic of traditional workshop platforms. Instead, it adopts a high-end editorial approach that treats the desktop screen as a focused, digital sanctuary. By utilizing intentional asymmetry, expansive breathing room, and a palette of deep indigos and slates, we prioritize the participant's "flow state." The layout breaks the "boxed-in" template look by favoring tonal depth and atmospheric layering over rigid borders and heavy UI chrome.

## 2. Colors & Atmospheric Depth
The palette is rooted in a "Deep Indigo and Slate" foundation, designed to recede into the background, allowing the educational content to sit in the foreground.

### The "No-Line" Rule
**Prohibit 1px solid borders for sectioning.** 
Structural boundaries must be defined solely through background color shifts. For example, a `surface-container-low` section sitting on a `surface` background provides all the definition needed. If a separator is required, use a 16px to 32px vertical gap rather than a line.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers—like stacked sheets of fine, heavy-weight paper.
*   **The Base:** `surface` (#f7f9fb) is our canvas.
*   **The Sidebar:** `surface-container` (#e8eff3) provides a soft, grounded anchor for the 20% left-hand navigation.
*   **The Content Pods:** Use `surface-container-lowest` (#ffffff) for active workshop modules to create a "lifted" feel against the slightly darker background.

### The Glass & Gradient Rule
To prevent the UI from feeling "flat" or "corporate," apply Glassmorphism to floating elements (like active tooltips or hovering participant cards). 
*   **Glass Effect:** Use `surface` at 80% opacity with a `20px` backdrop-blur.
*   **Signature Textures:** Apply a subtle linear gradient (135°) from `primary` (#4555ba) to `primary-dim` (#3848ad) for primary CTAs to give them a "jewel-like" presence in the slate environment.

## 3. Typography: The Manrope Scale
Manrope is our sole typographic voice. Its geometric yet warm construction provides the "modern, focused feel" required for deep learning.

*   **Display (The Statement):** `display-lg` (3.5rem) should be used for workshop titles, set with a tight letter-spacing (-0.02em) to feel like a premium magazine header.
*   **Headlines (The Anchor):** `headline-sm` (1.5rem) handles module headers. Use `on-surface-variant` (#566166) to keep these headers sophisticated and non-aggressive.
*   **Body (The Content):** `body-lg` (1rem) is the workhorse. Ensure a generous line-height (1.6) to maximize readability during long workshop sessions.
*   **Labels (The Metadata):** `label-md` (0.75rem) in `primary` (#4555ba) all-caps for "Upcoming" or "Live" status indicators.

## 4. Elevation & Tonal Layering
We achieve hierarchy through **Tonal Layering** rather than traditional structural lines or heavy drop shadows.

*   **The Layering Principle:** Place a `surface-container-lowest` card on a `surface-container-low` section. This creates a natural "pop" that feels architectural rather than digital.
*   **Ambient Shadows:** For floating modals, use a "Whisper Shadow": `0px 12px 32px rgba(42, 52, 57, 0.06)`. This uses a tinted version of the `on-surface` color to mimic natural light.
*   **The "Ghost Border" Fallback:** If accessibility requires a border, use the `outline-variant` (#a9b4b9) token at **15% opacity**. A solid 100% opaque border is considered a design failure in this system.

## 5. Component Guidelines

### Buttons: The Weighted Interaction
*   **Primary:** A pill-shaped (`full` roundedness) button using the `primary` fill. Text should be `on-primary`. No shadows.
*   **Secondary:** No fill. Use `on-secondary-container` text. The "border" is a `Ghost Border` (15% opacity).
*   **Tertiary:** Text-only, using `primary` color with an underline that only appears on hover.

### Inputs: The Immersive Field
*   **Text Fields:** Use `surface-container-highest` as the background fill. Use a `bottom-only` focus indicator in `primary` (#4555ba) that animates from the center outward. Avoid the "box" look.

### The 20/80 Sidebar
*   The 20% left sidebar should have no right-hand border. It is distinguished from the 80% content area purely by its `surface-container` (#e8eff3) fill.
*   **Active State:** Use a `primary-container` (#dfe0ff) pill-shaped background for the active navigation item.

### Workshop Content Cards
*   **No Dividers:** Forbid the use of divider lines between list items. Use 24px of vertical white space and a subtle background hover state of `surface-bright`.
*   **The Focus Card:** The current active module should use `surface-container-lowest` (#ffffff) with a `4px` left-side accent bar in `primary`.

## 6. Do’s and Don’ts

### Do
*   **Do** maximize white space. If you think there is enough space, add 16px more.
*   **Do** use `on-surface-variant` for secondary text to reduce visual noise.
*   **Do** utilize the `full` roundedness scale for interactive elements (chips, buttons) to maintain a "soft" sanctuary feel.

### Don’t
*   **Don't** use pure black (#000000) for text. Use `on-surface` (#2a3439) for a softer, premium contrast.
*   **Don't** use standard "Material Design" shadows. Always use the "Whisper Shadow" or Tonal Layering.
*   **Don't** crowd the 80% main content area. Keep a minimum 64px padding (inset) around the main content container to maintain the "Immersive" promise.