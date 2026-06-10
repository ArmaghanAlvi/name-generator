export type ResultCategory =
  | "established"
  | "related"
  | "translation"
  | "root"
  | "generated";

export type MatchType = "exact" | "expanded";

export type NamePartKind =
  | "root"
  | "word"
  | "inspired"
  | "crafted";

export type GenerationFlavor =
  | "default"
  | "fantasy"
  | "ancient-inspired"
  | "modern";

export interface NamePart {
  text: string;
  meaning: string;
  language: string;
  kind: NamePartKind;
  note?: string | null;
}

export interface AlternateMeaning {
  meaning: string;
  explanation: string;
  nativeForm?: string | null;
  isPrimary?: boolean;
}

export interface RelatedName {
  name: string;
  relationshipType: string;
  notes?: string | null;
}

export interface NameResult {
  id: string;
  name: string;
  category: ResultCategory;
  meaning: string;
  language: string;
  explanation: string;

  matchType?: MatchType;
  matchedConcept?: string;

  sourceLanguages?: string[];
  flavors?: GenerationFlavor[];
  parts?: NamePart[];

  alternateMeanings?: AlternateMeaning[];
  relatedNames?: RelatedName[];
}