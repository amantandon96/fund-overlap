export interface Searchable {
  id: string;
  /** Text to match against, e.g. fund name plus fund house. */
  text: string;
}

interface Entry {
  id: string;
  /** Each matchable word with its position in the name. */
  words: { text: string; position: number }[];
  length: number;
}

const tokenize = (text: string): string[] => text.toLowerCase().match(/[a-z0-9]+/g) ?? [];

/**
 * Word-prefix search: every word typed must be the start of some word in the
 * item, in any order, so "hdfc mid" finds "HDFC Mid Cap Fund". Neighbouring
 * words are also joined, so "midcap" finds "Mid Cap" too.
 *
 * The list is a few hundred short names, so each query scans all of it.
 */
export function createSearch(items: Searchable[]) {
  const entries: Entry[] = items.map((item) => {
    const tokens = tokenize(item.text);
    const words = tokens.map((text, position) => ({ text, position }));
    // A joined pair sits at its first word's position, so "midcap" ranks "Mid Cap" like a plain word.
    const joined = tokens.slice(0, -1).map((text, position) => ({ text: text + tokens[position + 1]!, position }));
    return { id: item.id, words: [...words, ...joined], length: item.text.length };
  });

  return function search(query: string, limit = 12, exclude: ReadonlySet<string> = new Set()): string[] {
    const tokens = tokenize(query);
    if (tokens.length === 0) return [];

    const hits: { id: string; score: number }[] = [];
    for (const entry of entries) {
      if (exclude.has(entry.id)) continue;
      let score = 0;
      let matched = true;
      for (const token of tokens) {
        const word = entry.words.find((candidate) => candidate.text.startsWith(token));
        if (!word) {
          matched = false;
          break;
        }
        // Earlier words and exact words rank higher.
        score += word.position + (word.text === token ? 0 : 0.5);
      }
      // Among equal matches, prefer the shorter (usually the plainer) name.
      if (matched) hits.push({ id: entry.id, score: score + entry.length / 1000 });
    }
    hits.sort((a, b) => a.score - b.score);
    return hits.slice(0, limit).map((hit) => hit.id);
  };
}
