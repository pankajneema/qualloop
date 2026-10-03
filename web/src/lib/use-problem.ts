'use client';

import { useTranslations } from 'next-intl';

import { ApiError } from '@/lib/api';
import type { Described } from '@/lib/problem';

/** Describes an API error in the user's language: the API's own words when it sent them, translated copy otherwise. */
export function useDescribe(): (error: unknown) => Described {
  const t = useTranslations('common.problem');
  const fallback = { title: t('title'), detail: t('detail'), reference: t('reference') };
  return (error) =>
    (error instanceof ApiError ? error : new ApiError(0, null, null)).describe(fallback);
}
