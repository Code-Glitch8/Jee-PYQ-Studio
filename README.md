# JEE PYQ Studio

A JEE Main and JEE Advanced previous-year-question practice platform that runs entirely on GitHub and Supabase.

- **Site:** static HTML, CSS and JavaScript on **GitHub Pages**. No server, no build step, no Node in production.
- **Data and login:** **Supabase** (PostgreSQL, Auth, Storage, Row Level Security).
- **Background work:** Python scripts run by **GitHub Actions** (PDF discovery, text extraction, OCR, AI classification).
- **AI Study Coach:** a **Supabase Edge Function**, so the AI key never reaches the browser.

There is no Vercel, Netlify or other hosting dependency.

## Architecture

```
Browser (GitHub Pages)  --anon/publishable key + user JWT-->  Supabase (Postgres + RLS, Auth, Storage)
                                                                  ^                       ^
GitHub Actions (cron) -- service-role key from GitHub Secrets ----+                       |
   python-importer: discover PDFs > download > OCR/extract > AI classify > unverified rows |
Browser --> Edge Function ai-coach (AI key stored as a Supabase secret) ------------------+
```

Routing uses the URL hash (`#/dashboard`, `#/test/<id>`), so every route works on GitHub Pages and refreshing never 404s. All asset paths are relative, so the site works under `https://<user>.github.io/<repo>/` with no base-path setting.

## Features

Login, registration and password reset; question bank with filters; papers list; custom test generator (exam, subject, chapter, topic, year, type, attempt history, custom difficulty split, availability check, never pads with fake questions); automatic duration from editable per-difficulty minutes; CBT-style exam screen (palette, review marks, clear, pause, autosave every 10 s, refresh recovery); per-question active time and visits; results with subject, chapter and topic tables, fastest and slowest question; solutions labelled by origin; statistics shown only when sourced (otherwise "Historical response statistics unavailable."); analytics charts; evidence-based weak-topic detection; AI Study Coach; test history with reattempt and "incorrect questions only"; admin area with access mode, invites, import controls and answer verification.

## Setup

### 1. Supabase
The database for this project already exists with the schema, RLS policies, syllabus seed (2 exams, 3 subjects, 58 chapters, 174 topics) and marking schemes. To reproduce it elsewhere, export it from the linked project:

```bash
npm i -g supabase
supabase login
supabase link --project-ref tcekqkeetfaefrbnijej
supabase db pull          # writes supabase/migrations/*.sql, commit them
```

In **Authentication > URL Configuration**, set the Site URL to your GitHub Pages address and add it to the redirect URLs (needed for email confirmation and password reset).

**The first account to register becomes the administrator.** After that, registration is closed unless the admin invites an email or switches to public registration (Admin page).

### 2. GitHub
1. Create a repository and push this folder.
2. **Settings > Pages > Source: GitHub Actions.**
3. Push to `main`. The *Deploy to GitHub Pages* workflow publishes the site.
4. `js/config.js` holds the Supabase URL and **publishable** key. These are meant to be public; RLS protects the data. Never put the service-role key or an AI key in any file under `js/`. CI fails if it finds one.

### 3. GitHub Secrets for the importer
*Settings > Secrets and variables > Actions*

| Name | Type | Purpose |
|---|---|---|
| `SUPABASE_URL` | secret | project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | secret | server-side writes (Supabase > Settings > API keys) |
| `AI_PROVIDER` | variable | `gemini`, `openrouter` or `openai_compatible` |
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_COMPAT_API_KEY` | secret | whichever provider you use |
| `OPENROUTER_MODEL`, `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_MODEL` | variable | provider details |

### 4. AI Study Coach
```bash
supabase functions deploy ai-coach --project-ref tcekqkeetfaefrbnijej
supabase secrets set GEMINI_API_KEY=... --project-ref tcekqkeetfaefrbnijej
```
Choose the provider in Settings. Without a key the Coach page shows the error instead of pretending to work.

## The importer

`python-importer/` runs weekly and on demand (*Actions > Import PYQs > Run workflow*). It:
1. Honours the pause switch in Admin.
2. Reads the official pages (jeemain.nta.nic.in, nta.ac.in, jeeadv.ac.in), obeying `robots.txt`, waiting 3 s between requests.
3. Skips any page that looks like a CAPTCHA, block or login wall. It never tries to get around one.
4. Downloads PDFs, hashes them to skip duplicates, and stores them in the private `source-documents` bucket with provenance.
5. Extracts text with PyMuPDF (OCR for scanned pages), splits questions, and classifies them with your AI provider.
6. Inserts questions as **unverified, unpublished, estimated difficulty**. An admin reviews each one, enters the answer from the official key, and publishes.

It does not invent papers, answers or statistics. If the AI key is missing, the exam year can't be read, or a PDF has no text, the job is marked failed or skipped with the reason, visible in Admin.

Manual fallback: upload a PDF to the `source-documents` bucket and add a `source_documents` row with `origin = 'manual_upload'`; the next run processes it.

Local run: copy `.env.example` to `python-importer/.env`, then `cd python-importer && pip install -r requirements.txt && python main.py` (needs `tesseract-ocr` for OCR), or `docker compose run importer`.

## Development
```bash
npm test          # marking, scheme and timing logic
npm run check     # syntax check
npm run serve     # http://localhost:8080
cd python-importer && python -m pytest -q tests
```

## Known limitations
- Answers are stored in the same row students can read, so a determined student could read answers before submitting. Acceptable for a private study tool; a public launch should move marking to the server.
- Partial marking for multiple-correct questions is not applied; they are scored all-or-nothing.
- "Check sources" and "Start import" queue a run; Actions executes it (next schedule, or start the workflow by hand). The browser cannot run Python.
- Official sites change often and many historical papers are not publicly downloadable. The link finder is deliberately simple; expect to supply some PDFs manually.
- Formula-recall, calculation and interpretation mistakes can't be separated from results alone; the weak-topic page reports conceptual (low accuracy), time-management and inconsistency patterns, with evidence, and says so.
- Chapter and difficulty corrections are done in the Supabase table editor for now.

## Troubleshooting
- **Blank page / 404 on refresh:** use the hash URLs; open the repository's Pages URL, not a deep path.
- **"Registration closed":** an admin already exists; ask for an invite.
- **Email links go to localhost:** fix the Site URL in Supabase Auth settings.
- **Importer says AI provider not configured:** set the secret and variable above, then retry failed documents in Admin.
- **Coach error:** deploy the function and set an AI secret.
