'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';

import { AuthShell } from '@/components/auth-shell';
import { Button, buttonClass } from '@/components/button';
import { TextField } from '@/components/field';
import { ProblemAlert } from '@/components/problem-alert';
import { Alert } from '@/components/states';
import { apiPost, ApiError } from '@/lib/api';

type Stage = 'request' | 'confirm' | 'done';

/** Password reset by emailed code (A-93). The answer to "send a code" is the same for every email. */
export default function ResetPage() {
  const t = useTranslations('login.reset');
  const [stage, setStage] = useState<Stage>('request');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost('/auth/password-reset/request', { email: email.trim() });
      setStage('confirm');
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null, null));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost('/auth/password-reset/confirm', {
        email: email.trim(),
        otp: code.trim(),
        new_password: password,
      });
      setStage('done');
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null, null));
    } finally {
      setBusy(false);
    }
  }

  if (stage === 'done') {
    return (
      <AuthShell>
        <h1 className="text-h1 text-ink">{t('title')}</h1>
        <div className="mt-16">
          <Alert tone="info" role="status" title={t('doneTitle')}>
            {t('doneDetail')}
          </Alert>
        </div>
        <Link href="/login" className={`${buttonClass('primary')} mt-16 w-full`}>
          {t('signIn')}
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <h1 className="text-h1 text-ink">{t('title')}</h1>
      <p className="text-body text-muted mt-4">{t('intro')}</p>
      <div className="mt-24 flex flex-col gap-16">
        {error ? <ProblemAlert error={error} /> : null}
        <form onSubmit={send} noValidate className="flex flex-col gap-16">
          <TextField
            label={t('email')}
            type="email"
            autoComplete="username"
            required
            value={email}
            readOnly={stage === 'confirm'}
            onChange={(e) => setEmail(e.target.value)}
          />
          {stage === 'request' ? (
            <Button type="submit" variant="primary" disabled={busy || !email.trim()}>
              {t('send')}
            </Button>
          ) : null}
        </form>
        {stage === 'confirm' ? (
          <>
            <Alert tone="info" role="status">
              {t('sent')}
            </Alert>
            <form onSubmit={confirm} noValidate className="flex flex-col gap-16">
              <TextField
                label={t('code')}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <TextField
                label={t('newPassword')}
                type="password"
                autoComplete="new-password"
                help={t('passwordHelp')}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Button
                type="submit"
                variant="primary"
                disabled={busy || code.trim().length !== 6 || !password}
              >
                {t('set')}
              </Button>
              <Button onClick={() => setStage('request')} variant="ghost">
                {t('resend')}
              </Button>
            </form>
          </>
        ) : (
          <Link href="/login" className="text-body min-h-target inline-flex items-center underline">
            {t('back')}
          </Link>
        )}
      </div>
    </AuthShell>
  );
}
