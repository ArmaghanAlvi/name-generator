import type { NameResult } from "@/features/generator/types";

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
  expansionCount: number;
  language: string | null;
  minLength: number;
  maxLength: number;
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
  results: NameResult[];
}

export async function exploreSelectedSenses(
  request: ExploreSelectedSensesRequest
): Promise<ExploreSelectedSensesResponse> {
  const response = await fetch("http://127.0.0.1:8000/explore-v2", {
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