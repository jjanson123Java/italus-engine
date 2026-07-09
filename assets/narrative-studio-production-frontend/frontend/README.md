# Narrative Studio Frontend

Production-ready static frontend shell for Narrative Studio.

## Run

Open `index.html` directly, or serve the `frontend/` folder from FastAPI.

Example FastAPI static mount:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()
app.mount("/assets", StaticFiles(directory="frontend/assets"), name="assets")

@app.get("/")
def index():
    return FileResponse("frontend/index.html")
```

If `styles.css` and `script.js` are served alongside `index.html`, no build step is required.

## Notes

- No React, Vue, Angular, Tailwind, Bootstrap, jQuery, npm, or bundler.
- UI components are real HTML/CSS.
- `assets/concept-reference-approved.png` is included only as a design reference.
- `assets/library-desk-bg.jpg` is decorative background only.
- Navigation and project card links are dummy anchors ready for FastAPI routing.
