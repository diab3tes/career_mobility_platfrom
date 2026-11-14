# Career Mobility Platform: MVP prototype

A working prototype of one journey: a user creates a career profile (typed in, or pre-filled from an
uploaded CV), the system scores 12 fictional opportunities against it, and the user sees ranked
recommendations with reasons, opens a detail view, and shortlists opportunities.

All organisations, opportunities and sample people are fictional. Do not enter real personal data.

## Setup

Requires Python 3.10 (built and tested on 3.10). Commands run from the project folder.

```bash
python -m venv .venv
```

Activate it (Windows: `.venv\Scripts\activate`; macOS/Linux: `source .venv/bin/activate`), then:

```bash
pip install -r requirements-dev.txt
```

(`requirements.txt` holds only the runtime packages, which is what Vercel installs; `requirements-dev.txt`
adds pytest and the optional watsonx provider.)

```bash
python manage.py migrate
```

```bash
python manage.py seed_opportunities
```

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000/ and press **Load sample profile**, then **Save profile**.

No configuration is needed for a local run: without a `.env` file the app uses SQLite and **Mock AI**.
To enable **Live AI**, copy `.env.example` to `.env`, paste a free Groq key after `GROQ_API_KEY=`
(the model is already filled in; see [AI](#ai)), then restart the server.

### Tests

```bash
pytest
```

187 tests, about 2 seconds. No test calls a real AI provider: models are replaced by fakes. A fixture
isolates the suite from your `.env`: provider keys are blanked, and tuning values and match weights are
reset to the code defaults, so local settings cannot change test results.

## Architecture

```
Browser
  Django templates: layout, profile form, CV upload, opportunity list, shortlist
  React island (CDN + in-browser Babel): matches and shortlist (cards, detail panel, AI assessment, save)
        |  fetch (JSON, CSRF token)
Django
  profiles       Profile model, form + validation, CV upload view, sample profile
  opportunities  Opportunity model, seed loader, list page, recommendation/detail JSON
  matching       pure-Python rule engine (no Django imports; Pydantic in and out)
  ai             mode toggle, LLM client, CV extractor, match agent, mock provider, cache
  shortlist      save / remove
        |
  SQLite (default)                   Groq · Cloudflare Workers AI · IBM watsonx.ai (Live mode only)
```

- **No login.** The profile belongs to the anonymous Django session: its id is stored in the server-side
  session, never taken from a URL or form, so one visitor cannot see or change another's data (see
  [Privacy in this prototype](#privacy-in-this-prototype)).
- **Configuration** comes from environment variables; see [Configuration](#configuration).
- **Interface:** light and dark themes (sun/moon switch in the header; follows the system setting until
  you choose, then remembers it), score rings, a collapsible score breakdown, hover tilt on cards and
  ambient glows. All motion is switched off when the system asks for reduced motion. Fonts (Space
  Grotesk, JetBrains Mono) load from Google Fonts.
- **React** 18.3.1 and Babel standalone 7.26.4 are pinned and loaded from a CDN; JSX is compiled in the
  browser (`<script type="text/babel">`). This is a prototype choice to avoid a Node build step; a
  production build would use a bundler. Initial data is passed with Django's `json_script`.
- **Django** 5.2 LTS (Django 6 needs Python 3.12; this was built on 3.10).

### Configuration

Everything deployment-specific or tunable is read from environment variables (or `.env`); see
`.env.example` for the full list with defaults. Values are range-checked at startup, so a bad value stops
the app with a message naming the variable (for example `AI_CALL_TIMEOUT_SECONDS must be at least 5`).

"Default" is what the code uses when a variable is unset or blank; "`.env.example`" is the value the
example file ships with, where it differs.

| Variable | Default | `.env.example` | Meaning |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | dev-only key when `DEBUG` is on | `change-me` | Required when `DEBUG` is off |
| `DEBUG` | true | | |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | | |
| `CSRF_TRUSTED_ORIGINS` | none | | Comma-separated `https://` origins; Vercel's own URLs are added automatically |
| `DATABASE_URL` | SQLite file in the project | | Any `dj-database-url` URL, e.g. Neon Postgres (`sslmode=require` is added if missing). The test suite always uses its own SQLite database |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | true, 3600 | | Only when `DEBUG` is off (HTTPS redirect, HSTS, secure cookies are then on) |
| `AI_PROVIDER` | `groq` | | `groq`, `cloudflare` or `watsonx` |
| Provider keys and model | none | models pre-filled | See [Provider](#provider); the model is required |
| `GROQ_REASONING_EFFORT` | blank (not sent) | `low` | Reasoning models only: `low`, `medium`, `high` |
| `AI_LIVE_CALLS_PER_SESSION` | 25 | 15 | Live calls per browser session; saved and cached answers are free |
| `AI_CALL_TIMEOUT_SECONDS` | 45 | | Hard limit for one call or one whole agent run (5–300) |
| `AI_AGENT_MAX_MODEL_CALLS` | 6 | | Model calls per assessment (2–20) |
| `AI_AGENT_RECURSION_LIMIT` | 24 | | Agent graph steps (4–100) |
| `CV_MAX_UPLOAD_MB` | 10 | 3 | Largest accepted PDF (1–50) |
| `CV_MIN_WORDS_PER_PAGE` | 50 | | Below this the PDF is treated as scanned; no model call (0–1000) |
| `CV_MAX_CHARS_SENT` | 15000 | | CV text beyond this is not sent to the model (1000–200000) |
| `MATCH_WEIGHT_SKILLS`, `_EXPERIENCE`, `_LANGUAGE`, `_LOCATION`, `_EDUCATION`, `_INTERESTS` | 35, 20, 15, 15, 10, 5 | | 0–100 each; 0 switches a rule off |
| `MATCH_EXPERIENCE_UNRELATED` | 0.25 | | Share of the years score kept when experience areas don't overlap (0–1) |
| `MATCH_EXPERIENCE_UNKNOWN` | 0.6 | | Share kept when the profile lists no experience areas (0–1) |
| `DATA_RETENTION_DAYS` | 30 | | `purge_expired_data` deletes data not used for this many days (1–3650) |

Deliberately not configurable: the prompt version, which is a fingerprint computed from the prompt text,
tool descriptions and output schema (it changes exactly when they do, so cached answers from an older prompt
are never reused); and interface wording.

### Pages and endpoints

| Route | Purpose |
|---|---|
| `/` | Profile form: manual entry, CV upload, "Load sample profile" |
| `/opportunities/` | All opportunities, filter by country and type |
| `/recommendations/` | Ranked cards with score rings, detail panel (collapsible score breakdown, full requirements), AI assessment, save |
| `/shortlist/` | Saved roles as the same cards and details panel as the matches page (overall rank, saved date, Remove with Undo); a server-rendered list without JavaScript |
| `GET /api/recommendations/` | Ranked rule-based results for the session profile; `?only=shortlisted` returns just the saved roles with their save times |
| `GET /api/opportunities/<id>/` | Details plus match breakdown |
| `POST /api/opportunities/<id>/ai-assessment/` | AI second opinion for one opportunity: returns the saved one, or runs and saves it; body `{"refresh": true}` runs it again |
| `POST` / `DELETE /api/shortlist/<id>/` | Save / remove (both idempotent) |
| `POST /api/ai-mode/` | Set the Live / Mock toggle |
| `POST /profile/cv/` | CV upload → pre-filled form (nothing saved until the user submits); Live mode requires consent |
| `POST /profile/delete/` | Delete my data: profile, shortlist, saved AI assessments and AI cache rows made from the profile |

## Data structures

Django models store data; Django forms validate user input; Pydantic validates the seed file, the
matching engine's inputs and outputs, and every LLM output. Lists are JSON fields.

**Profile**: `education_level` (secondary, diploma, bachelor, master, doctorate), `education_field`,
`years_experience` (0–50), `experience_areas[]`, `skills[]` (at least one), `languages[]`
(`{language, level}`, level basic/conversational/professional/native), `preferred_countries[]`,
`career_interests[]`, `currently_enrolled_student` (yes/no/unknown, default unknown),
`work_authorisation[]` + `work_authorisation_status` (specified/unknown, default unknown).

**Opportunity**: `title`, `organisation`, `country`, `city`, `type` (job/internship), `description`,
`required_skills[]`, `nice_to_have_skills[]`, `min_years_experience`, `max_years_experience` (nullable),
`experience_areas[]` (the kinds of work the experience should be in),
`education_level_required` (nullable), `education_fields[]`, `language_requirements[]`
(`{language, level, mandatory}`), `local_work_auth_required`, `must_be_enrolled_student`,
`visa_sponsorship` (yes/no/unstated), `interest_tags[]`. Seeded from
`opportunities/data/opportunities.json` (validated by `opportunities/schemas.py`).

**ShortlistItem**: profile, opportunity, created time; unique per pair.
**Profile** also has `last_active_at` (refreshed at most hourly as the visitor uses the site), which the
retention purge measures from.

**AIAssessmentCache**: SHA-256 key of (profile content, opportunity content, provider + model, prompt version),
plus `profile_hash` (a fingerprint of the profile content alone, so deleting a profile also removes the
cached answers made from it)
→ stored result. Shared across users; it only prevents paying twice for an identical request.

**UserAIAssessment** (table `user_ai_assessment`): `user_id` (the visitor's Profile; the app has no accounts,
so the session Profile is the user), `opportunity_id`, `assessment_data` (JSON: source, notice, model,
fit, summary, strengths, gaps, considerations), `is_active`, `created_at`, `updated_at`. It is what makes an
assessment survive a page reload. A partial unique index allows one active row per user and opportunity;
"Run again" deactivates the old row and adds a new one (history kept). Editing the profile deactivates that
user's rows, because they described the old profile. The rule engine's current label is attached when a
saved assessment is shown.

Engine types (`matching/schemas.py`): `ProfileData`, `OpportunityData` →
`MatchResult {score, uncapped_score, eligibility, eligibility_notes, criteria[CriterionResult]}`,
with `CriterionResult {name, score 0–1, status, weight, effective_weight, reason}`.

## Matching

### How the rule score and the AI work together

Every opportunity gets a **rule-based score from 0 to 100, and the list is ordered by that number
only.** The AI assessment is shown beside it as a second opinion (fit label, summary, strengths, gaps,
considerations). The AI never changes the score, the order or the eligibility label. Reasons: the
rules are repeatable and every point can be traced to a criterion; the ranking still works in Mock
mode or when the AI is down; and a model mistake cannot push a role with an eligibility problem to the
top. When the two disagree, both are shown and the page says so.

### Rule-based score (`matching/criteria.py`, `matching/engine.py`)

The weights below are the defaults; each can be changed with a `MATCH_WEIGHT_*` variable (0 switches a
rule off). The same weights and inputs always give the same scores.

| Criterion | Weight | Scoring |
|---|---|---|
| Skills | 35 | Share of required skills matched after normalisation (lowercase, trimmed, small synonym map, e.g. "MS Excel" = "Excel"). Matched nice-to-have skills add up to 0.1, capped at 1. |
| Experience | 20 | **Years score × relevance.** Years: 1.0 within range; 0.6 if within one year below the minimum; 0.2 if further below; 0.7 if above the maximum (may be overqualified). Relevance: 1.0 if the profile's experience areas overlap the role's; 0.25 if they don't; 0.6 if the profile lists none (with a prompt to add them); 1.0 if the role lists none. |
| Language | 15 | Per required language: 1.0 met, 0.5 one level short, 0 otherwise or absent. Averaged. |
| Location | 15 | 1.0 if the country is a preferred country, else 0. |
| Education | 10 | Level met: 0.6, plus 0.4 if the field is relevant or no field is specified. Level not met: 0.2 if one level short, else 0. |
| Interests | 5 | Share of the opportunity's interest tags found in the user's career interests. |

**Why experience is weighted by relevance.** Years alone over-reward unrelated work: a business graduate
with 3 years in operations used to get the full 20 points for a software role asking for 2–6 years.
Relevance compares the profile's experience areas with the opportunity's (same phrase, one inside the
other, or a shared meaningful word, so "business operations" matches "operations" but "project support"
does not match "customer support"). Unrelated years still count a little (0.25), because general work
experience has some value. The reason shown in the detail panel says which case applied, for example
"But your experience (Business operations, Project support) is unrelated to this role (software
development, software engineering), so it counts at 25%."

Rules on top of the weights:

1. **Requirement absent on the opportunity** → `not_applicable`; the criterion is dropped and the
   remaining weights are rescaled to 100 (the detail panel shows nominal and rescaled weight).
2. **Data absent on the profile** → `unknown`, score 0, with a reason such as "Add your languages to
   assess this". Unknown is never shown as "not met".
3. **Eligibility is a separate label, never part of the score:**
   - `no_stated_constraint`
   - `requires_verification`: the opportunity states a constraint the profile does not answer (local
     work authorisation required and status unknown; enrolled student required and enrolment unknown;
     a mandatory language when no languages are listed; a mandatory language one level short).
   - `blocker`: a stated hard requirement is clearly not met (mandatory language absent or two or
     more levels short; enrolled student required and the user said no; local work authorisation
     required and the user listed countries that exclude this one).
4. **Blocker cap:** a `blocker` caps the final score at 40 (the raw score is still shown).
5. Final score is rounded half-up to a whole number. Ties: eligibility label (no constraint, then
   requires verification, then blocker), then title.

Wording never states or implies that the user is legally eligible or ineligible to work anywhere;
notes use "requires verification" and "you stated…". Unknown work authorisation is never treated as
satisfied. Visa sponsorship is displayed but does not affect the label (the brief does not list it as
a constraint).

The explanation (`matching/explain.py`) is built only from criterion results: top strengths (met,
by weight), gaps (partial / not met), unknowns, and the eligibility notes.

### Sample profile outcome

With the sample candidate in `profiles/sample.py` (Bachelor's in Business Administration, 3 years of
experience) and the default weights:

| Opportunity | Score | Label |
|---|---|---|
| Operations Coordinator (SG), Programme Assistant (DE), Project Support Officer (CA) | 100 | No stated constraint |
| Business Analyst Intern (SG) | 96 | Requires verification (enrolled student, local work authorisation) |
| Operations Associate (DE) 93 · Business Analyst (CA) 89 · Programme Officer (KE) 85 · Project Coordinator (NL) 77 · Research Assistant (SG) 72 | | No stated constraint |
| Software Engineer (CA) | 41 | No stated constraint |
| German-speaking Client Associate (DE) | 40 (raw 73) | Stated requirement not met (mandatory German) |
| Senior Finance Manager (UAE) | 18 | No stated constraint |

Research Assistant, Software Engineer, the German-speaking role and Senior Finance Manager score lower
than years alone would give, because the sample's experience areas (business operations, project support)
are unrelated to them. The brief's sample candidate has 2 years of experience; with 2, Project Coordinator
(4+ years required) scores 69 instead of 77 and everything else is unchanged.

## AI

Two optional features, both behind a **Live AI / Mock AI** toggle in the header (stored in the
session). Mock is the default, and the toggle is locked to Mock until the chosen provider's keys are
set. Every AI response carries `source: live | mock | fallback` and the UI labels it, including the
provider and model for live output.

### Provider

Choose one with `AI_PROVIDER`; only the model factory in `ai/client.py` differs between them. Prompts,
the agent, validation, retry, cache, session limit and mock mode are shared.

| `AI_PROVIDER` | Required settings | Suggested model (pre-filled in `.env.example`) | Notes |
|---|---|---|---|
| `groq` (default) | `GROQ_API_KEY`, `GROQ_MODEL` | `openai/gpt-oss-20b` with `GROQ_REASONING_EFFORT=low` | 20B, tool calling, fast; free key at console.groq.com. For `llama-3.1-8b-instant`, leave `GROQ_REASONING_EFFORT` blank. Groq organisations can restrict models. LangChain `ChatGroq`. |
| `cloudflare` | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_MODEL` | `@cf/ibm-granite/granite-4.0-h-micro` | Keeps IBM Granite (3B, function calling per Cloudflare). Smaller model, so expect more fallbacks. LangChain `ChatCloudflareWorkersAI`. |
| `watsonx` | `WATSONX_APIKEY`, `WATSONX_URL`, `WATSONX_PROJECT_ID`, `WATSONX_MODEL_ID` | `ibm/granite-4-h-small` | The original plan; IBM withdrew Granite 3.x on watsonx.ai on 22 Feb 2026. LangChain `ChatWatsonx`. |

There is no model name in code: the model is a required setting like the key, and the "Locked to Mock"
hint names whatever is missing (for example `GROQ_MODEL`).

Measured on Groq's free tier with `openai/gpt-oss-20b`: CV extraction about 1.2 s; one match assessment
about 2–3 s and about 3,200 tokens. The free tier allowed 8,000 tokens per minute for this model on the test
account, so roughly two fresh assessments per minute: "Assess all" pauses between live calls, the Groq client
retries 429s after the provider's suggested wait, and cached assessments use no tokens. Groq organisations
can restrict models; the test key had no access to the Llama models, which is why the default is gpt-oss-20b.

Why 8B–20B rather than 70B: the tasks are short extraction and a three-tool assessment with a strict
schema; a 20B model handles them, uses less of a free quota, and responds faster.

### What the model does

1. **CV → pre-filled profile** (`ai/cv_extractor.py`, a fixed pipeline, not an agent): validate the
   upload (PDF, at most `CV_MAX_UPLOAD_MB`, `%PDF-` signature), extract text with `pypdf`, reject PDFs
   with fewer than `CV_MIN_WORDS_PER_PAGE` words per page *before* any model call (scanned/image-only
   PDFs are out of scope), then one
   structured-output call returning `ExtractedProfile`. The user reviews the pre-filled form (AI-filled
   fields and empty fields are marked) and nothing is saved until they submit.
2. **Match assessment** (`ai/match_agent.py`): a LangChain `create_agent` agent with three tools,
   `get_profile()`, `get_opportunity(id)`, `get_rule_based_result(id)`, bound to one profile and one
   opportunity. It returns `AIAssessment {fit, summary, strengths, gaps, considerations}` as a
   qualitative second opinion that can notice things rules miss (e.g. related experience in other
   words). Temperature 0.1, at most `AI_AGENT_MAX_MODEL_CALLS` model calls and
   `AI_AGENT_RECURSION_LIMIT` graph steps. Available per card, in the detail panel, and as "Assess all"
   (sequential, with progress and Stop). Each result is saved in `user_ai_assessment`, so it is still
   there after a page reload; "Run again" replaces it and keeps the old one as history.

Prompts are in `ai/prompts.py`.

### What data is sent to it

- **CV extraction:** the extracted CV text (the first `CV_MAX_CHARS_SENT` characters, default 15,000),
  delimited and labelled as data, **with email addresses, phone numbers and links replaced by
  placeholders first** (`ai/redact.py`; date ranges, scores and amounts are kept). The pre-filled form
  says what was removed. Names and postal addresses are not reliably detectable and are not removed.
- **Consent:** in Live mode the upload form has a required "I agree that the text of my CV is sent to
  <provider> (<model>)…" checkbox. The server checks it before reading the file, so without it nothing
  is processed or sent. Mock mode sends nothing, so it asks for no consent.
  The file itself is processed in memory and never stored.
- **Match assessment:** the profile *without* its work authorisation and enrolment fields; the
  opportunity *without* its local work authorisation, enrolment and visa fields; and the rule-based
  score with each criterion's status and reason. Eligibility labels and notes are not sent: the rule
  engine owns eligibility and the UI shows its label next to every AI answer.
- Nothing is sent in Mock mode. The upload screen states which mode is on and that in Live mode the CV
  text goes to the configured provider (named on the screen).

### How unreliable output is handled

- Every output is validated against a Pydantic schema (types, enums, ranges, list lengths).
  Work authorisation and enrolment do not exist in `ExtractedProfile`, so a model cannot fill them.
- The assessment prompt tells the model not to discuss work authorisation, visas, enrolment or legal
  eligibility at all, and every answer is also checked for such statements; a sentence about them that
  does not defer to verification is rejected.
- Invalid output gets **one retry** that includes the validation errors.
- After a second failure: the CV path opens the manual form with a clear message; the assessment path
  returns the deterministic mock assessment labelled `fallback`.
- The AI never changes the score, the ranking or the eligibility label, and the UI always shows the
  rule engine's label next to AI text.

### What happens when the service is unavailable

- Every live call has a timeout (`AI_CALL_TIMEOUT_SECONDS`, default 45). Timeout, network, authentication,
  quota and rate-limit errors are caught; the Groq client retries 429s after the provider's suggested wait.
- **Assessment:** returns the mock assessment with `source: fallback` and a visible notice.
- **CV upload:** opens the manual form with a message (see *Deviations* for why it does not
  fall back to the sample profile).
- The rule-based ranking is never affected; it does not use the AI.
- Cost control for a public demo on a token-capped plan: saved assessments (`user_ai_assessment`) and
  cache hits (`AIAssessmentCache`) use no tokens, and each session may make at most
  `AI_LIVE_CALLS_PER_SESSION` live calls (default 25), after which assessments fall back to mock.

### Mock mode

Mock CV extraction returns the brief's sample profile; mock assessment is generated deterministically
from the rule-based result (strong ≥ 75, moderate ≥ 50, else weak; a blocker is always weak). Both are
labelled "Mock AI output".

## Privacy in this prototype

| Concern | What the app does |
|---|---|
| Consent | Live CV uploads need an explicit, server-checked agreement naming the provider and model |
| Data minimisation | Contact details are removed from CV text before sending; work authorisation and enrolment are never extracted or sent; CV text is capped; the PDF is processed in memory and never stored |
| Deletion | **Delete my data** on the profile page removes the profile, shortlist, saved AI assessments and AI cache rows made from that profile, and starts a fresh session |
| Retention | `python manage.py purge_expired_data` (run it daily; `--dry-run` shows what it would delete) removes profiles not visited for `DATA_RETENTION_DAYS` days with everything linked to them, superseded AI assessments and AI cache rows older than that, and expired sessions |
| Transparency | The upload card names the provider and model in Live mode; every AI answer is labelled live, mock or fallback |
| Separation between visitors | Every view finds the visitor's profile only through the server-side session (database-backed; the browser holds just a random, HttpOnly, SameSite=Lax session key). The only id in URLs is the opportunity id, and opportunities are public. Shortlist items and saved AI assessments are always filtered by the session's profile, and every change needs a CSRF token. `tests/test_isolation.py` has a second visitor call every page and endpoint and checks they can neither see nor change the first visitor's data, and that a `profile_id` in the URL is ignored |
| Logging | No CV text or profile data is logged; only the error message when the AI falls back |

## Deploying to Vercel (free plan) with Neon Postgres

Vercel runs Django as one serverless Python function: `api/index.py` exposes the WSGI app, `vercel.json`
sends every path to it, and WhiteNoise serves `/static/` from inside the function. Vercel's disk is
read-only and not kept between requests, so the database must be external (Neon); the app refuses to
start on Vercel with SQLite.

1. **Neon:** create a project and copy the **pooled** connection string (host contains `-pooler`).
2. **Create the tables and the catalogue once**, from your machine, with that string in `.env` as
   `DATABASE_URL`:

   ```bash
   python manage.py migrate
   ```

   ```bash
   python manage.py seed_opportunities
   ```

3. **Vercel:** import the GitHub repository (Framework preset: Other), pick the branch, and add these
   environment variables:

   | Variable | Value |
   |---|---|
   | `DEBUG` | `False` |
   | `DJANGO_SECRET_KEY` | a new long random value (not your local one) |
   | `DATABASE_URL` | the Neon pooled connection string |
   | `ALLOWED_HOSTS` | your custom domain, if any (Vercel's own URLs are allowed automatically) |
   | `AI_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_REASONING_EFFORT` | as in your `.env` |
   | `CV_MAX_UPLOAD_MB` | `4` (Vercel rejects request bodies over 4.5 MB) |

4. Deploy. Later schema changes: run `migrate` against Neon again before deploying.

Notes: the function may run up to 60 s (`maxDuration` in `vercel.json`), which covers a slow live AI
call (45 s timeout). The first request after a quiet period is slower (cold start). The retention
purge (`purge_expired_data`) is not scheduled on Vercel; run it from your machine against Neon, or add a
scheduled job. Static files are cache-busted by the deployed commit (`VERCEL_GIT_COMMIT_SHA`).

## Security and privacy for a real deployment

This prototype has no accounts and is meant for fictional data. Beyond what is listed above, a real
deployment would need:

- **Authentication and authorisation:** user accounts (with MFA option), profiles owned by users rather
  than sessions, per-object permission checks on every endpoint, rate limiting.
- **Encryption:** HTTPS only (HSTS, secure and HttpOnly cookies, `SECURE_*` settings), encryption at rest
  for the database and backups, secrets in a secret manager rather than `.env`.
- **Consent and contracts:** the consent text should also name the provider's region and its own
  retention terms, and a data processing agreement with the provider is needed.
- **Data minimisation:** name and address detection (for example with a named-entity model) on top of
  the pattern-based removal; avoid special-category data.
- **Retention:** run `purge_expired_data` on a schedule and cover backups and logs by the same policy.
- **Access logging and monitoring:** audit logs for access to personal data and admin actions, alerting
  on unusual access, log redaction so CV text and profiles never appear in logs.
- **Other:** content security policy and self-hosted, bundled JavaScript (no in-browser Babel or
  third-party CDNs), dependency scanning, malware scanning of uploads, a DPIA for the CV feature.

## Known limitations

- Skill matching is exact after normalisation with a small synonym map; related skills in other words
  are not credited by the rules (the AI may point them out).
- Education field relevance uses simple word overlap.
- Interest matching is exact on normalised tags.
- Only text-based PDFs are supported for CVs; no OCR, no Word files.
- In-browser Babel compilation is slow on first load and is not suitable for production.
- Sessions are anonymous; clearing cookies loses the profile and shortlist (the profile is then removed
  by the retention purge).
- Contact-detail removal is pattern-based: it catches emails, phone numbers and links, not names or
  postal addresses.
- The shared AI cache is keyed by profile content, so a visitor who enters a profile identical to someone
  else's gets that cached answer, marked "cached" and returned instantly. It reveals nothing the visitor did
  not type, but it does show that someone submitted the same profile. This sharing is useful for the
  built-in sample profile; limiting it to the sample would remove the hint for real profiles.
- Anyone holding a visitor's session cookie acts as that visitor (there are no accounts). Over plain HTTP
  the cookie can be intercepted; with `DEBUG` off the app forces HTTPS and secure cookies.
- Live AI was checked by hand against Groq (CV extraction, three match assessments, the cache, the browser
  flow); the automated tests never call a provider.
- `call_with_timeout` stops waiting at the timeout but cannot cancel an in-flight HTTP request.
- The mock assessment restates the rule result; it adds no new information.
- 12 seed opportunities; no admin UI for editing them (edit the JSON and re-run the seed command).
