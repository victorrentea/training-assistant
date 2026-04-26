workspace "Workshop Live Interaction Tool" "Structurizr DSL model aligned to the current repository structure." {

    model {
        host = person "Host" "Runs the workshop, controls activities, and monitors the live session."
        participant = person "Participant" "Joins from a browser, votes, reacts, uploads, and follows the session."

        claudeApi = softwareSystem "Anthropic Claude API" "LLM used by the daemon for debate AI cleanup and code-review smart paste extraction."
        macosAddons = softwareSystem "victor-macos-addons" "Local Mac bridge that emits slide events and receives emoji/session notifications."
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
                participantApis = component "Participant APIs" "Authoritative participant REST handlers for identity, polls, Q&A, debate, code review, misc actions, slides, emoji, and word cloud." "daemon/participant/router.py + daemon/poll/router.py + daemon/qa/router.py + daemon/debate/router.py + daemon/codereview/router.py + daemon/misc/router.py + daemon/slides/router.py + daemon/emoji/router.py + daemon/wordcloud/router.py"
                hostApis = component "Host APIs" "Local host-side routers for session lifecycle, activity switching, leaderboard, host state snapshot, poll queue, and per-feature host actions." "daemon/session/router.py + daemon/activity/router.py + daemon/leaderboard/router.py + daemon/host_state_router.py + daemon/quiz/queue_router.py + daemon/{poll,qa,debate,codereview,wordcloud,misc}/router.py (host sub-routers)"
                runtimeState = component "Runtime state modules" "In-memory feature state for participants, polls, Q&A, debate, code review, misc data, leaderboard, scores, session stack, and word cloud." "daemon/*/state.py + daemon/scores.py + daemon/session/state.py"
                pollQueue = component "Poll queue" "In-memory queue of pre-submitted poll questions for one-at-a-time firing by the host." "daemon/quiz/queue.py + daemon/quiz/queue_router.py"
                railwayBridge = component "Railway bridge" "Persistent /ws/daemon client, proxy response handling, typed broadcasts/notify_host, upload handoff, and static sync trigger." "daemon/ws_client.py + daemon/proxy_handler.py + daemon/ws_publish.py + daemon/upload.py + daemon/static_sync.py + daemon/ws_messages.py"
                sessionPersistence = component "Session persistence" "Persists global-state.json, session-state.json, session metadata, key points, and slide manifests." "daemon/session_state.py + daemon/persisted_models.py"
                debateCleanup = component "Debate AI cleanup" "Claude-backed argument dedupe, cleanup, and new-suggestion generation." "daemon/debate/ai_cleanup.py + daemon/llm/adapter.py"
                codereviewSmartPaste = component "Code-review smart paste" "Claude Haiku call that extracts a code snippet and language from pasted LLM output." "daemon/codereview/router.py + daemon/llm/adapter.py"
                summaryHelpers = component "Summary helpers" "File-driven helpers that read ai-summary.md and surface its mtime; consumed by misc routes and host snapshots." "daemon/summary/loop.py"
                slidesPipeline = component "Slides and upload pipeline" "Loads catalogs, tracks current slide, converts decks, invalidates Railway cache, scans PPTX mtimes, and pushes slide metadata/files." "daemon/slides/*"
                addonsBridge = component "Addons bridge" "Receives slide events and slides_viewed deltas from victor-macos-addons and forwards emoji/session notifications back." "daemon/addon_bridge_client.py + daemon/adapters/*"
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
        trainingDaemon -> macosAddons "Receives slide events and sends emoji/session notifications"
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
        hostServer -> pollQueue "Mounts host poll-queue routes"
        hostServer -> railwayBackend "Proxies unmatched HTTP and WebSocket traffic to"

        participantApis -> runtimeState "Mutates"
        participantApis -> railwayBridge "Publishes participant updates through"
        participantApis -> sessionPersistence "Reads current session metadata from"
        participantApis -> codereviewSmartPaste "Triggers Claude smart-paste extraction (host create path)"

        hostApis -> runtimeState "Mutates"
        hostApis -> railwayBridge "Publishes host-driven updates through"
        hostApis -> sessionPersistence "Persists and restores session files through"
        hostApis -> slidesPipeline "Triggers"
        hostApis -> debateCleanup "Triggers"
        hostApis -> summaryHelpers "Reads ai-summary.md state through"
        hostApis -> pollQueue "Manages queued poll questions through"

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

        transcriptIngest -> hostFiles "Reads normalized transcript files from"

        ragIndexer -> hostFiles "Reads local materials from"
        ragIndexer -> localRag "Writes embeddings into"

        emailNotify -> agentMail "Sends notification emails via AgentMail SDK"
        participantApis -> emailNotify "Triggers paste/feedback notifications through"
    }

    views {
        systemContext workshop "C1SystemContext" "Overall system context." {
            include *
            autoLayout lr
        }

        container workshop "C2Containers" "Current runtime containers." {
            include *
            autoLayout lr
        }

        container workshop "C2DaemonFlow" "Focused container view around the daemon-first host control plane." {
            include host hostSpa trainingDaemon railwayBackend macosAddons claudeApi agentMail hostFiles localRag googleDrive
            autoLayout lr
        }

        container workshop "C2ParticipantFlow" "Focused container view around the participant journey." {
            include participant participantSpa railwayBackend trainingDaemon nominatim googleDrive
            autoLayout lr
        }

        container workshop "C2TrainingDaemonOnly" "Container view with only the local daemon and its immediate dependencies." {
            include trainingDaemon railwayBackend macosAddons claudeApi agentMail hostFiles localRag
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
            include orchestrator hostServer participantApis hostApis runtimeState pollQueue railwayBridge sessionPersistence debateCleanup codereviewSmartPaste summaryHelpers slidesPipeline addonsBridge transcriptIngest ragIndexer emailNotify daemonTelemetry lockHeartbeat
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

        component trainingDaemon "C3DaemonSummaryAndPolls" "Daemon slice for file-driven summary helpers and the host poll queue." {
            include hostApis summaryHelpers pollQueue railwayBridge sessionPersistence hostFiles
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
        }
    }
}
