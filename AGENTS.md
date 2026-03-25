## Reguli Persistente

- La începutul fiecărei sesiuni, citește `CLAUDE.md`.
- Când trebuie citite sau actualizate reguli, folosește `CLAUDE.md` ca sursă principală (nu Codem).
- Dacă există diferențe între reguli locale și `CLAUDE.md`, aliniază regulile locale la `CLAUDE.md` înainte de task-uri de cod.

## Transcript Debugging

When debugging transcript content in a specific time window, prefer:

```bash
./extract-transcripts.sh START_ISO END_ISO [TRANSCRIPTION_FOLDER]
```

Example:

```bash
./extract-transcripts.sh 2026-03-25T09:30 2026-03-25T17:30
```

Expected output:
- first line: summary per speaker + total duration in the requested interval
- next lines: `YYYY-MM-DDTHH:MM <transcript text>`

Do not use ad-hoc grep/sed first for this use case; use this script as the default debugging entrypoint.
