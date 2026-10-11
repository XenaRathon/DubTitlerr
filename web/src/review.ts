import { diffWordsWithSpace } from 'diff';

export const riskLabels = {
  words: 'Words added / dropped',
  substitution: 'Word substitution',
  punctuation: 'Punctuation / case',
};
export const verdictLabels = {
  accept: 'Keep repair',
  reject: 'Keep original',
  correct: 'Write correction',
  force: 'Override guard',
};
export function timecode(seconds: number) {
  const s = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const mm = Math.floor(s / 60) % 60;
  const ss = String(s % 60).padStart(2, '0');
  return s >= 3600
    ? `${Math.floor(s / 3600)}:${String(mm).padStart(2, '0')}:${ss}`
    : `${Math.floor(s / 60)}:${ss}`;
}
/** Index of the next row after `from` that has no staged verdict; `from` itself when none follows (no wrap). */
export function nextOpenIndex(ids: string[], isStaged: (id: string) => boolean, from: number) {
  for (let i = from + 1; i < ids.length; i++) if (!isStaged(ids[i])) return i;
  return from;
}
export function diffParts(original: string, proposed: string, side: 'original' | 'proposed') {
  return diffWordsWithSpace(original, proposed).filter((p) => (side === 'original' ? !p.added : !p.removed));
}
export function blank(text: string) {
  return !/[^\s\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]/u.test(text);
}
