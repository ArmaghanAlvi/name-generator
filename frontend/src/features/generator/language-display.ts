/**
 * Language display config for the sidebar and the language sort.
 *
 * ⚠️ WHY THIS FILE EXISTS: the DB's `languages.native_name` is a verbatim copy
 * of `name` on all 21 rows -- not a failed backfill, but a property of the
 * importer, which passes `native_name=name` at creation
 * (app/importers/kaikki_english.py:96-101). `LanguageInfo.nativeName` from
 * /languages therefore returns "Spanish" for `es`. Item 21 cannot be built
 * from the API as it stands.
 *
 * These are UI display strings, not pipeline data: not derived from any
 * import, never entering an embedding, incapable of changing engine output.
 * That is why 21 hand-written entries here do not conflict with the
 * zero-review constraint, which governs sense and relation data.
 *
 * TO RETIRE THIS FILE: give the importer an endonym source and re-import (or
 * backfill), then change languageLabel()'s first line to read
 * `lang.nativeName`. It is the only consumer -- nothing else imports ENDONYMS.
 *
 * Native script, not romanized. Romanization quality is exactly what Phase D
 * is gated on measuring; a wrong transliteration here is worse than a correct
 * native form, and dir="auto" handles the RTL entries.
 *
 * Keys verified against the live `languages` table, 2026-08-14 (21 rows).
 */
export const ENDONYMS: Record<string, string> = {
  en: "English",
  ar: "العربية",
  zh: "中文",
  de: "Deutsch",
  el: "Ελληνικά",
  he: "עברית",
  hi: "हिन्दी",
  is: "Íslenska",
  ga: "Gaeilge",
  ja: "日本語",
  ko: "한국어",
  la: "Latina",
  ang: "Ænglisc",
  non: "Norrœnt mál",
  fa: "فارسی",
  pl: "Polski",
  ru: "Русский",
  sa: "संस्कृतम्",
  es: "Español",
  sw: "Kiswahili",
  cy: "Cymraeg",
};

/**
 * Pinned to the top of the sidebar and of the language sort.
 *
 * NOT a new behavior: /languages already hoists English server-side
 * (app/api/routes/languages.py:50-51). This preserves that pin through the
 * client-side alphabetization rather than introducing one. English holds the
 * "Searched meaning" card and is the pivot language for every non-English
 * tree.
 */
export const PINNED_FIRST = ["en"];

/**
 * "Spanish (Español)" -- English name first.
 *
 * Deliberately matching the sort key below. Endonym-first labels over an
 * English-name sort produce a list that LOOKS unsorted, which is worse than
 * either consistent option. To flip: swap this template AND the sort key.
 *
 * The equality guard is currently inert -- no language name collides with its
 * endonym in the live data (English is the one match, and it is intentionally
 * identical). It exists so a future row whose native_name gets backfilled to
 * the English name does not render "German (German)".
 */
export function languageLabel(lang: { code: string; name: string }): string {
  const endonym = ENDONYMS[lang.code];
  if (!endonym || endonym === lang.name) return lang.name;
  return `${lang.name} (${endonym})`;
}

/**
 * Alphabetical by English name, with PINNED_FIRST hoisted.
 *
 * English name, not endonym: there is no meaningful single collation across
 * Devanagari, Han, Hangul, Arabic, Hebrew, Greek, and Cyrillic, and the user
 * scanning this list is reading the English names.
 *
 * Decoupled from `languages.display_order` -- which is NULL on all 21 rows
 * anyway, so the server's order is currently import order. display_order's
 * job is the backend's parallel interleave: a different concern with a
 * different correct answer.
 */
export function sortLanguages<T extends { code: string; name: string }>(
  languages: T[]
): T[] {
  const rank = (code: string) => {
    const index = PINNED_FIRST.indexOf(code);
    return index === -1 ? PINNED_FIRST.length : index;
  };

  return [...languages].sort((first, second) => {
    const delta = rank(first.code) - rank(second.code);
    if (delta !== 0) return delta;
    return first.name.localeCompare(second.name, "en");
  });
}