"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  exploreMeanings,
  exploreSelectedSenses,
  lookupSenses,
  type SenseOption,
} from "@/lib/api/explore";
import type {
  GenerationFlavor,
  NamePartKind,
  NameResult,
  ResultCategory,
} from "@/features/generator/types";

type CategoryFilter = ResultCategory | "all";
type SortOption = "az" | "za" | "shortest" | "longest";

const categoryOptions: { value: CategoryFilter; label: string }[] = [
  { value: "all", label: "All result types" },
  { value: "established", label: "Established names" },
  { value: "translation", label: "Translations and words" },
  { value: "root", label: "Roots" },
  { value: "generated", label: "Generated names" },
];

const categoryLabels: Record<ResultCategory, string> = {
  established: "Established name",
  related: "Related word",
  translation: "Semantic equivalent",
  root: "Root",
  generated: "Generated name",
};

const categoryStyles: Record<ResultCategory, string> = {
  established: "border-green-200 bg-green-50",
  related: "border-yellow-200 bg-yellow-50",
  translation: "border-yellow-200 bg-yellow-50",
  root: "border-pink-200 bg-pink-50",
  generated: "border-blue-200 bg-blue-50",
};

const partKindLabels: Record<NamePartKind, string> = {
  root: "Verified root",
  word: "Existing word",
  inspired: "Inspired fragment",
  crafted: "Crafted element",
};

const flavorOptions: {
  value: GenerationFlavor;
  label: string;
}[] = [
  { value: "default", label: "Default" },
  { value: "fantasy", label: "Fantasy" },
  { value: "ancient-inspired", label: "Ancient-inspired" },
  { value: "modern", label: "Modern" },
];

const languageOptions = [
  "Arabic",
  "English",
  "Greek",
  "Japanese",
  "Latin",
];

function sortResults(results: NameResult[], sort: SortOption) {
  return [...results].sort((first, second) => {
    if (sort === "za") {
      return second.name.localeCompare(first.name);
    }

    if (sort === "shortest") {
      return first.name.length - second.name.length;
    }

    if (sort === "longest") {
      return second.name.length - first.name.length;
    }

    return first.name.localeCompare(second.name);
  });
}

function getNameLength(name: string) {
  return Array.from(name.replace(/[-\s']/g, "")).length;
}

function formatConceptSlug(slug: string) {
  return slug.replace(/-/g, " ");
}

export function GeneratorPrototype() {
  const [inputValue, setInputValue] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [sort, setSort] = useState<SortOption>("az");
  const [language, setLanguage] = useState("all");
  const [expansionCount, setExpansionCount] = useState(0);
  const [minLength, setMinLength] = useState(0);
  const [maxLength, setMaxLength] = useState(20);
  const [flavor, setFlavor] = useState<GenerationFlavor>("default");

  const [results, setResults] = useState<NameResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [senseOptions, setSenseOptions] = useState<SenseOption[]>([]);
  const [selectedSenseIds, setSelectedSenseIds] = useState<number[]>([]);
  const [isLookingUpSenses, setIsLookingUpSenses] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);

  const [hoveredBuiltFrom, setHoveredBuiltFrom] = useState<
    Record<string, boolean>
  >({});
  const hoverTimeouts = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const searchContainerRef = useRef<HTMLDivElement>(null);

  const visibleResults = useMemo(() => {
    const filteredResults = results.filter((result) => {
      const matchesCategory =
        category === "all" || result.category === category;

      const resultLanguages =
        result.sourceLanguages ?? [result.language];

      const matchesLanguage =
        language === "all" || resultLanguages.includes(language);

      const resultLength = getNameLength(result.name);

      const matchesLength =
        resultLength >= minLength && resultLength <= maxLength;

      const resultFlavors: GenerationFlavor[] =
        result.flavors ?? ["default"];

      const matchesFlavor =
        result.category !== "generated" ||
        flavor === "default" ||
        resultFlavors.includes(flavor);

      return (
        matchesCategory &&
        matchesLanguage &&
        matchesLength &&
        matchesFlavor
      );
    });

    return sortResults(filteredResults, sort);
  }, [
    category,
    language,
    minLength,
    maxLength,
    flavor,
    sort,
    results,
  ]);

  useEffect(() => {
    const query = inputValue.trim();

    if (query.length === 0) {
      setSenseOptions([]);
      setShowDropdown(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLookingUpSenses(true);
      try {
        const response = await lookupSenses(query, "en");
        setSenseOptions(response.options);
        setShowDropdown(response.options.length > 0);
      } catch {
        setSenseOptions([]);
        setShowDropdown(false);
      } finally {
        setIsLookingUpSenses(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [inputValue]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        searchContainerRef.current &&
        !searchContainerRef.current.contains(event.target as Node)
      ) {
        setShowDropdown(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function runSearch(senseIds: number[]) {
    if (senseIds.length === 0) return;

    setActiveSearch(inputValue);
    setIsLoading(true);
    setErrorMessage(null);

    try {
      const response = await exploreSelectedSenses({
        selectedSenseIds: senseIds,
        queryText: inputValue,
        expansionCount,
        language: language === "all" ? null : language,
        minLength,
        maxLength,
      });

      setResults(response.results);
    } catch (error) {
      console.error(error);

      setResults([]);
      setErrorMessage(
        "The exploration backend is unavailable. Start FastAPI and search again."
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSenseClick(senseId: number) {
    setShowDropdown(false);
    setSelectedSenseIds([senseId]);
    await runSearch([senseId]);
  }

  async function handleSubmit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();

    if (selectedSenseIds.length === 0) {
      setErrorMessage("Select a meaning from the dropdown first.");
      return;
    }

    await runSearch(selectedSenseIds);
  }

  function scheduleBuiltFromShow(resultId: string) {
    clearTimeout(hoverTimeouts.current[resultId]);
    hoverTimeouts.current[resultId] = setTimeout(() => {
      setHoveredBuiltFrom((current) => ({
        ...current,
        [resultId]: true,
      }));
    }, 550);
  }

  function hideBuiltFrom(resultId: string) {
    clearTimeout(hoverTimeouts.current[resultId]);
    setHoveredBuiltFrom((current) => ({
      ...current,
      [resultId]: false,
    }));
  }

  useEffect(() => {
  const timeouts = hoverTimeouts.current;

  return () => {
    Object.values(timeouts).forEach((timeout) => {
      clearTimeout(timeout);
    });
  };
}, []);

  return (
    <main className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-xl font-bold tracking-tight">
            Namecraft
          </Link>

          <p className="text-sm text-slate-500">UI prototype</p>
        </div>
      </header>

      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-8">
          <h1 className="text-3xl font-bold tracking-tight">
            Explore names by meaning
          </h1>

          <p className="mt-2 text-slate-600">
            Try searching for <strong>light</strong>, <strong>dawn</strong>, or{" "}
            <strong>clarity</strong>.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 max-w-3xl">
            <div className="flex gap-3">
              <div className="relative min-w-0 flex-1" ref={searchContainerRef}>
                <input
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                  onFocus={() => {
                    if (senseOptions.length > 0) setShowDropdown(true);
                  }}
                  placeholder="Enter meanings, such as light, freedom, or sky"
                  className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 outline-none transition focus:border-slate-900"
                />

                {isLookingUpSenses && (
                  <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm text-slate-400">
                    Looking up...
                  </span>
                )}

                {showDropdown && senseOptions.length > 0 && (
                  <div className="absolute inset-x-0 top-full z-50 mt-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lg">
                    {senseOptions.map((option) => (
                      <button
                        key={option.senseId}
                        type="button"
                        onClick={() => handleSenseClick(option.senseId)}
                        className="w-full px-4 py-3 text-left transition hover:bg-slate-50 not-last:border-b not-last:border-slate-100"
                      >
                        <span className="block font-semibold text-slate-900">
                          {option.word} · {option.partOfSpeech}
                        </span>
                        <span className="mt-0.5 block text-sm text-slate-600">
                          {option.definition || "No definition text stored."}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-400">
                          Chosen {option.selectionCount} times
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={isLoading || selectedSenseIds.length === 0}
                className="rounded-2xl bg-slate-900 px-6 py-3 font-semibold text-white transition hover:bg-slate-700 disabled:opacity-40"
              >
                {isLoading ? "Searching..." : "Search"}
              </button>
            </div>
          </form>

          {errorMessage && (
            <p className="mt-3 text-sm font-semibold text-red-600">
              {errorMessage}
            </p>
          )}
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-8 px-6 py-8 lg:grid-cols-[260px_1fr]">
        <aside className="h-fit rounded-3xl border border-slate-200 bg-white p-5">
          <h2 className="font-bold">Filters</h2>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Result type
          </label>

          <select
            value={category}
            onChange={(event) =>
              setCategory(event.target.value as CategoryFilter)
            }
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
          >
            {categoryOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Language
          </label>

          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
          >
            <option value="all">All languages</option>

            {languageOptions.map((languageOption) => (
              <option key={languageOption} value={languageOption}>
                {languageOption}
              </option>
            ))}
          </select>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Meaning expansions
          </label>

          <select
            value={expansionCount}
            onChange={(event) =>
              setExpansionCount(Number(event.target.value))
            }
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
          >
            <option value={0}>0 — Exact meaning only</option>
            <option value={1}>1 expansion</option>
            <option value={2}>2 expansions</option>
            <option value={3}>3 expansions</option>
          </select>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Name length
          </label>

          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-semibold text-slate-500">
                Minimum
              </label>

              <input
                type="number"
                min="0"
                max="30"
                value={minLength}
                onChange={(event) =>
                  setMinLength(Number(event.target.value))
                }
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-500">
                Maximum
              </label>

              <input
                type="number"
                min="0"
                max="30"
                value={maxLength}
                onChange={(event) =>
                  setMaxLength(Number(event.target.value))
                }
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
              />
            </div>
          </div>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Generation flavor
          </label>

          <select
            value={flavor}
            onChange={(event) =>
              setFlavor(event.target.value as GenerationFlavor)
            }
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
          >
            {flavorOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="mt-5 block text-sm font-semibold text-slate-700">
            Sort By
          </label>

          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as SortOption)}
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2"
          >
            <option value="az">First Letter: A–Z</option>
            <option value="za">First Letter: Z–A</option>
            <option value="shortest">Shortest first</option>
            <option value="longest">Longest first</option>
          </select>

        </aside>

        <div>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">
                Results
              </p>

              <h2 className="mt-1 text-2xl font-bold">
                {visibleResults.length} matches for “{activeSearch}”
              </h2>
            </div>
          </div>

          {visibleResults.length === 0 ? (
            <div className="mt-6 rounded-3xl border border-dashed border-slate-300 bg-white p-10 text-center">
              <h3 className="font-bold">No results found</h3>
              <p className="mt-2 text-sm text-slate-600">
                Try searching for light, dawn, or clarity. You can also increase
                the number of meaning expansions.
              </p>
            </div>
          ) : (
            <div className="mt-6 grid gap-4 md:grid-cols-2">
              {visibleResults.map((result) => (
                <article
                  key={result.id}
                  className={`rounded-3xl border p-6 ${categoryStyles[result.category]}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-2xl font-bold">{result.name}</h3>

                      <p className="mt-1 text-sm font-semibold text-slate-700">
                        {categoryLabels[result.category]}
                      </p>

                      {result.matchType && result.matchedConcept && (
                        <span
                          className={`mt-3 inline-flex rounded-full px-3 py-1 text-xs font-semibold shadow-sm ${
                            result.matchType === "exact"
                              ? "bg-white/80 text-slate-700"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {result.matchType === "exact"
                            ? "Exact meaning"
                            : `Related through ${formatConceptSlug(result.matchedConcept)}`}
                        </span>
                      )}
                    </div>

                    <span className="rounded-full bg-white/70 px-3 py-1 text-xs font-semibold text-slate-700">
                      {result.language}
                    </span>
                  </div>

                  <p className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-500">
                    Meaning
                  </p>

                  <p className="mt-1 font-semibold">{result.meaning}</p>

                  <p className="mt-4 text-sm leading-6 text-slate-600">
                    {result.explanation}
                  </p>

                  {result.category === "translation" && (
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                      {result.equivalenceType && (
                        <span className="rounded-full bg-white px-2.5 py-1 font-semibold">
                          {result.equivalenceType.replaceAll("_", " ")}
                        </span>
                      )}

                      {typeof result.senseRank === "number" && (
                        <span className="rounded-full bg-white px-2.5 py-1 font-semibold">
                          rank {result.senseRank}
                        </span>
                      )}

                      {result.source && (
                        <span className="rounded-full bg-white px-2.5 py-1 font-semibold">
                          {result.source}
                        </span>
                      )}

                      {result.confidence && (
                        <span className="rounded-full bg-white px-2.5 py-1 font-semibold">
                          {result.confidence} confidence
                        </span>
                      )}
                    </div>
                  )}
                  
                  {result.category === "generated" &&
                    result.parts &&
                    result.parts.length > 0 && (
                      <div
                        className="relative mt-5"
                        onMouseEnter={() => scheduleBuiltFromShow(result.id)}
                        onMouseLeave={() => hideBuiltFrom(result.id)}
                      >
                        <button
                          type="button"
                          className="w-full rounded-2xl border border-blue-200 bg-white/80 p-3 text-left shadow-sm transition hover:bg-white"
                          aria-expanded={Boolean(hoveredBuiltFrom[result.id])}
                        >
                          <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
                            Generation logic
                          </span>
                        </button>

                        <div
                          className={`absolute inset-x-0 top-full z-20 mt-2 rounded-2xl border border-blue-200 bg-white/95 p-3 shadow-xl transition duration-150 ${
                            hoveredBuiltFrom[result.id]
                              ? "pointer-events-auto opacity-100"
                              : "pointer-events-none opacity-0"
                          }`}
                        >
                          <div className="space-y-3">
                            {result.parts.map((part) => (
                              <div
                                key={`${result.id}-${part.text}`}
                                className="rounded-xl border border-slate-200 bg-white p-3"
                              >
                                <div className="flex flex-wrap items-start justify-between gap-2">
                                  <div>
                                    <p className="font-bold text-slate-900">
                                      {part.text}
                                    </p>

                                    <p className="mt-1 text-xs font-semibold text-slate-500">
                                      {part.language}
                                    </p>
                                  </div>

                                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                                    {partKindLabels[part.kind]}
                                  </span>
                                </div>

                                <p className="mt-3 text-sm text-slate-700">
                                  {part.meaning}
                                </p>

                                {part.note && (
                                  <p className="mt-1 text-xs leading-5 text-slate-500">
                                    {part.note}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}