workspace "Workshop Live Interaction Tool" "Structurizr DSL model aligned to the current repository structure." {

    model {
        host = person "Host" "Runs the workshop, controls activities, and monitors the live session."
        participant = person "Participant" "Joins from a browser, votes, reacts, uploads, and follows the session."

        macosAddons = softwareSystem "victor-macos-addons" "Produces normalized transcript files on the trainer's Mac."
        claudeApi = softwareSystem "Anthropic Claude API" "LLM used for quiz generation, debate cleanup, and summaries."
        nominatim = softwareSystem "Nominatim" "Reverse geocodes GPS coordinates into city and country."
        googleDrive = softwareSystem "Google Drive" "Hosts exported slide PDFs consumed by the backend."

        workshop = softwareSystem "Workshop Live Interaction Tool" "Self-hosted real-time audience interaction platform." {
            participantSpa = container "Participant SPA" "Participant-facing UI served from static files." "HTML/CSS/JavaScript"
            hostSpa = container "Host SPA" "Host control panel served from static files." "HTML/CSS/JavaScript"
            fastapi = container "FastAPI Backend" "REST endpoints, WebSocket hub, session routing, and in-memory state." "Python 3.12 / FastAPI / Uvicorn" {
                corePlatform = component "Core Platform" "AppState, auth, metrics, versioning, session guards, and messaging registry." "core/*"
                wsRouter = component "WS Router" "Host, participant, overlay, and daemon WebSocket endpoints plus proxy bridge." "features/ws/*"
                pollRouter = component "Poll Router" "Poll lifecycle, status, correct answers, scoring, and public helpers." "features/poll/*"
                qaRouter = component "Q&A Router" "Question edit, delete, answer, and clear lifecycle." "features/qa/*"
                wordcloudRouter = component "Word Cloud Router" "Topic changes and reset operations." "features/wordcloud/*"
                codeReviewRouter = component "Code Review Router" "Snippet lifecycle, selections, and line confirmation." "features/codereview/*"
                debateRouter = component "Debate Router" "Debate phases, AI request lifecycle, and round orchestration." "features/debate/*"
                quizRouter = component "Quiz Router" "Quiz request, status, preview, and refinement endpoints." "features/quiz/*"
                summaryRouter = component "Summary Router" "Summaries, notes, transcript status, and token usage." "features/summary/*"
                leaderboardRouter = component "Leaderboard Router" "Leaderboard reveal and score reset endpoints." "features/leaderboard/*"
                activityRouter = component "Activity Router" "Switches the currently active participant experience." "features/activity/*"
                sessionRouter = component "Session Router" "Global and session-scoped lifecycle, sync, snapshots, and timing events." "features/session/*"
                snapshotRouter = component "Snapshot Router" "Diagnostic state snapshot and restore endpoints." "features/snapshot/*"
                slidesRouter = component "Slides Router" "Slides publishing, public file serving, upload, and catalog management." "features/slides/*"
                uploadRouter = component "Upload Router" "Participant and host file upload endpoints." "features/upload/*"
                pagesRouter = component "Pages Router" "Landing, participant, host, and notes pages." "features/pages/*"
                feedbackRouter = component "Feedback Router" "Global feedback endpoint." "features/feedback/*"
                internalRouter = component "Internal Router" "Daemon-facing internal file-management endpoints." "features/internal/*"
                transcriptionLanguageRouter = component "Transcription Language Router" "Global transcription language endpoint." "features/transcription_language/*"
                scoresRouter = component "Scores Router" "Score reset helper endpoints." "features/scores/*"
            }
            trainingDaemon = container "Training Daemon" "Background worker running on the host machine." "Python 3.12 CLI" {
                orchestrator = component "Orchestrator" "Main loop, startup binding, polling, and restart coordination." "daemon/__main__.py"
                configHttp = component "Config + HTTP" "Environment config and shared HTTP helpers." "daemon/config.py + daemon/http.py"
                wsClient = component "Daemon WS Client" "WebSocket channel used for daemon sync and uploads." "daemon/ws_client.py"
                sessionState = component "Session State" "Persists daemon stack and synchronizes session snapshots with backend." "daemon/session_state.py"
                quizGenerator = component "Quiz Generator" "Builds quiz suggestions from transcript or topic context." "daemon/quiz/generator.py"
                quizHistory = component "Quiz History" "Prevents repeated quiz questions." "daemon/quiz/history.py"
                quizApi = component "Quiz Poll API" "Polls quiz requests and posts previews/status." "daemon/quiz/poll_api.py"
                debateAi = component "Debate AI Cleanup" "Cleans up debate arguments and posts AI suggestions." "daemon/debate/ai_cleanup.py"
                summaryLoop = component "Summary Loop" "Triggers summary generation cycles and publishes results." "daemon/summary/loop.py"
                summarizer = component "Summarizer" "Extracts discussion points and notes from transcript deltas." "daemon/summary/summarizer.py"
                transcriptLoader = component "Transcript Loader" "Loads and filters normalized transcript windows." "daemon/transcript/loader.py"
                transcriptParser = component "Transcript Parser" "Parses transcript files such as txt, vtt, and srt." "daemon/transcript/parser.py"
                transcriptSession = component "Transcript Session" "Computes active transcript windows per session." "daemon/transcript/session.py"
                transcriptState = component "Transcript State" "Tracks transcript processing state." "daemon/transcript/state.py"
                slidesLoop = component "Slides Loop" "Polls for slide work and orchestrates conversions/uploads." "daemon/slides/loop.py"
                slidesCatalog = component "Slides Catalog" "Reads and resolves slide catalog entries." "daemon/slides/catalog.py"
                slidesConvert = component "Slides Convert" "Converts PPTX to PDF via host tooling." "daemon/slides/convert.py"
                slidesUpload = component "Slides Upload" "Uploads converted slide PDFs to the backend." "daemon/slides/upload.py"
                slidesDaemon = component "Slides Daemon" "Coordinates slide upload workflow over WebSocket." "daemon/slides/daemon.py"
                materialsMirror = component "Materials Mirror" "Mirrors project files for backend-side materials access." "daemon/materials/mirror.py"
                ragIndexer = component "RAG Indexer" "Indexes local project files for retrieval." "daemon/rag/indexer.py"
                ragRetriever = component "RAG Retriever" "Retrieves relevant context for quiz generation." "daemon/rag/retriever.py"
                projectFiles = component "Project Files Scanner" "Scans repository files for RAG and tooling." "daemon/rag/project_files.py"
                llmAdapter = component "LLM Adapter" "Claude client wrapper with token accounting." "daemon/llm/adapter.py"
                processLock = component "Process Lock" "Single-instance PID lock and heartbeat." "daemon/lock.py"
            }
            emojiOverlay = container "Emoji Overlay" "Always-on-top overlay for live emoji reactions on the host machine." "Swift / AppKit"
        }

        participant -> participantSpa "Uses in browser"
        host -> hostSpa "Uses in browser"
        host -> trainingDaemon "Starts and monitors locally"
        host -> emojiOverlay "Starts locally"

        participantSpa -> fastapi "Calls public REST and WebSocket APIs"
        participantSpa -> nominatim "Reverse geocodes location"
        hostSpa -> fastapi "Calls host REST and WebSocket APIs"
        emojiOverlay -> fastapi "Receives live emoji reactions"
        macosAddons -> trainingDaemon "Writes transcript files read by"
        trainingDaemon -> fastapi "Polls, syncs, uploads, and publishes"
        trainingDaemon -> claudeApi "Requests LLM completions"
        fastapi -> googleDrive "Downloads exported slide PDFs"

        participantSpa -> pagesRouter "Loads participant and notes pages"
        participantSpa -> wsRouter "Connects as participant"
        participantSpa -> pollRouter "Reads status and identity helpers"
        participantSpa -> summaryRouter "Reads public notes and summaries"
        participantSpa -> slidesRouter "Reads public slides"
        participantSpa -> uploadRouter "Uploads participant files"

        hostSpa -> pagesRouter "Loads host page"
        hostSpa -> wsRouter "Connects as host"
        hostSpa -> pollRouter "Creates polls and manages poll state"
        hostSpa -> qaRouter "Moderates questions"
        hostSpa -> wordcloudRouter "Sets topic and clears cloud"
        hostSpa -> codeReviewRouter "Manages code review activity"
        hostSpa -> debateRouter "Controls debate phases and cleanup"
        hostSpa -> leaderboardRouter "Reveals leaderboard"
        hostSpa -> activityRouter "Switches activity"
        hostSpa -> quizRouter "Requests and refines quizzes"
        hostSpa -> summaryRouter "Reads notes and summaries"
        hostSpa -> slidesRouter "Publishes current slides"
        hostSpa -> sessionRouter "Controls session lifecycle"
        hostSpa -> snapshotRouter "Requests snapshot/restore"
        hostSpa -> uploadRouter "Uploads host files"
        hostSpa -> feedbackRouter "Sends feedback"
        hostSpa -> scoresRouter "Resets scores"
        hostSpa -> transcriptionLanguageRouter "Changes transcription language"

        emojiOverlay -> wsRouter "Connects as overlay"

        internalRouter -> corePlatform "Uses shared backend state"
        feedbackRouter -> corePlatform "Updates shared state if needed"
        transcriptionLanguageRouter -> corePlatform "Reads current session context"
        uploadRouter -> corePlatform "Associates uploads with active state"
        pagesRouter -> corePlatform "Reads active mode and session state"
        wsRouter -> corePlatform "Builds and broadcasts state"
        pollRouter -> corePlatform "Mutates poll state and scores"
        qaRouter -> corePlatform "Mutates Q&A state"
        wordcloudRouter -> corePlatform "Mutates word cloud state"
        codeReviewRouter -> corePlatform "Mutates code review state"
        debateRouter -> corePlatform "Mutates debate state"
        quizRouter -> corePlatform "Stores quiz generation state"
        summaryRouter -> corePlatform "Reads and updates summaries and notes"
        leaderboardRouter -> corePlatform "Updates leaderboard visibility and scores"
        activityRouter -> corePlatform "Updates current activity"
        sessionRouter -> corePlatform "Serializes and restores session state"
        snapshotRouter -> corePlatform "Serializes and restores diagnostic snapshots"
        slidesRouter -> corePlatform "Stores slide catalog and current slide"
        scoresRouter -> corePlatform "Resets score state"

        orchestrator -> configHttp "Uses"
        orchestrator -> wsClient "Maintains daemon WebSocket"
        orchestrator -> sessionState "Loads and saves daemon/session state"
        orchestrator -> summaryLoop "Triggers"
        orchestrator -> slidesLoop "Triggers"
        orchestrator -> materialsMirror "Triggers"
        orchestrator -> processLock "Maintains"
        orchestrator -> transcriptSession "Computes active windows with"

        configHttp -> fastapi "Calls host-protected HTTP endpoints"
        wsClient -> fastapi "Connects to daemon WebSocket endpoint"
        sessionState -> fastapi "Synchronizes snapshots and active session"

        quizApi -> fastapi "Polls quiz endpoints and posts preview/status"
        quizApi -> quizGenerator "Triggers generation"
        quizGenerator -> transcriptLoader "Reads transcript context from"
        quizGenerator -> ragRetriever "Retrieves project context from"
        quizGenerator -> quizHistory "Checks against"
        quizGenerator -> llmAdapter "Requests quiz suggestions from"

        debateAi -> fastapi "Polls AI cleanup endpoints"
        debateAi -> llmAdapter "Requests cleanup suggestions from"

        summaryLoop -> summarizer "Triggers"
        summaryLoop -> fastapi "Posts summaries and transcript status"
        summarizer -> transcriptLoader "Reads transcript deltas from"
        summarizer -> llmAdapter "Requests summary output from"

        transcriptLoader -> transcriptParser "Parses files through"
        transcriptLoader -> transcriptState "Tracks processing through"

        slidesLoop -> slidesCatalog "Reads catalog from"
        slidesLoop -> slidesConvert "Triggers PDF conversion in"
        slidesLoop -> slidesDaemon "Coordinates upload flow with"
        slidesDaemon -> slidesUpload "Delegates uploads to"
        slidesUpload -> wsClient "Streams slide artifacts through"

        materialsMirror -> projectFiles "Scans repository through"
        materialsMirror -> fastapi "Synchronizes mirrored materials"
        ragIndexer -> projectFiles "Indexes files from"
        ragRetriever -> ragIndexer "Queries"
        llmAdapter -> claudeApi "Calls"
    }

    views {
        systemContext workshop "C1SystemContext" "Overall system context." {
            include *
            autoLayout lr
        }

        container workshop "C2Containers" "All runtime containers in the current repository." {
            include *
            autoLayout lr
        }

        container workshop "C2DaemonFlow" "Focused container view around the daemon and AI/slides integrations." {
            include host trainingDaemon fastapi macosAddons claudeApi googleDrive
            autoLayout lr
        }

        container workshop "C2ParticipantFlow" "Focused container view around the participant journey." {
            include participant participantSpa fastapi nominatim
            autoLayout lr
        }

        component fastapi "C3BackendOverview" "Main backend components registered in main.py." {
            include *
            autoLayout lr
        }

        component fastapi "C3BackendRealtime" "Realtime-focused backend slice." {
            include hostSpa participantSpa wsRouter pollRouter qaRouter wordcloudRouter codeReviewRouter debateRouter leaderboardRouter activityRouter corePlatform
            autoLayout lr
        }

        component fastapi "C3BackendSessionAndSlides" "Session, snapshot, slides, upload, and summary slice." {
            include hostSpa participantSpa trainingDaemon sessionRouter snapshotRouter slidesRouter uploadRouter summaryRouter pagesRouter transcriptionLanguageRouter internalRouter corePlatform
            autoLayout lr
        }

        component trainingDaemon "C3DaemonOverview" "Main daemon subsystems present in the repository." {
            include *
            autoLayout lr
        }

        component trainingDaemon "C3DaemonQuiz" "Daemon slice for quiz generation." {
            include orchestrator quizApi quizGenerator quizHistory transcriptLoader ragRetriever ragIndexer projectFiles llmAdapter fastapi claudeApi
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSlides" "Daemon slice for slide conversion and upload." {
            include orchestrator slidesLoop slidesCatalog slidesConvert slidesDaemon slidesUpload wsClient fastapi
            autoLayout lr
        }

        component trainingDaemon "C3DaemonSummary" "Daemon slice for transcript-driven summaries." {
            include orchestrator summaryLoop summarizer transcriptLoader transcriptParser transcriptState transcriptSession llmAdapter fastapi macosAddons claudeApi
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
