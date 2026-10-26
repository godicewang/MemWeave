import MiniSearch from "minisearch";
import type { PolicySettings } from "../config/defaults.ts";
export interface SearchDocument {
  task_id: string;
  goal: string;
  title: string;
  summary: string;
  keywords: string[];
  project_name: string;
  updated_at: string;
  vector: number[];
  similarity?: number;
}
const segmenter = new Intl.Segmenter("zh", { granularity: "word" });
export const terms = (text: string) =>
  [...segmenter.segment(text.toLocaleLowerCase())]
    .filter((p) => p.isWordLike)
    .map((p) => p.segment);
export function rankTasks<T extends SearchDocument>(
  docs: T[],
  query: string,
  keywords: string[],
  vector: number[],
  settings: PolicySettings["task_search"],
) {
  const fields = Object.keys(settings.field_weights);
  const index = new MiniSearch<T>({
    fields,
    idField: "task_id",
    tokenize: terms,
    processTerm: (term) => term,
    extractField: (doc, field) =>
      Array.isArray(doc[field as keyof T])
        ? (doc[field as keyof T] as string[]).join(" ")
        : String(doc[field as keyof T] ?? ""),
  });
  index.addAll(docs);
  const hits = new Map(
    index
      .search(query, {
        boost: settings.field_weights,
        fuzzy: false,
        prefix: false,
      })
      .map((hit) => [String(hit.id), hit.score]),
  );
  const lexical = docs.map((doc) => hits.get(doc.task_id) ?? 0);
  const wanted = new Set(keywords.map((k) => k.toLocaleLowerCase()));
  const keywordScores = docs.map(
    (d) => d.keywords.filter((k) => wanted.has(k.toLocaleLowerCase())).length,
  );
  const semantic = docs.map((d) => {
    if (d.similarity !== undefined) return d.similarity;
    if (
      d.vector.length !== vector.length ||
      !d.vector.every(Number.isFinite) ||
      !vector.every(Number.isFinite)
    )
      throw Error("INVALID_TASK_EMBEDDING");
    let dot = 0,
      a = 0,
      b = 0;
    for (let i = 0; i < vector.length; i++) {
      dot += d.vector[i]! * vector[i]!;
      a += d.vector[i]! ** 2;
      b += vector[i]! ** 2;
    }
    return a && b ? dot / Math.sqrt(a * b) : 0;
  });
  const ranks = {
    lexical: new Map<number, number>(),
    semantic: new Map<number, number>(),
    keywords: new Map<number, number>(),
  };
  for (const [name, scores] of [
    ["lexical", lexical],
    ["semantic", semantic],
    ["keywords", keywordScores],
  ] as const) {
    scores
      .map((score, i) => ({ score, i }))
      .filter((d) => d.score > 0)
      .sort(
        (a, b) =>
          b.score - a.score ||
          docs[a.i]!.task_id.localeCompare(docs[b.i]!.task_id),
      )
      .slice(0, settings.candidates_per_channel)
      .forEach((d, i) => ranks[name].set(d.i, i + 1));
  }
  return docs
    .map((doc, i) => ({
      ...doc,
      score: (Object.keys(ranks) as (keyof typeof ranks)[]).reduce(
        (n, k) =>
          n +
          (ranks[k].has(i)
            ? settings.channel_weights[k] /
              (settings.rrf_constant + ranks[k].get(i)!)
            : 0),
        0,
      ),
      ranks: {
        lexical: ranks.lexical.get(i) ?? null,
        semantic: ranks.semantic.get(i) ?? null,
        keywords: ranks.keywords.get(i) ?? null,
      },
    }))
    .filter((d) => d.score > 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        Date.parse(b.updated_at) - Date.parse(a.updated_at) ||
        a.task_id.localeCompare(b.task_id),
    );
}
