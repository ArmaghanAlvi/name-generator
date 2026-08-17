# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Namecraft (product-facing name "NameForge" in project notes) — a semantic name generator. Users search by *meaning*, and the backend traverses a multilingual wordnet-style graph (synonyms, translations, sense relations) to surface names/words related to that meaning across ~21 languages, ranked and grouped by hop distance from the queried sense.

- `backend/` — FastAPI + SQLAlchemy + Postgres/pgvector. The real engine: sense graph traversal, root selection, vector search, data import pipeline.
- `frontend/` — Next.js 16 (App Router) + React 19 + Tailwind 4. Thin client over the backend API.

## Commands

### Backend

```bash
# from repo root, backend venv already exists at backend/.venv
source backend/.venv/bin/activate

# run the API (from backend/)
cd backend && uvicorn app.main:app --reload

# run the whole test suite (from repo root — pytest.ini lives here)
python -m pytest

# run a single test file / test
python -m pytest backend/tests/test_sense_display.py
python -m pytest backend/tests/test_sense_display.py::test_single_gloss_is_used_verbatim

# migrations (from backend/, where alembic.ini lives)
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "..."
```

Tests use an in-memory SQLite DB (`backend/tests/conftest.py`), not Postgres — no running DB needed to run `pytest`.

### Database

```bash
docker-compose up -d   # pgvector/pgvector:pg17, exposed on localhost:5433
```

`backend/.env` (see `backend/.env.example`) sets `DATABASE_URL` (`postgresql+psycopg://...`). `backend/app/config.py` loads it via pydantic-settings.

### Frontend

```bash
cd frontend
npm run dev     # http://localhost:3000
npm run build
npm run lint
```

Backend CORS (`app/main.py`) only allows `localhost:3000`/`127.0.0.1:3000`.

## Architecture

### Domain model (`backend/app/models/`)

Two model files, split by role:
- `generated_name.py` — `Language`, `GeneratedName`, `NamePart`, `GenerationFlavorModel`: the curated/generated-name side.
- `semantic.py` — the sense graph: `Source`, `Lexeme`/`Word`, `Sense`, `WordSense`, `Concept`, `SenseRelation`, `SenseEmbedding` (pgvector), `SenseSynset`/ILI bridge rows, `SenseTranslation`, `RootLlmAttempt`. This is the larger, load-bearing schema.

### Request flow

`app/api/routes/*` are thin — they call into `app/services/*`, which holds essentially all logic:

- `POST /generate` → `services/generated_names.py` — simple curated-name search.
- `POST /explore-v2` → the core semantic engine, branching on whether `languageCodes` is present:
  - **Legacy single-tree path** (no `languageCodes`) → `services/multi_hop_expansion.py`. Explicitly commented as "BYTE-IDENTICAL, guarded by `diff_reference.py`" — do not change its output shape casually.
  - **Parallel multilingual path** (`languageCodes` present) → `services/parallel_expansion.py`, which builds one traversal tree per requested language, then interleaves them (root band first, then round-robin) for display.
- `GET /languages` → `services/language_directory.py` (rewritten in Phase C for performance — see below).

### Root selection: the multilingual entry point

Before a language's tree can be expanded, it needs a *root* — the equivalent word in that language for the queried English sense. This is its own subsystem, `services/root_selection.py`, described in full in `notes/MULTILINGUAL_EXPANSION_MODEL.md`. It's a five-rung provenance ladder, evaluated in this order:

```
corroborated → primary → ili → llm → pivoted_root → fallback (vector NN)
```

Each rung is a different evidence source (translation link, shared interlingual index, LLM-proposed + DB-validated translation, a pivot through Russian, or embedding nearest-neighbor as last resort). Fallback-rung roots are the least trustworthy — a wrong root poisons its entire tree — and are marked with their rung in the API response (`rootRung`) so a bad root is diagnosable from the output. Per-language-pair similarity floors for the fallback and pivot-rescue rungs are hardcoded calibration constants at the top of `root_selection.py`, derived from `scripts/eval/root_link_calibration.py` — don't hand-tune them without re-running that calibration.

**Naming gotcha:** "root" is overloaded. `root_selection.py` / `RootLlmAttempt` / `rootRung` refer to this per-language tree-root concept. A now-deleted "pink-card" `Root`/`RootMeaning` model family (a different, unrelated feature) was fully removed in the Phase A cleanup (see `notes/CLEANUP_AND_TWEAKS_ROADMAP.MD`) — if you see references to it in old notes, it no longer exists in code.

### Vector search

`services/vector_scope.py` / `vector_sense_search.py` wrap pgvector HNSW queries over `SenseEmbedding`. `embedding_provider.py` wraps the embedding model (e5-family; cosine similarity is only meaningful *within* one language pair — there's a constant anisotropy offset across pairs, see comments in `root_selection.py`). `embed_query` is LRU-cached (safe — deterministic inference, results copied on return) since it's the largest single cost in a cold search per `phase_timing.py` measurements.

### Data pipeline (import-once, not request-path)

`app/importers/` and `app/extractors/` load the sense graph from external sources (Kaikki Wiktionary dumps, Open English WordNet / OMW). `app/review/` and `app/review_ui/` (Streamlit apps — `review_app.py`, `sense_admin_app.py`) are manual-review tooling for the imported/curated data, run standalone (`streamlit run app/review_ui/review_app.py`), not part of the API. `app/seed.py` seeds dev data. None of this runs on the request path.

### Byte-identity regression harness — read before touching engine code

This project's standing convention (see `notes/CLEANUP_AND_TWEAKS_ROADMAP.MD` appendix and `notes/MULTILINGUAL_EXPANSION_MODEL.md`) is: **measure before fixing, and verify semantic-engine changes don't alter output** using scripted diff tools in `backend/scripts/eval/`, not just `pytest`:

- `capture_engine_reference.py` / `capture_api_current.py` snapshot expansion output to `engine_reference.json` / `api_current.json`; `diff_reference.py` diffs them (word-sequence identity) — covers the **legacy single-tree path only**.
- `capture_parallel_reference.py` / `root_selection_diff.py` are the equivalent gates for the **parallel multilingual path** (`diff_reference.py` never exercises it, since `capture_api_current.py` issues English-only requests).
- These are run after any change touching `multi_hop_expansion.py`, `parallel_expansion.py`, `root_selection.py`, `vector_scope.py`, `sense_reranker.py`, `dropdown_ranker.py`, etc. — a 0-diff result is the bar, not a nice-to-have.
- `capture_api_current.py` has a side effect (writes `SenseSelectionStat`) that `capture_engine_reference.py` does not — re-baseline references before comparing if ordinary API usage happened in between.

If you're asked to change ranking/traversal/root-selection behavior, check `notes/MULTILINGUAL_EXPANSION_MODEL.md` and `notes/CLEANUP_AND_TWEAKS_ROADMAP.MD` first — both are living decision records with a lot of "we measured X, rejected Y because Z" history that will stop you from re-deriving already-rejected approaches.

### Frontend structure

- `src/app/generate/page.tsx` — main search page.
- `src/components/generator/GeneratorPrototype.tsx` — primary search/results UI.
- `src/lib/api/{generate,explore}.ts` — typed fetch wrappers for the two backend endpoints.
- `src/features/generator/types.ts` — shared result/request types mirroring the backend Pydantic schemas (`app/schemas/generate.py`, `app/schemas/explore_v2.py`) — keep them in sync manually, there's no codegen.

## Notes directory

`notes/*.md` are living design/decision documents, not historical archives — check them before making non-trivial changes to search ranking, root selection, multilingual traversal, or the search UI, since they record prior measurements and explicitly rejected approaches. `notes/CLEANUP_AND_TWEAKS_ROADMAP.MD` is the most current one and tracks in-progress cleanup phases (A–D) against `git log`.


## Additional instructions
Never make irreversible changes to the database without waiting for confirmation, and explaining the change.