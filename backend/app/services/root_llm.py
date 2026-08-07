"""
LLM translation proposer + resolver for root selection's `llm` rung
(Breakdown 4.5). The model PROPOSES candidate target-language words for one
English sense; admission requires resolving through the SAME discipline as
every curated rung: normalize_lemma -> lexeme in target language -> viable
display sense. The model proposes, the database disposes.

Provider-agnostic over HTTP (httpx). Default request shape: Google Gemini
generateContent (free tier), JSON response mode. Swap providers by editing
_request() and _extract_text() only.

Config (env):
  ROOT_LLM_API_KEY      required for live calls
  ROOT_LLM_MODEL        gemini-flash-lite-latest
  ROOT_LLM_RPM          per-process politeness cap, default 8
  ROOT_LLM_QUERY_TIME   '1' to allow live resolution in the query path
                        (decision 1d; default OFF -- backfill is primary)

CLI smoke (from backend/):
  python3 -m app.services.root_llm --lemma light \
      --gloss "electromagnetic radiation that enables sight" \
      --pos noun --target ru
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

from app.config import BACKEND_DIR

load_dotenv(BACKEND_DIR / ".env")
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.generated_name import Language
from app.models.semantic import (
    Lexeme, RootLlmAttempt, Sense, SenseTranslation, Source,
)
from app.utils.text import normalize_lemma

ROOT_LLM_MODEL = os.environ.get("ROOT_LLM_MODEL", "gemini-flash-lite-latest")
ROOT_LLM_RPM = int(os.environ.get("ROOT_LLM_RPM", "8"))
QUERY_TIME_LIVE = os.environ.get("ROOT_LLM_QUERY_TIME", "0") == "1"

_PROMPT = """You are a bilingual lexicographer. Give the standard {language} \
translation(s) of the English word below, in the specific sense given.

English word: {lemma} ({pos})
Sense: {gloss}

Return ONLY a JSON array of 1 to 3 strings: the most standard {language} \
words for exactly this sense, as dictionary lemma (citation) forms in native \
script. Most standard first. No romanization, no explanations. If no good \
translation exists, return []."""

_last_call = 0.0


def _throttle() -> None:
    global _last_call
    gap = 60.0 / max(ROOT_LLM_RPM, 1)
    wait = _last_call + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def can_call_now() -> bool:
    """True only if a call right now would NOT have to sleep inside
    _throttle(). The query path (parallel_expand's live trickle, decision
    1d) must take an LLM call opportunistically or skip it -- a root found
    this way is worth ~0ms of added latency, never the 7.5s throttle gap or
    a 20s 429-retry sleep. The backfill script does not use this: it has no
    user waiting and should throttle/retry normally."""
    gap = 60.0 / max(ROOT_LLM_RPM, 1)
    return time.monotonic() >= _last_call + gap


def _request(prompt: str) -> dict:
    key = os.environ.get("ROOT_LLM_API_KEY")
    if not key:
        raise RuntimeError("ROOT_LLM_API_KEY not set")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{ROOT_LLM_MODEL}:generateContent?key={key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0,
                             "responseMimeType": "application/json"},
    }
    _throttle()
    r = httpx.post(url, json=body, timeout=30.0)
    if r.status_code == 429:          # one polite retry on rate limit
        time.sleep(20)
        _throttle()
        r = httpx.post(url, json=body, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _extract_text(data: dict) -> str:
    return data["candidates"][0]["content"]["parts"][0]["text"]


def propose_translations(*, lemma: str, pos: str, gloss: str,
                         language_name: str) -> tuple[list[str], str]:
    """Returns (proposals, actual_served_model_version) -- 'latest' aliases
    silently resolve to a concrete version at request time (Breakdown 4.5
    finding, 7/24/26); the served version is what gets persisted, not the
    alias, so a future alias rotation doesn't retroactively blur history."""
    prompt = _PROMPT.format(language=language_name, lemma=lemma,
                            pos=pos or "word", gloss=gloss)
    response = _request(prompt)
    text_out = _extract_text(response).strip()
    if text_out.startswith("```"):
        text_out = text_out.strip("`").removeprefix("json").strip()
    parsed = json.loads(text_out)
    served_model = response.get("modelVersion", ROOT_LLM_MODEL)
    if not isinstance(parsed, list):
        raise ValueError(f"non-list response: {parsed!r}")
    return [str(w).strip() for w in parsed if str(w).strip()][:3], served_model


def _llm_source_id(db: Session) -> int:
    src = db.scalars(select(Source).where(Source.slug == "llm-root")).first()
    if src is None:
        src = Source(
            slug="llm-root",
            name="LLM root translations",
            # source_type is NOT NULL. New category alongside the existing
            # 'wordnet' / 'wiktionary' / 'dictionary_dump' values -- keeps
            # generated evidence sortable apart from curated corpora.
            source_type="llm",
            notes="Gemini-proposed translations, DB-resolution gated "
                  "(Breakdown 4.5). Never curated evidence.",
        )
        db.add(src)
        db.flush()
    return src.id


def resolve_llm_root(db: Session, *, english_sense_id: int,
                     language_code: str) -> int | None:
    """
    Resolve-once entry point (backfill + optional query-time). Returns the
    resolved target lexeme id, or None. Idempotent via root_llm_attempts:
    resolved/unresolved short-circuit with NO API call; 'error' retries.
    Commits its own work (ledger semantics require durability per pair).
    """
    lang = db.scalars(select(Language).where(Language.code == language_code)).first()
    sense = db.get(Sense, english_sense_id)
    if lang is None or sense is None:
        return None
    # Snapshot as plain values: a rollback in the error path EXPIRES ORM
    # attributes, and re-loading them mid-recovery is what turned a simple
    # DB error into PendingRollbackError (Breakdown 4.5, 7/24/26).
    lang_id, lang_code, lang_name = lang.id, lang.code, lang.name

    prior = db.scalars(
        select(RootLlmAttempt).where(
            RootLlmAttempt.sense_id == english_sense_id,
            RootLlmAttempt.language_id == lang_id)
    ).first()
    if prior is not None and prior.status != "error":
        return prior.resolved_lexeme_id

    gloss = (sense.definition or "").strip() or \
            (sense.raw_glosses[0] if sense.raw_glosses else "")
    proposed: list[str] = []
    served_model = ROOT_LLM_MODEL          # overwritten once the call lands
    status, resolved_lexeme_id = "unresolved", None
    try:
        proposed, served_model = propose_translations(
            lemma=sense.lexeme.lemma, pos=sense.lexeme.part_of_speech,
            gloss=gloss, language_name=lang_name,
        )
        # Resolve ALL proposals (not just the first that resolves), then
        # pick by cross-language cosine to the EN sense -- same tie-break
        # rungs 1-2 use. Fixes a measured gap (Breakdown 4.5 Step 5:
        # precision_any > precision_top1 for every language, worst on la,
        # 62% vs 52%) where "first resolving" wasn't always "best."
        from app.services.root_selection import (
            _cross_sim, _display_sense, _en_vector,
        )
        en_vector = _en_vector(db, english_sense_id)
        resolved: list[tuple[float, str, int]] = []  # (sim, word, lex_id)
        for word in proposed:
            norm = normalize_lemma(word, lang_code)
            # normalize_lemma casefolds (and NFD-folds Latin macrons), so one
            # normalized form can map to SEVERAL lexemes -- la 'canis' noun
            # (viable) vs 'Canis' name (no visible+embedded sense). Taking the
            # lowest id blind silently drops a good proposal whenever the dud
            # sorts first. Walk candidates; keep the first VIABLE one.
            cand_ids = [i for (i,) in db.execute(
                select(Lexeme.id)
                .where(Lexeme.language_id == lang_id,
                       Lexeme.normalized_lemma == norm)
                .order_by(Lexeme.id)
            )]
            for lex_id in cand_ids:
                disp = _display_sense(db, lex_id, en_vector)
                if disp is None:
                    continue                  # the database disposes
                resolved.append(
                    (_cross_sim(db, en_vector, disp.id), word, lex_id))
                break

        if resolved:
            _sim, word, lex_id = max(resolved, key=lambda r: r[0])
            norm = normalize_lemma(word, lang_code)
            # Persist the link; repair a stale-NULL curated row if it
            # collides (decision 1e) -- curated evidence keeps the credit.
            db.execute(
                pg_insert(SenseTranslation).values(
                    sense_id=english_sense_id, language_id=lang_id,
                    target_text=word, target_normalized=norm,
                    target_lexeme_id=lex_id, attachment="llm",
                    source_id=_llm_source_id(db),
                ).on_conflict_do_update(
                    constraint="uq_sense_translations_link",
                    set_={"target_lexeme_id": lex_id},
                    where=SenseTranslation.target_lexeme_id.is_(None),
                )
            )
            status, resolved_lexeme_id = "resolved", lex_id
    except Exception as exc:
        # A DB error inside the try leaves the session in a failed
        # transaction; without this rollback the ledger write below fails
        # too, turning one bad pair into a dead backfill run. Cause is
        # printed because 'error' alone is undiagnosable after the fact.
        db.rollback()
        status, resolved_lexeme_id = "error", None
        print(f"[root_llm] {language_code} sense={english_sense_id}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)

    if prior is not None:                     # retried an 'error' row
        prior.status, prior.model = status, served_model
        prior.proposed, prior.resolved_lexeme_id = proposed, resolved_lexeme_id
    else:
        db.add(RootLlmAttempt(
            sense_id=english_sense_id, language_id=lang_id, status=status,
            model=served_model, proposed=proposed,
            resolved_lexeme_id=resolved_lexeme_id,
        ))
    db.commit()
    return resolved_lexeme_id


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lemma", required=True)
    ap.add_argument("--gloss", required=True)
    ap.add_argument("--pos", default="noun")
    ap.add_argument("--target", required=True)
    a = ap.parse_args()
    _NAMES = {"la": "Latin", "ru": "Russian", "ja": "Japanese", "ar": "Arabic"}
    words, served = propose_translations(lemma=a.lemma, pos=a.pos,
                                         gloss=a.gloss,
                                         language_name=_NAMES[a.target])
    print(words, "| served by:", served)