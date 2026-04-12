workspace "Workshop Live Interaction Tool" "Structurizr DSL model aligned to the current repository structure." {

    model {
        host = person "Host" "Runs the workshop, controls activities, and monitors the live session."
        participant = person "Participant" "Joins from a browser, votes, reacts, uploads, and follows the session."

        claudeApi = softwareSystem "Anthropic Claude API" "LLM used by the daemon for quiz generation/refinement and debate cleanup."
        macosAddons = softwareSystem "victor-macos-addons" "Local Mac bridge that emits slide events and receives emoji/session notifications."
        nominatim = softwareSystem "Nominatim" "Reverse geocodes GPS coordinates into city and country."
        googleDrive = softwareSystem "Google Drive" "Hosts exported slide PDFs consumed by the Railway cache."
        hostFiles = softwareSystem "Host session files" "Session folders, normalized transcripts, ai-summary.md, uploaded files, and slide manifests on the trainer's Mac."
        localRag = softwareSystem "Local ChromaDB store" "~/.workshop-rag/chroma"

        workshop = softwareSystem "Workshop Live Interaction Tool" "Self-hosted real-time audience interaction platform." {
            participantSpa = container "Participant SPA" "Participant-facing UI served from Railway session routes." "HTML/CSS/JavaScript"
            hostSpa = container "Host SPA" "Host control panel served from the daemon host server on localhost." "HTML/CSS/JavaScript"
            railwayBackend = container "Railway Backend" "Thin session-aware bridge for participants, slides, uploads, and daemon sync." "Python 3.12 / FastAPI / Uvicorn" {
                bootstrap = component "Bootstrap" "Registers route ordering, session guards, and startup stamping." "railway/app.py"
                sharedCore = component "Shared Core" "AppState, auth, session registry/guard, metrics, messaging, and version helpers." "shared/*"
                wsBridge = component "WebSocket bridge" "Daemon auth, session-scoped browser sockets, participant proxy bridge, and broadcast fan-out." "features/ws/*"
                pageRoutes = component "Page routes" "Landing, participant, notes, quiz history, and remote host pages." "features/pages/router.py"
                publicNotes = component "Public notes and key points" "Session-scoped summary and notes endpoints." "features/session/notes_router.py"
                slidesBridge = component "Slides cache and file serving" "Public slide catalog/current slide, Google Drive cache, and host upload/invalidate helpers." "features/slides/*"
                uploadsBridge = component "Temporary upload bridge" "Streams participant uploads into temporary storage and lets the daemon fetch and acknowledge them." "features/upload/*"
                staticSync = component "Static sync endpoints" "Allows the daemon to upload and delete generated files under static/." "features/internal/router.py"
            }
            trainingDaemon = container "Training Daemon" "Local source of truth for host control, live state, persistence, and AI-assisted jobs." "Python 3.12 CLI + embedded FastAPI" {
                orchestrator = component "Orchestrator" "Starts the lock/heartbeat, host server, daemon WS client, addons bridge, slide runner, summary loop, and the 1-second main loop." "daemon/__main__.py"
                hostServer = component "Embedded host server" "Serves /host, mounts local feature routers, and proxies remaining HTTP/WS traffic to Railway." "daemon/host_server.py + daemon/host_proxy.py + daemon/host_ws.py"
                participantApis = component "Participant APIs" "Authoritative participant REST handlers for identity, polls, Q&A, debate, code review, misc actions, slides, emoji, and word cloud." "daemon/participant/router.py + daemon/poll/router.py + daemon/qa/router.py + daemon/debate/router.py + daemon/codereview/router.py + daemon/misc/router.py + daemon/slides/router.py + daemon/emoji/router.py + daemon/wordcloud/router.py"
                hostApis = component "Host APIs" "Local host-side routers for session lifecycle, activity switching, quiz requests, leaderboard control, host state, uploads, and feature administration." "daemon/session/router.py + daemon/activity/router.py + daemon/quiz/router.py + daemon/leaderboard/router.py + daemon/host_state_router.py + daemon/misc/router.py + daemon/poll/router.py + daemon/qa/router.py + daemon/debate/router.py + daemon/codereview/router.py + daemon/wordcloud/router.py"
                runtimeState = component "Runtime state modules" "In-memory feature state for participants, polls, Q&A, debate, code review, misc data, leaderboard, session stack, and word cloud." "daemon/*/state.py"
                railwayBridge = component "Railway bridge" "Persistent /ws/daemon client, proxy response handling, typed broadcasts, upload handoff, and static sync." "daemon/ws_client.py + daemon/proxy_handler.py + daemon/ws_publish.py + daemon/upload.py + daemon/static_sync.py"
                sessionPersistence = component "Session persistence" "Persists global-state.json, session-state.json, session metadata, key points, and slide manifests." "daemon/session_state.py + daemon/persisted_models.py"
                quizPipeline = component "Quiz pipeline" "Generates and refines quiz suggestions from notes, key points, transcripts, and local materials." "daemon/quiz/* + daemon/llm/adapter.py + daemon/rag/*"
                debateCleanup = component "Debate AI cleanup" "Claude-backed argument dedupe, cleanup, and new suggestion generation." "daemon/debate/ai_cleanup.py"
                summaryLoop = component "Summary loop" "Reads ai-summary.md, refreshes key points, and republishes summary state." "daemon/summary/loop.py + daemon/transcript/*"
                slidesPipeline = component "Slides and upload pipeline" "Loads catalogs, tracks current slide, converts decks, invalidates Railway cache, and pushes slide metadata/files." "daemon/slides/*"
                addonsBridge = component "Addons bridge" "Receives slide events from victor-macos-addons and forwards emoji/session notifications back." "daemon/addon_bridge_client.py + daemon/adapters/*"
                lockHeartbeat = component "Lock and heartbeat" "Single-instance PID lock and heartbeat maintenance." "daemon/lock.py"
            }
        }

        participant -> participantSpa "Uses in browser"
        host -> hostSpa "Uses in browser"

        participantSpa -> railwayBackend "Calls session-scoped REST and WebSocket APIs"
        participantSpa -> nominatim "Reverse geocodes optional location"

        hostSpa -> trainingDaemon "Calls host REST and proxied WebSocket APIs on localhost"

        trainingDaemon -> railwayBackend "Synchronizes active session, participant events, uploads, and generated static assets"
        trainingDaemon -> claudeApi "Requests quiz generation/refinement and debate cleanup"
        trainingDaemon -> macosAddons "Receives slide events and sends emoji/session notifications"
        trainingDaemon -> hostFiles "Reads and writes session folders and summary files"
        trainingDaemon -> localRag "Indexes and queries local materials"

        railwayBackend -> googleDrive "Downloads slide PDFs into cache"

        participantSpa -> pageRoutes "Loads participant and notes pages"
        participantSpa -> wsBridge "Connects as participant"
        participantSpa -> publicNotes "Reads notes and key points"
        participantSpa -> slidesBridge "Reads slides and downloads PDFs"
        participantSpa -> uploadsBridge "Uploads participant files"

        hostSpa -> hostServer "Loads host pages and local APIs"

        bootstrap -> sharedCore "Initializes"
        bootstrap -> wsBridge "Registers"
        bootstrap -> pageRoutes "Registers"
        bootstrap -> publicNotes "Registers"
        bootstrap -> slidesBridge "Registers"
        bootstrap -> uploadsBridge "Registers"
        bootstrap -> staticSync "Registers"

        wsBridge -> sharedCore "Reads auth, session, and connection state from"
        pageRoutes -> sharedCore "Uses auth/session helpers from"
        publicNotes -> sharedCore "Reads mirrored summary state from"
        slidesBridge -> sharedCore "Reads slide/current-session state from"
        slidesBridge -> wsBridge "Uses daemon proxy and download protocol from"
        uploadsBridge -> sharedCore "Associates uploads with active participants from"
        uploadsBridge -> wsBridge "Uses daemon protocol helpers from"
        staticSync -> sharedCore "Uses host auth from"

        wsBridge -> slidesBridge "Triggers slide cache downloads and broadcasts through"

        orchestrator -> hostServer "Starts"
        orchestrator -> railwayBridge "Maintains"
        orchestrator -> sessionPersistence "Loads and flushes state through"
        orchestrator -> summaryLoop "Triggers"
        orchestrator -> slidesPipeline "Triggers"
        orchestrator -> addonsBridge "Starts"
        orchestrator -> lockHeartbeat "Maintains"

        hostServer -> participantApis "Mounts"
        hostServer -> hostApis "Mounts"
        hostServer -> railwayBackend "Proxies unmatched HTTP and WebSocket traffic to"

        participantApis -> runtimeState "Mutates"
        participantApis -> railwayBridge "Publishes participant updates through"
        participantApis -> sessionPersistence "Reads current session metadata from"

        hostApis -> runtimeState "Mutates"
        hostApis -> railwayBridge "Publishes host-driven updates through"
        hostApis -> sessionPersistence "Persists and restores session files through"
        hostApis -> quizPipeline "Triggers"
        hostApis -> slidesPipeline "Triggers"
        hostApis -> debateCleanup "Triggers"

        runtimeState -> sessionPersistence "Is snapshotted by"

        railwayBridge -> railwayBackend "Connects over /ws/daemon and host-auth REST"
        railwayBridge -> sessionPersistence "Reads session metadata for sync payloads from"

        quizPipeline -> hostFiles "Reads notes, transcripts, and local materials from"
        quizPipeline -> localRag "Retrieves indexed local context from"
        quizPipeline -> claudeApi "Requests quiz drafts and refinements from"
        quizPipeline -> railwayBridge "Publishes quiz status through"

        debateCleanup -> claudeApi "Requests cleanup suggestions from"
        debateCleanup -> railwayBridge "Publishes cleanup results through"

        summaryLoop -> hostFiles "Reads ai-summary.md and key points from"
        summaryLoop -> railwayBridge "Publishes summary state through"

        slidesPipeline -> hostFiles "Reads slide catalogs and generated PDFs from"
        slidesPipeline -> railwayBridge "Publishes slide metadata/files through"
        slidesPipeline -> railwayBackend "Uses cache and upload helpers on"

        addonsBridge -> macosAddons "Connects over local WebSocket"
        addonsBridge -> slidesPipeline "Forwards slide events to"
        addonsBridge -> railwayBridge "Forwards emoji/session notifications through"
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
            include host hostSpa trainingDaemon railwayBackend macosAddons claudeApi hostFiles localRag googleDrive
            autoLayout lr
        }

        container workshop "C2ParticipantFlow" "Focused container view around the participant journey." {
            include participant participantSpa railwayBackend trainingDaemon nominatim googleDrive
            autoLayout lr
        }

        container workshop "C2TrainingDaemonOnly" "Container view with only the local daemon and its immediate dependencies." {
            include trainingDaemon railwayBackend macosAddons claudeApi hostFiles localRag
            autoLayout lr
        }

        component railwayBackend "C3BackendOverview" "Main Railway backend subsystems present in the repository." {
            include *
            autoLayout lr
        }

        component railwayBackend "C3BackendRealtime" "Session-aware browser and daemon bridge slice." {
            include participantSpa hostSpa trainingDaemon bootstrap sharedCore wsBridge pageRoutes publicNotes
            autoLayout lr
        }

        component railwayBackend "C3BackendSessionAndSlides" "Public notes, slides, uploads, and static sync slice." {
            include participantSpa trainingDaemon bootstrap sharedCore publicNotes slidesBridge uploadsBridge staticSync
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOverview" "Main daemon subsystems aligned to the daemon-first runtime." {
            include *
            exclude orchestrator
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOnly" "Only the internal daemon subsystems, without Railway or external systems." {
            include orchestrator hostServer participantApis hostApis runtimeState railwayBridge sessionPersistence quizPipeline debateCleanup summaryLoop slidesPipeline addonsBridge lockHeartbeat
            autoLayout lr
        }

        component trainingDaemon "C3DaemonQuiz" "Daemon slice for quiz generation and refinement." {
            include hostApis quizPipeline sessionPersistence railwayBridge hostFiles localRag claudeApi
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSlides" "Daemon slice for slide following, cache coordination, and uploads." {
            include orchestrator hostApis slidesPipeline railwayBridge sessionPersistence addonsBridge hostFiles railwayBackend macosAddons
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSummary" "Daemon slice for file-driven summary publication and key-point refresh." {
            include orchestrator hostApis summaryLoop railwayBridge sessionPersistence hostFiles
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
