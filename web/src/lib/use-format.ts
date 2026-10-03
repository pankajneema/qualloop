'use client';

import { formatDate } from '@/lib/format';
import { usePlantTimeZone } from '@/lib/session';

/** Dates in the plant's timezone, "3 Oct 2026". */
export function useFormatDate(): (iso: string | null | undefined) => string {
  const timeZone = usePlantTimeZone();
  return (iso) => (iso ? formatDate(iso, timeZone) : '');
}
