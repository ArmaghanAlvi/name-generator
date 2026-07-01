import type { HopPathStep, NameResult } from "@/features/generator/types";

interface ExploreMeaningsRequest {
  meanings: string[];
  expansionCount: number;
  language: string | null;
  minLength: number;
  maxLength: number;
}

interface ExpandedConcept {
  slug: string;
  label: string;
  relationshipType: string;
  weight: number;
}

interface ExploreMeaningsResponse {
  matchedConcepts: string[];
  expandedConcepts: ExpandedConcept[];
  results: NameResult[];
}

export async function exploreMeanings(
  request: ExploreMeaningsRequest
): Promise<ExploreMeaningsResponse> {
  const response = await fetch("http://127.0.0.1:8000/explore", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Backend returned status ${response.status}`);
  }

  return response.json();
}

export interface SenseOption {
  senseId: number;
  word: string;
  language: string;
  languageCode: string | null;
  partOfSpeech: string;
  definition: string;
  rawGlosses: string[];
  tags: string[];
  categories: string[];
  selectionCount: number;
  pinnedRank: number | null;
  isHidden: boolean;
  sourceLocator: string;
}

export interface SenseLookupResponse {
  query: string;
  options: SenseOption[];
}

export async function lookupSenses(
  query: string,
  languageCode = "en"
): Promise<SenseLookupResponse> {
  const params = new URLSearchParams({
    query,
    languageCode,
  });

  const response = await fetch(
    `http://127.0.0.1:8000/senses/lookup?${params.toString()}`
  );

  if (!response.ok) {
    throw new Error(`Backend returned status ${response.status}`);
  }

  return response.json();
}

export interface ExploreSelectedSensesRequest {
  selectedSenseIds: number[];
  queryText: string;
  breadth: number;   // expansions per node (0-3); 0 = exact meaning only
  depth: number;     // hops (0-3); 0 = exact meaning only
  language: string | null;
  minLength: number;
  maxLength: number;
}

// Mirrors the backend's ExploreV2Result exactly (app/schemas/explore_v2.py).
export interface ExploreV2Result {
  id: string;
  name: string;
  category: "established" | "related" | "translation" | "root" | "generated";
  meaning: string;
  language: string;
  explanation: string;
  matchType: "exact" | "expanded";
  matchedSenseId: number;
  relationshipType: string;
  relationshipWeight: number;
  partOfSpeech: string;
  depth: number;
  parentSenseId: number | null;
  provenance: string | null;
  path: HopPathStep[];
}

export interface ExploreSelectedSensesResponse {
  selectedSenseIds: number[];
  expandedSenses: {
    senseId: number;
    word: string;
    language: string;
    definition: string;
    relationshipType: string;
    weight: number;
  }[];
  results: ExploreV2Result[];
}

// The mapped shape the UI consumes: same envelope, results as NameResult[].
export interface ExploreSelectedSensesResult {
  selectedSenseIds: number[];
  expandedSenses: ExploreSelectedSensesResponse["expandedSenses"];
  results: NameResult[];
}

// D3 adapter: explore-v2 sends ExploreV2Result; the UI consumes NameResult.
// Every field here is real backend output; NameResult's other optional fields
// (parts, flavors, matchedConcept, ...) are mock/generator-era and never come
// from this endpoint.
export function toNameResult(r: ExploreV2Result): NameResult {
  return {
    id: r.id,
    name: r.name,
    category: r.category,
    meaning: r.meaning,
    language: r.language,
    explanation: r.explanation,
    matchType: r.matchType,
    matchedSenseId: r.matchedSenseId,
    relationshipType: r.relationshipType,
    relationshipWeight: r.relationshipWeight,
    partOfSpeech: r.partOfSpeech,
    depth: r.depth,
    parentSenseId: r.parentSenseId,
    provenance: r.provenance,
    path: r.path,
  };
}

export async function exploreSelectedSenses(
  request: ExploreSelectedSensesRequest
): Promise<ExploreSelectedSensesResult> {
  // Map UI semantics (breadth/depth, both 0-3) onto the API contract
  // (expansionCount, width, depth>=1):
  //   breadth=0 OR depth=0  -> exact meaning only: single-hop, expansionCount=0
  //   depth=1               -> single-hop with expansionCount=breadth
  //   depth>=2              -> multi-hop with width=breadth
  const exactOnly = request.breadth === 0 || request.depth === 0;
  const body = {
    selectedSenseIds: request.selectedSenseIds,
    queryText: request.queryText,
    expansionCount: exactOnly ? 0 : request.breadth,
    width: exactOnly || request.depth === 1 ? null : request.breadth,
    depth: exactOnly ? 1 : request.depth,
    language: request.language,
    minLength: request.minLength,
    maxLength: request.maxLength,
  };

  const response = await fetch("http://127.0.0.1:8000/explore-v2", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Backend returned status ${response.status}`);
  }

  const data: ExploreSelectedSensesResponse = await response.json();
  return { ...data, results: data.results.map(toNameResult) };
}