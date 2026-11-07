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

**Apply migration `007_importer_pipeline.sql`** (SQL editor, or `supabase db push`). It is additive only: it adds columns and one table (`answer_key_entries`) and a few admin-only functions, widens one CHECK constraint, and deletes nothing. Until it is applied, the Admin page shows a banner and the importer cannot run. It also re-queues the four answer-key documents the old importer had marked `skipped`.

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

`python-importer/` runs in GitHub Actions: weekly (Monday 03:00 UTC), every 6 hours **only if an admin queued a run** in the Admin page, and on demand (*Actions > Import PYQs > Run workflow*, with mode, depth, page and download limits).

### What it does

1. **Discover.** Starting from `jeemain.nta.nic.in`, `www.nta.ac.in` (JEE links only) and `jeeadv.ac.in`, it follows archive-like links (archive, previous year, question paper, answer key, year/session/shift words) up to `--max-depth` (default 3) and `--max-pages` per site (default 60), and records every PDF it sees. It stays on those hosts. For each PDF it keeps the **page it was found on and the PDF URL**, and reads the year, session, shift, paper number, exam date and key version (provisional/final) from the file name, link text, the table row or heading next to the link, and finally the PDF's own first page. A field that cannot be read stays empty and the evidence is stored with the document. Two different years in one name are reported, not guessed.
2. **Classify the link.** Question papers, answer keys, solutions and everything else (bulletins, notices, results, admit cards, counselling, memory-based papers, B.Arch/B.Planning papers) are told apart. Solutions and non-papers are recorded as `skipped` with the reason.
3. **Download** with SHA-256 duplicate detection. An identical file under another URL is `skipped` as a duplicate.
4. **Extract.** PyMuPDF reads positioned text lines; scanned pages are OCR'd with Tesseract. Running headers, footers and page numbers are dropped, Hindi lines are dropped, superscripts and subscripts become `$x^{2}$`, `$H_{2}$`. A dynamic-programming splitter picks question starts, so `2. 5 m/s`, a wrapped `3) x + y = 0`, a decimal such as `2.5 m`, or a numbered instruction list does not split a question. Questions can span pages. Section instructions decide single-correct, multiple-correct, integer or numerical; List-I/List-II becomes matrix-match; paragraphs are attached to their questions. Missing question numbers are reported, never invented. Embedded images and vector diagrams are cropped into `question-images`; questions that are OCR'd, maths-heavy or mention a figure also get a page snapshot for you to compare against.
5. **Classify.** If an AI provider is configured, each question gets a chapter and difficulty (the AI only sees the subject printed in the paper). Without one, questions are still stored, with the subject from the paper's headings and a blank chapter.
6. **Parse answer keys** into `answer_key_entries` (one row per answer: raw text, normalised answer, subject section, page). Single, multiple, numerical, ranges (`12.3-12.5`), dropped/bonus, row-wise tables and id-based keys are recognised. Conflicting duplicates inside a key are left unresolved.
7. **Match keys to papers and questions** by year, session, shift, paper number and exam date, then by subject and question number. An entry becomes **proposed** only if exactly one paper and one question fit and the answer fits the question's type. Anything else is **ambiguous** or **unmatched**, with the reason. Provisional and final keys that disagree are both marked ambiguous. **The importer never writes an answer onto a question**; you confirm it in Admin.

It never invents papers, questions, answers or statistics. It obeys `robots.txt` (including Crawl-delay), waits at least 3 s between requests to one host, and never bypasses a CAPTCHA, login or bot challenge: such pages, HTTP 403/429 responses and refused downloads are logged with a reason, and a host that refuses 3 times is dropped for the run. **Do not assume every historical paper is available.** Several official pages block automated access or only host recent years; for those, download the PDF yourself and use **Manual upload**.

### Statuses

Every source document has exactly one status, with its reason shown in Admin:

| Status | Meaning |
|---|---|
| `discovered` | Found on an official page; not downloaded yet |
| `downloaded` | PDF stored; not read yet |
| `extracted` | Question paper: questions stored. Answer key: entries stored |
| `classified` | Chapter and difficulty assigned by the AI |
| `awaiting_review` | Waiting for you (Question review / Answer keys) |
| `completed` | Paper published, or every key entry confirmed/rejected. Only a person gets a document here |
| `skipped` | Deliberately not imported (solutions, notices, duplicates, out-of-scope papers) |
| `failed` | Something went wrong (download blocked, not a PDF, no text, missing year, no questions found). Fix and retry |

A key being processed never advances a question paper's status, and the run summary counts them separately: PDFs discovered, question papers downloaded, answer keys downloaded, questions extracted, questions classified, questions requiring review, documents skipped, documents failed, plus answer-key entries proposed / ambiguous / unmatched. Each run also reports an **outcome**. If none of the official sites could be read, the outcome is `sources_unreachable` and the workflow **fails** (exit code 3), so an import that did nothing is never shown as green.

### Admin page

Overview (counts by status, run history with the counters above, queue / pause / retry), Documents (filters, reasons, how each document was identified, edit metadata, retry, links to the source page, the PDF and the stored copy), Papers and publishing, Question review (statement, options, figures and page snapshots, the matched official answer, edit text, classification, manual answer with a stated source, bulk actions), Answer keys (confirm, reject, choose the question for an ambiguous entry), Import logs (filter by level, run, document, text) and Manual upload (PDF, exam, kind, year, session, shift, paper, date).

**Publishing is per paper.** *Publish* releases only questions that are answer-verified **and** reviewed; the rest stay hidden. *Verify safe matches* confirms every proposed answer in a paper, and marks a question reviewed only if it has a chapter, a confident classification (>= 75%), no OCR and no extraction warnings. Unpublishing hides the paper's questions from students, including in their old results.

`shift` holds `1` or `2`. For JEE Main 2019-2022, where several days share shift numbers, it holds `YYYY-MM-DD S1` so papers stay distinct.

### Run it locally

```bash
cp .env.example python-importer/.env        # fill in the Supabase values
cd python-importer && pip install -r requirements.txt      # needs tesseract-ocr for scanned PDFs
python main.py --print-only                  # crawl and print what would be found. No database, no downloads
python main.py --mode discover_only          # register PDFs only
python main.py --mode process_only           # read stored / uploaded PDFs
python main.py --only-if-queued              # exit unless Admin queued a run
```
or `docker compose run importer`.

## Development
```bash
npm test          # marking, scheme and timing logic
npm run check     # syntax check
npm run serve     # http://localhost:8080
cd python-importer && python -m pytest -q tests     # discovery, extraction, answer keys, matching, duplicates, pipeline, failure handling
```

## Known limitations
- Answers are stored in the same row students can read, so a determined student could read answers before submitting. Acceptable for a private study tool; a public launch should move marking to the server.
- Partial marking for multiple-correct questions is not applied; they are scored all-or-nothing.
- "Check sources" and "Start import" queue a run; Actions executes it (next schedule, or start the workflow by hand). The browser cannot run Python.
- Official sites change often and many historical papers are not publicly downloadable. Discovery is generic (archive-like links, depth-limited) and has been tested against fixtures, not against the live sites, some of which refuse automated access. Expect to supply some PDFs by Manual upload.
- PDF text from mathematical content is only as good as the PDF. Simple exponents and subscripts are converted; fractions, integrals and matrices stay as extracted text, so compare maths-heavy questions with the page snapshot before verifying.
- Id-based answer keys (long official question and option ids instead of A/B/C/D) are stored but cannot be matched automatically.
- Formula-recall, calculation and interpretation mistakes can't be separated from results alone; the weak-topic page reports conceptual (low accuracy), time-management and inconsistency patterns, with evidence, and says so.

## Troubleshooting
- **Blank page / 404 on refresh:** use the hash URLs; open the repository's Pages URL, not a deep path.
- **"Registration closed":** an admin already exists; ask for an invite.
- **Email links go to localhost:** fix the Site URL in Supabase Auth settings.
- **Importer says AI provider not configured:** set the secret and variable above, then retry failed documents in Admin.
- **Admin shows a red banner saying migration 007 is not applied:** run `supabase/migrations/007_importer_pipeline.sql`.
- **Run outcome `sources_unreachable`:** the official sites refused or could not be reached from GitHub's servers (Import logs give the reason per page). Use Manual upload.
- **A document is `failed` with `missing_year`:** open Documents, Edit, enter the year printed on the paper, and save with *re-run* ticked.
- **Queued runs never start:** the 6-hourly workflow must be enabled (GitHub disables scheduled workflows after 60 days without repository activity), or start *Import PYQs* by hand.
- **Coach error:** deploy the function and set an AI secret.
