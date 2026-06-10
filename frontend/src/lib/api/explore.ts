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