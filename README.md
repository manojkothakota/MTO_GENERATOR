# Isometric Drawing → Automated MTO Generator

Upload one piping isometric drawing (PNG / JPG / PDF) and get back a structured
Material Take-Off (MTO): a table of pipe, fittings, flanges, valves, gaskets and
bolt sets, with CSV export.

## Live Demo

**App:** [https://mto-generator-alpha.vercel.app/](https://mto-generator-alpha.vercel.app/)

**Backend API:** `https://mto-generator-jok9.onrender.com`

> Note: the backend is on Render's free tier and cold-starts after inactivity —
> the first upload after idling may take ~30–50s while the server spins up.
> The UI's "processing" spinner covers this gracefully.



## 1. Architecture

```
┌─────────────┐   multipart/form-data    ┌────────────────────────────┐
│  Next.js    │ ───────────────────────▶ │  FastAPI                  │
│  frontend   │  POST /api/upload        │  /api/upload               │
│             │ ◀─────────────────────── │    -> preprocess (PDF→PNG) │
│  upload +   │   { job_id }             │    -> Groq vision call      │
│  results UI │                          │       (or MOCK if no key)  │
│             │  GET /api/mto/{id}       │    -> Pydantic validation   │
│             │ ◀─────────────────────── │    -> derive gasket/bolt    │
│             │   MTO JSON               │    -> summary totals        │
│             │                          │    -> in-memory job store   │
│             │  GET /api/mto/{id}/csv   │                            │
│             │ ◀─────────────────────── │  /api/mto/{id}/csv (CSV)  │
└─────────────┘                          │  /api/health               │
                                          └────────────────────────────┘
```

- **Frontend**: Next.js 14, App Router, TypeScript, Tailwind. Single page
  (`app/page.tsx`) with a state machine: `idle → uploading → processing →
  done/error`. Chosen over Pages Router simply because it's the current
  default/recommended Next.js pattern and keeps the client-only upload logic
  in one component (`"use client"`).
- **Backend**: FastAPI, Pydantic v2, the `groq` Python client for the Groq
  vision calls, and PyMuPDF for PDF→image rendering. Clear module boundaries:
  - `app/models.py` – Pydantic schema (MTOItem, DrawingMeta, Summary, Job)
  - `app/mock_data.py` – deterministic mock MTO
  - `app/pipeline.py` – preprocess / extract / validate / derive / summarize
  - `app/storage.py` – in-memory job store
  - `app/main.py` – routes only

### Design trade-off: synchronous processing, job-shaped API

The brief allows a synchronous single-call design. We use the **suggested
job-based contract** (`POST /api/upload` → `{job_id}`, then
`GET /api/mto/{job_id}`) but run the pipeline **synchronously inside**
`POST /api/upload` rather than spinning up a background worker — a single
Groq call takes a few seconds, so a queue wasn't worth the complexity for
this assessment. The job is already `done` by the time `/api/upload`
returns. This keeps the frontend contract stable and forward-compatible: if
extraction moved to a background task (e.g. Celery/RQ or FastAPI
`BackgroundTasks` + polling), only `pipeline.py`/`main.py` would change, not
the frontend.

## 2. Setup (exact steps)

**Requirements**: Python 3.11+, Node.js 18+ (tested on Node 20), npm.

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # leave GROQ_API_KEY blank to run in mock mode
uvicorn app.main:app --reload --port 8000
```

Verify: open `http://localhost:8000/docs` (Swagger) and
`http://localhost:8000/api/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`, upload one of the images in `samples/`, and you
should see the MTO table populate within a few seconds.

### Backend tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

### Docker Compose (bonus, optional)

```bash
GROQ_API_KEY=your_key_here docker compose up --build
```

## 3. Environment variables

**`backend/.env`**
| Variable | Required | Purpose |
|---|---|---|
| `AI_PROVIDER` | No | Forces `groq`, `gemini`, or `mock` explicitly. If unset, Groq is used when `GROQ_API_KEY` is set (this is the provider actually used for this submission), else Gemini when `GEMINI_API_KEY` is set, else mock. |
| `GROQ_API_KEY` | No | Free key from console.groq.com/keys. Fast inference, generous free tier. This is the provider used for this submission. |
| `GROQ_MODEL` | No | Defaults to `meta-llama/llama-4-scout-17b-16e-instruct` (Groq's current vision model with JSON mode support). |
| `GEMINI_API_KEY` | No | Optional alternative provider. Free key from aistudio.google.com. |
| `GEMINI_MODEL` | No | Defaults to `gemini-2.5-flash`. |
| `CORS_ORIGINS` | No | Defaults to `http://localhost:3000`. |

If none of the keys are set (or extraction fails for any reason), the app automatically serves a clearly-labelled mock MTO — nothing crashes.

**`frontend/.env.local`**
| Variable | Required | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Base URL of the FastAPI backend. |

## 4. How the AI pipeline works

1. **Pre-process** (`pipeline.preprocess`): if the upload is a PDF, render
   page 1 to a PNG at 200 DPI with PyMuPDF (multi-page PDFs → first sheet
   only; see limitations). Images pass through unchanged.
2. **Extract** (`pipeline.extract_with_groq`): the PNG is sent to Groq
   (`meta-llama/llama-4-scout-17b-16e-instruct` by default) with JSON mode
   enabled and a **prompt containing the full target JSON schema** and the
   domain rules from the brief (pipe by length, everything else by count,
   bolts by set, derive gaskets/bolts per flanged joint if not drawn, use real
   ASME/ASTM vocabulary). The full prompt lives in `pipeline.py` /
   `EXTRACTION_PROMPT` — it is part of the deliverable, not hidden.
3. **Validate** (`pipeline.extract_with_groq` + `app/models.py`): the JSON
   response is parsed and pushed through Pydantic `MTOItem`/`DrawingMeta`
   models. Any malformed/missing field raises inside a `try/except` in
   `run_pipeline`, which **falls back to the mock MTO** rather than ever
   returning a 500 to the user for an LLM hiccup.
4. **Derive** (`pipeline._derive_joint_consumables`): if Groq didn't
   already emit GASKET/BOLT rows, we add one GASKET row and one BOLT row
   with `quantity = number of flanges detected` — the domain convention from
   Section 2.2 of the brief.
5. **Serve** (`pipeline._compute_summary`): totals (pipe length, counts per
   category) are computed server-side from the validated items, not trusted
   from the LLM, so the summary chips are always internally consistent with
   the table.

### Mock mode (graceful degradation)

If `GROQ_API_KEY` is unset, `run_pipeline` skips the network call entirely
and returns `mock_data.build_mock_mto()` — a hand-built, schema-valid MTO for
a representative 6" line, tagged `"mode": "mock"`. The same tag drives a
visible amber badge in the UI so evaluators always know which mode they're
looking at. This also fires automatically if Groq errors or returns
unparseable JSON, with the reason surfaced in `result.warnings`.

### Accuracy strategy — what to expect

**Will likely work well**: clean, single-sheet, computer-generated isometrics
with a legible title block and line number; straightforward runs with a
handful of elbows/tees/flanges/one valve; standard NPS/schedule/material
callouts written in text.

**Will likely struggle**: dense, multi-spool sheets with overlapping
callouts; hand-drawn or scanned/rotated isometrics with skewed text; drawings
where dimensions are in feet-inches with tick marks rather than metric
labels (the model may misread units); reducers/olets that are visually subtle;
distinguishing SR vs LR elbows purely from a small drawn radius. Per-item
`confidence` scores are the model's own self-assessment (not calibrated
against ground truth) — treat them as a rough triage signal, shown as a
colour-coded badge in the UI, not a guarantee.

**With more time** we would: (a) add a second pass that OCRs the BOM
table/title block separately (Tesseract/PaddleOCR) and reconciles it against
the vision-model output, since real isometrics usually already carry a BOM;
(b) do bounding-box symbol detection and overlay it on the preview image for
auditability; (c) support multi-sheet PDFs by looping the pipeline per page
and merging line numbers; (d) add a real weld/field-weld count; (e) move
extraction to a background task with a proper `queued/processing/done`
status so the UI can show granular progress instead of one spinner.

## 5. Assumptions & known limitations

- One drawing per upload; multi-page PDFs are processed as page 1 only
  (documented, not silently wrong — a warning is not currently emitted for
  this specific case, but could be added trivially).
- Job storage is in-memory (`app/storage.py`); restarting the backend loses
  history. No database is required per the brief.
- `length_m` is only meaningful for `PIPE` rows; a validator on `MTOItem`
  nulls it out for any other category defensively.
- Gasket/bolt derivation counts **flange occurrences only** (not valve
  end-connections) as "flanged joints" — a conservative simplification;
  a more accurate model would also count flanged valve ends and
  flange-to-flange mating pairs distinctly rather than per detected flange
  symbol.
- Confidence scores come straight from the LLM's self-report; no separate
  calibration step.
- CORS defaults to `localhost:3000`; set `CORS_ORIGINS` to your deployed
  frontend URL in production (see Section 6).

## 6. Deployment (Render + Vercel)

This project is deployed live — see **Live Demo** above for links.

**Backend on Render**
1. New → Web Service → connect this repo, root directory `backend/`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add env vars: `GROQ_API_KEY` (optional), `CORS_ORIGINS=https://mto-generator-alpha.vercel.app`.

**Frontend on Vercel**
1. New Project → import this repo, root directory `frontend/`.
2. Add env var: `NEXT_PUBLIC_API_URL=https://mto-generator-jok9.onrender.com`.
3. Deploy.

Note Render's free tier cold-starts after inactivity; the first request
after idling may take ~30–50s — the UI's "processing" spinner covers this
gracefully rather than erroring.

## 7. What's in this ZIP

```
backend/     FastAPI app + tests + Dockerfile
frontend/    Next.js app + Dockerfile
samples/     one small self-generated sample isometric (for testing)
screenshots/ input drawing + output MTO screenshots (referenced in this README)
docker-compose.yml
README.md
```

## Output

**Input** — a hand-marked-up piping isometric (`samples/`):

![Input isometric drawing](https://github.com/manojkothakota/MTO_GENERATOR/blob/55bf77503973d5aa69898c73fde6300cf48a1723/sample/Screenshot%202026-07-08%20120335.png)

**Output** — the extracted Material Take-Off, live on the deployed app:

![Live app — MTO output](https://github.com/manojkothakota/MTO_GENERATOR/blob/55bf77503973d5aa69898c73fde6300cf48a1723/sample/Screenshot%202026-07-07%20232655.png)

**Output** — Material Take-Off table detail, with per-item confidence scores and CSV export:

![MTO table detail](https://github.com/manojkothakota/MTO_GENERATOR/blob/55bf77503973d5aa69898c73fde6300cf48a1723/sample/Screenshot%202026-07-07%20232735%20-%20Copy.png)
