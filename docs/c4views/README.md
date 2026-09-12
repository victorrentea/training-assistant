# C4 Views

Generated C4 diagram exports and Import Linter artifacts from `docs/c4model.dsl`.

Sources used for the model:

- `ARCHITECTURE.md`
- `railway/app.py`
- the current `railway/shared/*`, `railway/features/*`, and `daemon/*` packages

It shows that Structurizr can render both:

- full C4 views such as C1 and C2
- focused slices, by defining separate views with targeted `include` statements

Defined views in [c4model.dsl](../c4model.dsl):

- `C1SystemContext`
- `C2Containers`
- `C2DaemonFlow`
- `C2ParticipantFlow`
- `C2TrainingDaemonOnly`
- `C3BackendOverview`
- `C3BackendRealtime`
- `C3BackendSessionAndSlides`
- `C3DaemonOverview`
- `C3DaemonOnly`
- `C3DaemonQuiz`
- `C3DaemonSlides`
- `C3DaemonSummary`
- `C1Ecosystem`
- `C2EcosystemMac`

The DSL is intentionally closer to the codebase than to the older static diagrams, so it includes backend routers and daemon modules that already exist in the repo even if they are not all represented in `ARCHITECTURE.md`.

## Ecosystem

`C1Ecosystem` and `C2EcosystemMac` step outside this repo. They model Victor's whole set of
personal tools, of which the workshop tool is one system, and they exist to answer one
question: **what talks to what, and over which channel.**

Every relationship description carries the real transport and the real port or path — never a
bare verb like "uses" — because the channel is what drifts and what nobody writes down.
`victor-macos-addons` is the switchboard: the tablet, both IDEs, the Chrome extension, the
training daemon and Claude Code's own hooks all dial it on `:55123`.

Ports and transports were read out of code, not out of prose. The sources:

| edge | read from |
|---|---|
| tablet transport ladder (adb reverse → LAN → mDNS → WSS relay) | `victor-macos-addons/Sources/VictorAddons/UsbTunnelKeeper.swift`, `victor-vibe-board/.../MacLink.kt` |
| effects proxy `:55123 → :55124` | `victor-macos-addons/Sources/VictorAddons/EffectsProxy.swift`, `TabletHttpServer.swift` |
| tile manifest precedence | `victor-effects/Sources/VictorEffects/TilesManifest.swift`, `victor-vibe-board/.../MainActivity.kt` |
| addons bridge `ws://127.0.0.1:8765` | `daemon/addon_bridge_client.py` |
| Chrome dictation `ws://127.0.0.1:8766` | `victor-macos-addons/Sources/VictorAddons/ChromeBridge.swift` |
| IDE relay ephemeral ports | `live-coding/.../RelayTerminalService.kt`, `victor-vsc/relay-terminal.js`, `walkie-talkie/Sources/WalkieTalkie/IDEBridge.swift` |
| hands-off gate | `~/bin/hands-off`, `victor-macos-addons/docs/hands-off.md` |
| hotspot over Bluetooth SPP, channel 9 | `victor-macos-addons/docs/hotspot-fallback.md`, `victor-phone-addons/CLAUDE.md` |

**Known to be moving:** the tablet is being changed to adopt the Mac's tile manifest at
reconnect, and usage counts are moving to the Mac. Those two edges will be wrong until the
next pass re-derives them.

The grey boxes on the right of `C1Ecosystem` are islands — tools that integrate with nothing
else Victor runs. That is information, not an omission.

These views are re-derived from code every week by the doc gardening pass
(`~/.claude/doc-gardening/prompt.md`, Faza 1.5), which diffs the model against the ports it
finds and reports the difference in both directions: an edge in the code that is missing from
the model, and an edge in the model the code no longer supports.

PNG renders are committed beside the exports. Regenerate them with the natively installed
PlantUML — no Docker needed for this step:

```bash
plantuml -tpng docs/c4views/C1-Ecosystem.puml docs/c4views/C2-Ecosystem-Mac.puml
```

Two traps paid for on the first render: a `\"` escaped quote inside a DSL relationship
description is emitted as a raw quote and breaks the PlantUML string, and angle brackets in a
description (`<pid>`, `<ephemeral>`) are read as markup. Keep both out of descriptions.

## View slicing

Structurizr does not crop an existing rendered diagram. Instead, you define another view over the same model.

Example:

```dsl
container workshop "C2DaemonFlow" {
    include host trainingDaemon fastapi macosAddons claudeApi googleDrive
    autoLayout lr
}
```

That renders only the selected part of the container model, plus relationships between included elements.

## Validate locally

Official CLI documentation:

- https://docs.structurizr.com/cli/installation
- https://docs.structurizr.com/cli/export
- https://docs.structurizr.com/dsl/language

From the repository root:

```bash
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/structurizr validate \
  -workspace docs/c4model.dsl
```

## Export locally

PlantUML / C4-PlantUML export:

```bash
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/structurizr export \
  -workspace docs/c4model.dsl \
  -format plantuml/c4plantuml \
  -output docs/c4views
```

Mermaid export:

```bash
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/structurizr export \
  -workspace docs/c4model.dsl \
  -format mermaid \
  -output docs/c4views
```

## Browse interactively

Structurizr Lite serves the DSL locally in a browser:

```bash
docker run --rm -p 8080:8080 \
  -v "$PWD/docs":/usr/local/structurizr \
  structurizr/structurizr lite
```

Then open `http://localhost:8080`.

## Export Import Linter Contracts

Generate Import Linter contracts directly from the Structurizr DSL relationships:

```bash
python3 scripts/generate_importlinter_from_structurizr.py
```

Then run Import Linter on the generated config:

```bash
uv run --extra dev lint-imports --config docs/c4views/importlinter.ini
```
