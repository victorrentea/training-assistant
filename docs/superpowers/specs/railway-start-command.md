# Railway Start Command (Manual Step)

Update the Railway dashboard start command to:

```
echo "window.APP_VERSION = '$(date -u '+%Y-%m-%d %H:%M')';" > static/version.js && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

This generates `static/version.js` at deploy time with the current UTC timestamp.

Previous command (if any): `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`
