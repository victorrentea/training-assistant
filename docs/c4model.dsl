workspace "Workshop Live Interaction Tool" "Structurizr DSL model aligned to the current repository structure." {

    model {
        host = person "Host" "Runs the workshop, controls activities, and monitors the live session."
        participant = person "Participant" "Joins from a browser, votes, reacts, uploads, and follows the session."

        claudeApi = softwareSystem "Anthropic Claude API" "LLM used by the daemon for debate AI cleanup and code-review smart paste extraction."
        githubApi = softwareSystem "GitHub API" "Repo metadata (default branch), repo trees, and blob existence checks used to link opened files to the branch captured at open time. Unauthenticated."
        macosAddons = softwareSystem "victor-macos-addons" "Local Mac bridge that emits slide and IDE file-open events, and receives emoji/session notifications."
        nominatim = softwareSystem "Nominatim" "Reverse geocodes GPS coordinates into city and country."
        googleDrive = softwareSystem "Google Drive" "Hosts exported slide PDFs consumed by the Railway cache."
        agentMail = softwareSystem "AgentMail" "Hosted inbox/email service: delivers participant feedback notifications and routes incoming Claude email webhooks."
        hostFiles = softwareSystem "Host session files" "Session folders, normalized transcripts, ai-summary.md, uploaded files, and slide manifests on the trainer's Mac."
        localRag = softwareSystem "Local ChromaDB store" "~/.workshop-rag/chroma — background-indexed local materials."

        workshop = softwareSystem "Workshop Live Interaction Tool" "Self-hosted real-time audience interaction platform." {
            participantSpa = container "Participant SPA" "Participant-facing UI served from Railway session routes." "HTML/CSS/JavaScript"
            hostSpa = container "Host SPA" "Host control panel served from the daemon host server on localhost." "HTML/CSS/JavaScript"
            railwayBackend = container "Railway Backend" "Thin session-aware bridge for participants, slides, uploads, daemon sync, inbox webhooks, and telemetry." "Python 3.12 / FastAPI / Uvicorn" {
                bootstrap = component "Bootstrap" "Registers route ordering, OTel instrumentation, session guards, and startup stamping (version.js / deploy-info.json)." "railway/app.py"
                sharedCore = component "Shared Core" "AppState, auth, session registry/guard, throttling, metrics, messaging, and version helpers." "railway/shared/*"
                wsBridge = component "WebSocket bridge" "Daemon auth, session-scoped browser sockets, participant proxy bridge, and broadcast fan-out." "railway/features/ws/*"
                pageRoutes = component "Page routes" "Landing, participant, and host static page routing." "railway/features/pages/router.py"
                slidesBridge = component "Slides cache and file serving" "Public slide catalog/current slide, Google Drive cache, and host upload/invalidate helpers." "railway/features/slides/*"
                uploadsBridge = component "Temporary upload bridge" "Streams participant uploads into temporary storage and lets the daemon fetch and acknowledge them." "railway/features/upload/*"
                staticSync = component "Static sync endpoints" "Allows the daemon to upload and delete generated files under static/." "railway/features/internal/router.py"
                inboxBridge = component "Inbox webhook bridge" "Verifies AgentMail (Svix) webhooks for incoming Claude email and forwards events to the connected claude-inbox WebSocket listener." "railway/features/inbox/router.py"
                telemetryReceiver = component "Telemetry receiver" "Receives browser OTel spans (POST /api/telemetry/spans) and appends them to the shared traces file." "railway/features/telemetry/router.py"
            }
            trainingDaemon = container "Training Daemon" "Local source of truth for host control, live state, persistence, and AI-assisted jobs." "Python 3.12 CLI + embedded FastAPI" {
                orchestrator = component "Orchestrator" "Starts OTel tracing, the lock/heartbeat, host server, daemon WS client, addons bridge, slide runner, transcript probes, and the 1-second main loop." "daemon/__main__.py"
                hostServer = component "Embedded host server" "Serves /host on localhost:1234, mounts local feature routers, holds the host-browser WS, and reverse-proxies remaining HTTP/WS traffic to Railway." "daemon/host_server.py + daemon/host_proxy.py + daemon/host_ws.py"
                participantApis = component "Participant APIs" "Authoritative participant REST handlers for identity, quizzes, Q&A, debate, code review, misc actions, slides, emoji, and word cloud." "daemon/participant/router.py + daemon/quiz/router.py + daemon/qa/router.py + daemon/debate/router.py + daemon/codereview/router.py + daemon/misc/router.py + daemon/slides/router.py + daemon/emoji/router.py + daemon/wordcloud/router.py"
                hostApis = component "Host APIs" "Local host-side routers for session lifecycle, activity switching, leaderboard, host state snapshot, quiz queue, and per-feature host actions." "daemon/session/router.py + daemon/activity/router.py + daemon/leaderboard/router.py + daemon/host_state_router.py + daemon/quiz_queue/router.py + daemon/{quiz,qa,debate,codereview,wordcloud,misc}/router.py (host sub-routers)"
                runtimeState = component "Runtime state modules" "In-memory feature state for participants, quizzes, Q&A, debate, code review, misc data, leaderboard, scores, session stack, and word cloud." "daemon/*/state.py + daemon/scores.py + daemon/session/state.py"
                quizQueue = component "Quiz queue" "In-memory queue of pre-submitted quiz questions for one-at-a-time firing by the host." "daemon/quiz_queue/queue.py + daemon/quiz_queue/router.py"
                railwayBridge = component "Railway bridge" "Persistent /ws/daemon client, proxy response handling, typed broadcasts/notify_host, upload handoff, and static sync trigger." "daemon/ws_client.py + daemon/proxy_handler.py + daemon/ws_publish.py + daemon/upload.py + daemon/static_sync.py + daemon/ws_messages.py"
                sessionPersistence = component "Session persistence" "Persists global-state.json, session-state.json, session metadata, key points, and slide manifests." "daemon/session_state.py + daemon/persisted_models.py"
                debateCleanup = component "Debate AI cleanup" "Claude-backed argument dedupe, cleanup, and new-suggestion generation." "daemon/debate/ai_cleanup.py + daemon/llm/adapter.py"
                codereviewSmartPaste = component "Code-review smart paste" "Claude Haiku call that extracts a code snippet and language from pasted LLM output." "daemon/codereview/router.py + daemon/llm/adapter.py"
                summaryHelpers = component "Summary helpers" "File-driven helpers that read ai-summary.md and surface its mtime; consumed by misc routes and host snapshots." "daemon/summary/loop.py"
                slidesPipeline = component "Slides and upload pipeline" "Loads catalogs, tracks current slide, converts decks, invalidates Railway cache, scans PPTX mtimes, and pushes slide metadata/files." "daemon/slides/*"
                addonsBridge = component "Addons bridge" "Receives slide events, slides_viewed deltas, and IDE file-open events from victor-macos-addons, and forwards emoji/session notifications back." "daemon/addon_bridge_client.py + daemon/adapters/*"
                openedFilesLinking = component "Opened files linking" "Resolves IDE file-open events to GitHub blob links against the branch captured at open time (falling back to the repo default branch), and maintains the opened-files.md artifact; a standalone CLI re-resolves every link before summarization." "daemon/files_md.py + daemon/github_client.py + daemon/relink_open_files.py"
                transcriptIngest = component "Transcript ingest" "Loads normalized transcript files, tracks deltas, and exposes range queries used by quizzes and host inspection." "daemon/transcript/*"
                ragIndexer = component "Materials RAG indexer" "Background ChromaDB indexer over local workshop materials; retriever helpers available for future consumers." "daemon/rag/*"
                emailNotify = component "Email notifications" "Best-effort AgentMail-backed notifications for participant paste/feedback events." "daemon/email_notify.py"
                daemonTelemetry = component "Daemon telemetry" "OpenTelemetry tracer provider, file span exporter, and FastAPI/urllib instrumentation; also reused by the Railway process." "daemon/telemetry/*"
                lockHeartbeat = component "Lock and heartbeat" "Single-instance PID lock and heartbeat maintenance." "daemon/lock.py"
            }
        }

        participant -> participantSpa "Uses in browser"
        host -> hostSpa "Uses in browser"

        participantSpa -> railwayBackend "Calls session-scoped REST and WebSocket APIs"
        participantSpa -> nominatim "Reverse geocodes optional location"

        hostSpa -> trainingDaemon "Calls host REST and proxied WebSocket APIs on localhost"

        trainingDaemon -> railwayBackend "Synchronizes active session, participant events, uploads, and generated static assets"
        trainingDaemon -> claudeApi "Requests debate cleanup and code-review smart-paste extraction"
        trainingDaemon -> githubApi "Resolves opened-file blob links against repo trees and blobs"
        trainingDaemon -> macosAddons "WebSocket client to ws://127.0.0.1:8765: receives slide and IDE file-open events, sends display_emoji / session_started / session_ended / bell_ring / pdf_export_alarm"
        trainingDaemon -> agentMail "Sends best-effort email notifications via AgentMail SDK"
        trainingDaemon -> hostFiles "Reads and writes session folders, transcripts, and summary files"
        trainingDaemon -> localRag "Indexes local materials in the background"

        railwayBackend -> googleDrive "Downloads slide PDFs into cache"
        railwayBackend -> agentMail "Receives signed AgentMail webhooks for incoming Claude email"

        participantSpa -> pageRoutes "Loads participant pages"
        participantSpa -> wsBridge "Connects as participant and forwards REST commands via the daemon proxy"
        participantSpa -> slidesBridge "Reads slides and downloads PDFs"
        participantSpa -> uploadsBridge "Uploads participant files"
        participantSpa -> telemetryReceiver "Posts browser OTel spans (test/diagnostic mode)"

        hostSpa -> hostServer "Loads host pages and local APIs"

        bootstrap -> sharedCore "Initializes"
        bootstrap -> wsBridge "Registers"
        bootstrap -> pageRoutes "Registers"
        bootstrap -> slidesBridge "Registers"
        bootstrap -> uploadsBridge "Registers"
        bootstrap -> staticSync "Registers"
        bootstrap -> inboxBridge "Registers"
        bootstrap -> telemetryReceiver "Registers when OTEL_TRACES_FILE is set"

        wsBridge -> sharedCore "Reads auth, session, and connection state from"
        pageRoutes -> sharedCore "Uses auth/session helpers from"
        slidesBridge -> sharedCore "Reads slide/current-session state from"
        slidesBridge -> wsBridge "Uses daemon proxy and download protocol from"
        uploadsBridge -> sharedCore "Associates uploads with active participants from"
        uploadsBridge -> wsBridge "Uses daemon protocol helpers from"
        staticSync -> sharedCore "Uses host auth from"
        inboxBridge -> sharedCore "Stores the connected claude-inbox WebSocket on"
        wsBridge -> slidesBridge "Triggers slide cache downloads and broadcasts through"

        bootstrap -> daemonTelemetry "Configures OTel tracing and FastAPI instrumentation through (Railway side)"

        orchestrator -> daemonTelemetry "Configures OTel tracing on startup"
        orchestrator -> hostServer "Starts"
        orchestrator -> railwayBridge "Maintains"
        orchestrator -> sessionPersistence "Loads and flushes state through"
        orchestrator -> slidesPipeline "Triggers"
        orchestrator -> addonsBridge "Starts"
        orchestrator -> transcriptIngest "Polls for stats and time-window queries"
        orchestrator -> ragIndexer "Starts background materials indexer"
        orchestrator -> lockHeartbeat "Maintains"

        hostServer -> participantApis "Mounts"
        hostServer -> hostApis "Mounts"
        hostServer -> quizQueue "Mounts host quiz-queue routes"
        hostServer -> railwayBackend "Proxies unmatched HTTP and WebSocket traffic to"

        participantApis -> runtimeState "Mutates"
        participantApis -> railwayBridge "Publishes participant updates through"
        participantApis -> sessionPersistence "Reads current session metadata from"
        participantApis -> codereviewSmartPaste "Triggers Claude smart-paste extraction (host create path)"
        participantApis -> openedFilesLinking "Reads and serves opened-files.md through"

        hostApis -> runtimeState "Mutates"
        hostApis -> railwayBridge "Publishes host-driven updates through"
        hostApis -> sessionPersistence "Persists and restores session files through"
        hostApis -> slidesPipeline "Triggers"
        hostApis -> debateCleanup "Triggers"
        hostApis -> summaryHelpers "Reads ai-summary.md state through"
        hostApis -> quizQueue "Manages queued quiz questions through"

        runtimeState -> sessionPersistence "Is snapshotted by"

        railwayBridge -> railwayBackend "Connects over /ws/daemon and host-auth REST"
        railwayBridge -> sessionPersistence "Reads session metadata for sync payloads from"

        debateCleanup -> claudeApi "Requests cleanup suggestions from"
        debateCleanup -> railwayBridge "Publishes cleanup results through"

        codereviewSmartPaste -> claudeApi "Requests code/language extraction from"

        summaryHelpers -> hostFiles "Reads ai-summary.md and mtime from"

        slidesPipeline -> hostFiles "Reads slide catalogs and generated PDFs from"
        slidesPipeline -> railwayBridge "Publishes slide metadata/files through"
        slidesPipeline -> railwayBackend "Uses cache and upload helpers on"

        addonsBridge -> macosAddons "Connects over local WebSocket"
        addonsBridge -> slidesPipeline "Forwards slide events to"
        addonsBridge -> railwayBridge "Forwards emoji/session notifications through"
        addonsBridge -> openedFilesLinking "Forwards IDE file-open events to"

        openedFilesLinking -> githubApi "Resolves branch and default-branch blob links via"
        openedFilesLinking -> hostFiles "Reads and writes opened-files.md in"

        transcriptIngest -> hostFiles "Reads normalized transcript files from"

        ragIndexer -> hostFiles "Reads local materials from"
        ragIndexer -> localRag "Writes embeddings into"

        emailNotify -> agentMail "Sends notification emails via AgentMail SDK"
        participantApis -> emailNotify "Triggers paste/feedback notifications through"

        # ------------------------------------------------------------------
        # Victor's tooling ecosystem
        #
        # The workshop tool is one system among Victor's personal tools; this
        # block models the others so the landscape shows what talks to what and
        # OVER WHICH CHANNEL. Every relationship description carries the real
        # transport and the real port or path -- never a bare verb -- because
        # the channel is the thing that drifts and the thing nobody writes down.
        #
        # Derived from code, not from prose: ports come from the sources named
        # in docs/c4views/README.md#ecosystem. Kept fresh by the weekly doc
        # gardening pass (~/.claude/doc-gardening/prompt.md, Faza 1.5).
        # ------------------------------------------------------------------

        victorEffects   = softwareSystem "victor-effects" "Desktop effects, sounds, whip and the tile manifest. Menu bar 🎆, port 55124. Public repo." "Ecosystem"
        vibeBoard       = softwareSystem "victor-vibe-board" "LaunchBreak: the tablet soundboard (Kotlin, Android)." "Ecosystem"
        phoneAddons     = softwareSystem "victor-phone-addons" "Minimal app on the S24U phone; exists to be opened, which fires the Samsung hotspot routine." "Ecosystem"
        macKit          = softwareSystem "victor-mac-kit" "Shared SwiftPM package (crop selection overlay, geometry, capture). No app of its own." "Ecosystem"
        walkieTalkie    = softwareSystem "walkie-talkie" "macOS overlay that relays dictation, screenshots and picked elements into a running agent." "Ecosystem"
        wtChromeExt     = softwareSystem "walkie-talkie Chrome extension" "Element picking (⌘⇧) and the music bridge." "Ecosystem"
        addonsChromeExt = softwareSystem "Victor Chrome Addons" "Chrome extension feeding dictation and the feedback form to the Mac." "Ecosystem"
        liveCoding      = softwareSystem "live-coding" "IntelliJ plugin: live-coding visual effects and the IDE end of the relay." "Ecosystem"
        victorVsc       = softwareSystem "victor-vsc" "VS Code extension holding every customization (colors, icons, keybindings, terminal profiles)." "Ecosystem"
        victorStatusline = softwareSystem "victor-statusline" "Status line for Claude Code and Copilot CLI." "Ecosystem"
        gmailAddons     = softwareSystem "gmail-victor-addons" "Chrome extension + local daemon: CSS injection and smart search." "Ecosystem"
        gmailDarkCss    = softwareSystem "gmail-dark-css" "gmail.user.css -- the source of truth for Gmail dark mode." "Ecosystem"
        claudeCode      = softwareSystem "Claude Code" "The agent itself: hooks, skills, plugins, MCP servers." "Ecosystem"
        claudeUsage     = softwareSystem "claude-usage" "Reads Claude Code transcripts to report usage." "Ecosystem"
        victorSkills    = softwareSystem "victor-skills / skills-private / human-review" "Skill and plugin marketplaces." "Ecosystem"
        terminalApp     = softwareSystem "Terminal.app / tmux" "Where dictated sessions land." "Ecosystem"
        transcripts     = softwareSystem "Whisper transcripts" "~/Documents/transcriptions/ -- files on disk, written by the Mac and read by the daemon." "Ecosystem"

        victorCarduri   = softwareSystem "victor-carduri" "Loyalty cards on the phone. Deliberately isolated from the beacon app." "Island"
        codeCity        = softwareSystem "code-city" "3D city of classes, used as a course demo." "Island"
        codeSearch      = softwareSystem "code-search" "Semantic duplicate detection CLI (Ollama + Qdrant)." "Island"
        agenticHow      = softwareSystem "agentic.how" "Workshop landing page on cPanel." "Island"
        agenticWiki     = softwareSystem "agentic-wiki" "LLM wiki published with Quartz." "Island"
        personalSite    = softwareSystem "victorrentea.ro" "Personal static site." "Island"

        # --- tablet <-> Mac ---
        vibeBoard -> macosAddons "HTTP :55123, over the first transport that answers: adb reverse (USB) -> LAN -> mDNS Victor-Mac.local -> WSS relay"
        macosAddons -> vibeBoard "WSS wss://interact.victorrentea.ro/ws/bridge/tablet (last resort, when there is no LAN)"
        macosAddons -> victorEffects "HTTP proxy :55123 -> :55124 for /ping /sounds /sound /effect /alarm /bt-compensation /tiles /state"
        vibeBoard -> victorEffects "GET /tiles through the proxy. The Mac's manifest outranks the tablet's bundled tiles.json, which is first-boot bootstrap only"
        macosAddons -> phoneAddons "Bluetooth RFCOMM/SPP channel 9, which trips the Samsung hotspot routine"

        # --- Mac desktop ---
        addonsChromeExt -> macosAddons "WebSocket ws://127.0.0.1:8766 (dictation)"
        addonsChromeExt -> macosAddons "HTTP :55123/feedback-form/*"
        macosAddons -> workshop "POST 127.0.0.1:1234/feedback-form"
        macosAddons -> transcripts "Writes Whisper output to"
        trainingDaemon -> transcripts "Reads and tracks deltas of normalized transcripts from"
        victorVsc -> macosAddons "POST :55123/intellij/file-opened"
        liveCoding -> macosAddons "POST :55123/intellij/file-opened"
        macosAddons -> macKit "SwiftPM path dependency on ../victor-mac-kit"
        walkieTalkie -> macKit "SwiftPM path dependency on ../victor-mac-kit"

        # --- dictation -> agent ---
        walkieTalkie -> wtChromeExt "HTTP loopback :8917-8919 (/pick) and WebSocket :8920 (music bridge)"
        walkieTalkie -> liveCoding "POST to 127.0.0.1 on an ephemeral port published in ~/.walkie-talkie/ide/intellij-PID.json, authenticated with x-relay-token"
        walkieTalkie -> victorVsc "POST to 127.0.0.1 on an ephemeral port published in ~/.walkie-talkie/ide/vscode-PID.json"
        walkieTalkie -> terminalApp "AppleScript `do script`, or tmux send-keys addressed at a pane"
        terminalApp -> claudeCode "Runs interactive sessions"

        # --- browser / Gmail ---
        gmailAddons -> gmailDarkCss "Reads ../gmail-dark-css/gmail.user.css off disk, live, with no extension reload"
        gmailAddons -> claudeCode "Subprocess `claude -p --model claude-sonnet-5`, which reaches Gmail over MCP"

        # --- Claude Code as a participant, not just a tool ---
        claudeCode -> macosAddons "HTTP :55123/hands-off/{start,end,state} from the PreToolUse hook via ~/bin/hands-off"
        victorStatusline -> claudeCode "Symlinked in as ~/.claude/statusline-command.sh"
        victorSkills -> claudeCode "Plugin marketplaces: one git source, one local directory"
        claudeUsage -> claudeCode "Reads ~/.claude/projects/** transcripts"
    }

    views {
        systemLandscape "C1Ecosystem" "Every personal tool and the channel each integration actually runs over. Islands on the right are connected to nothing." {
            include workshop macosAddons victorEffects vibeBoard phoneAddons macKit
            include walkieTalkie wtChromeExt addonsChromeExt liveCoding victorVsc
            include victorStatusline gmailAddons gmailDarkCss claudeCode claudeUsage
            include victorSkills terminalApp transcripts
            include victorCarduri codeCity codeSearch agenticHow agenticWiki personalSite
            autoLayout lr
        }

        systemLandscape "C2EcosystemMac" "The Mac cluster on its own, where the ports matter: addons is the switchboard every other piece dials." {
            include macosAddons victorEffects vibeBoard phoneAddons macKit
            include addonsChromeExt victorVsc liveCoding claudeCode workshop transcripts
            autoLayout lr
        }

        systemContext workshop "C1SystemContext" "Overall system context." {
            include *
            autoLayout lr
        }

        container workshop "C2Containers" "Current runtime containers." {
            include *
            autoLayout lr
        }

        container workshop "C2DaemonFlow" "Focused container view around the daemon-first host control plane." {
            include host hostSpa trainingDaemon railwayBackend macosAddons claudeApi githubApi agentMail hostFiles localRag googleDrive
            autoLayout lr
        }

        container workshop "C2ParticipantFlow" "Focused container view around the participant journey." {
            include participant participantSpa railwayBackend trainingDaemon nominatim googleDrive
            autoLayout lr
        }

        container workshop "C2TrainingDaemonOnly" "Container view with only the local daemon and its immediate dependencies." {
            include trainingDaemon railwayBackend macosAddons claudeApi githubApi agentMail hostFiles localRag
            autoLayout lr
        }

        component railwayBackend "C3BackendOverview" "Main Railway backend subsystems present in the repository." {
            include *
            autoLayout lr
        }

        component railwayBackend "C3BackendRealtime" "Session-aware browser and daemon bridge slice." {
            include participantSpa hostSpa trainingDaemon bootstrap sharedCore wsBridge pageRoutes
            autoLayout lr
        }

        component railwayBackend "C3BackendSlidesAndUploads" "Slides, uploads, and static sync slice." {
            include participantSpa trainingDaemon bootstrap sharedCore slidesBridge uploadsBridge staticSync
            autoLayout lr
        }

        component railwayBackend "C3BackendInboxAndTelemetry" "Inbox webhook + browser telemetry receivers." {
            include participantSpa trainingDaemon bootstrap sharedCore inboxBridge telemetryReceiver agentMail
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOverview" "Main daemon subsystems aligned to the daemon-first runtime." {
            include *
            exclude orchestrator
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOnly" "Only the internal daemon subsystems, without Railway or external systems." {
            include orchestrator hostServer participantApis hostApis runtimeState quizQueue railwayBridge sessionPersistence debateCleanup codereviewSmartPaste summaryHelpers slidesPipeline addonsBridge openedFilesLinking transcriptIngest ragIndexer emailNotify daemonTelemetry lockHeartbeat
            autoLayout lr
        }

        component trainingDaemon "C3DaemonAi" "Daemon slice for Claude-backed AI features (debate cleanup + code-review smart paste)." {
            include hostApis participantApis debateCleanup codereviewSmartPaste railwayBridge claudeApi
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSlides" "Daemon slice for slide following, cache coordination, and uploads." {
            include orchestrator hostApis slidesPipeline railwayBridge sessionPersistence addonsBridge hostFiles railwayBackend macosAddons
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSummaryAndQuiz" "Daemon slice for file-driven summary helpers and the host quiz queue." {
            include hostApis summaryHelpers quizQueue railwayBridge sessionPersistence hostFiles
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOpenedFiles" "Daemon slice for opened-files tracking and GitHub link resolution." {
            include addonsBridge openedFilesLinking participantApis hostFiles githubApi macosAddons
            autoLayout lr
        }

        component trainingDaemon "C3DaemonNotifications" "Daemon slice for email notifications via AgentMail." {
            include participantApis emailNotify agentMail
            autoLayout lr
        }

        styles {
            element "Person" {
                background "#0b3d2c"
                color "#ffffff"
                shape person
            }
            element "Software System" {
                background "#1d6f42"
                color "#ffffff"
            }
            element "Container" {
                background "#5aa05a"
                color "#ffffff"
            }
            element "Component" {
                background "#d6e8c8"
                color "#10210f"
            }
            element "Ecosystem" {
                background "#2c5f8a"
                color "#ffffff"
            }
            element "Island" {
                background "#8d99a6"
                color "#ffffff"
            }
        }
    }
}
