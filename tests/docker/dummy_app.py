"""Minimal FastAPI app to prove the container setup works."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return """<!DOCTYPE html>
<html><head><title>Hermetic Test</title></head>
<body>
  <h1 id="greeting">Hello from FastAPI in Docker!</h1>
  <p id="visitor">Visitor: <span id="name">anonymous</span></p>
  <script>
    // Each browser context gets its own localStorage
    const saved = localStorage.getItem('test_name');
    if (saved) document.getElementById('name').textContent = saved;
  </script>
</body></html>"""


@app.get("/set-name/{name}", response_class=HTMLResponse)
def set_name(name: str):
    return f"""<!DOCTYPE html>
<html><head><title>Set Name</title></head>
<body>
  <p id="result">Name set to: {name}</p>
  <script>localStorage.setItem('test_name', '{name}');</script>
</body></html>"""
