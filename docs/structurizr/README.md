# Structurizr Example

This folder contains a Structurizr DSL workspace aligned to the current repository structure.

Sources used for the model:

- `ARCHITECTURE.md`
- `main.py`
- the current `core/`, `features/`, and `daemon/` packages

It shows that Structurizr can render both:

- full C4 views such as C1 and C2
- focused slices, by defining separate views with targeted `include` statements

Examples included in [workspace.dsl](/Users/victorrentea/conductor/workspaces/training-assistant/geneva-v1/docs/structurizr/workspace.dsl):

- `C1SystemContext`
- `C2Containers`
- `C2DaemonFlow`
- `C2ParticipantFlow`
- `C2TrainingDaemonOnly`
- `C3BackendOverview`
- `C3BackendRealtime`
- `C3BackendSessionAndSlides`
- `C3DaemonOverview`
- `C3DaemonQuiz`
- `C3DaemonSlides`
- `C3DaemonSummary`

The DSL is intentionally closer to the codebase than to the older static diagrams, so it includes backend routers and daemon modules that already exist in the repo even if they are not all represented in `ARCHITECTURE.md`.

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
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/cli validate \
  -workspace docs/structurizr/workspace.dsl
```

## Export locally

PlantUML / C4-PlantUML export:

```bash
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/cli export \
  -workspace docs/structurizr/workspace.dsl \
  -format plantuml/c4plantuml \
  -output docs/structurizr/out
```

Mermaid export:

```bash
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/cli export \
  -workspace docs/structurizr/workspace.dsl \
  -format mermaid \
  -output docs/structurizr/out
```

## Browse interactively

Structurizr Lite serves the DSL locally in a browser:

```bash
docker run --rm -p 8080:8080 \
  -v "$PWD/docs/structurizr":/usr/local/structurizr \
  structurizr/lite
```

Then open `http://localhost:8080`.
