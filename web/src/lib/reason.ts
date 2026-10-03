/** The reason rule shared by every ReasonDialog (API.md 1.8: 1 to 2000 characters after trimming). */
export const REASON_MAX = 2000;

export function reasonError(value: string): 'required' | 'too_long' | null {
  const length = value.trim().length;
  if (length === 0) return 'required';
  if (length > REASON_MAX) return 'too_long';
  return null;
}

export function isValidReason(value: string): boolean {
  return reasonError(value) === null;
}
