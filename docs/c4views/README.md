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
