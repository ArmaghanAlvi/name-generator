export type ResultCategory =
  | "established"
  | "related"
  | "translation"
  | "root"
  | "generated";

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
  note?: string;
}

export interface NameResult {
  id: string;
  name: string;
  category: ResultCategory;
  meaning: string;
  language: string;
  explanation: string;
  parts?: NamePart[];

  // Used when a generated name draws from one or more languages.
  sourceLanguages?: string[];

  // Used only for generated-name cards.
  flavors?: GenerationFlavor[];
}