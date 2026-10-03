'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { AuthShell } from '@/components/auth-shell';
import { Button } from '@/components/button';
import { TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { Alert } from '@/components/states';
import { apiPost, ApiError } from '@/lib/api';

export default function LoginPage() {
  const t = useTranslations('login');
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [missing, setMissing] = useState<{ email?: string; password?: string }>({});

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = {
      ...(email.trim() ? {} : { email: t('errors.email') }),
      ...(password ? {} : { password: t('errors.password') }),
    };
    setMissing(found);
    if (found.email || found.password) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost('/auth/login', { email: email.trim(), password });
      router.replace('/suppliers');
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null, null));
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <h1 className="text-h1 text-ink">{t('title')}</h1>
      <p className="text-body text-muted mt-4">{t('intro')}</p>
      <form onSubmit={submit} noValidate className="mt-24 flex flex-col gap-16">
        {error?.status === 401 ? (
          <Alert tone="error" title={t('bad.title')}>
            {t('bad.detail')}
          </Alert>
        ) : error ? (
          <ProblemAlert error={error} />
        ) : null}
        <TextField
          label={t('email')}
          type="email"
          name="email"
          autoComplete="username"
          required
          error={missing.email}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <TextField
          label={t('password')}
          type="password"
          name="password"
          autoComplete="current-password"
          required
          error={missing.password}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" variant="primary" disabled={busy}>
          {t('submit')}
        </Button>
      </form>
      <p className="mt-16">
        <Link
          href="/login/reset"
          className="text-body min-h-target inline-flex items-center underline"
        >
          {t('forgot')}
        </Link>
      </p>
    </AuthShell>
  );
}
