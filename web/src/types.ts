export type Verdict = 'accept' | 'reject' | 'correct' | 'force';
export type Risk = 'words' | 'substitution' | 'punctuation';
export interface Episode {
  stem: string;
  name: string;
  season: string;
  show: string;
  pending: number;
  admitted: number;
  refused: number;
}
export interface Entry {
  id: string;
  index: number;
  original_text: string;
  proposed_text: string;
  stage: string;
  reason: string;
  risk: Risk;
  reference?: string;
  starts: number[];
  context: { before: string[]; after: string[] }[];
  offered: Verdict[];
  permanent: boolean;
  avg_logprob?: number;
}
export interface Shared extends Omit<
  Entry,
  'index' | 'starts' | 'context' | 'stage' | 'reason' | 'permanent'
> {
  show: string;
  episodes: number;
  pair: number;
}
export interface Draft {
  verdict: Verdict;
  text: string;
  note: string;
}
export interface SaveResult {
  saved: number;
  error?: string;
  warning?: string;
  errors?: { index?: number; id?: string; error: string }[];
}
