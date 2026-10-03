/** Number, money and date formatting (DESIGN_SPEC copy rules, ADR-013 item 7). Lakh/crore grouping, plant timezone. */

const indian = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 20 });
const rupees = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatIndianNumber(n: number): string {
  return indian.format(n);
}

/** `paise` is an integer count of paise (money is never a float, ADR-005). */
export function formatInr(paise: number): string {
  const negative = paise < 0;
  const abs = Math.abs(paise);
  const whole = abs % 100 === 0;
  const text = whole ? indian.format(abs / 100) : rupees.format(abs / 100);
  return `${negative ? '-' : ''}₹${text}`;
}

/** "3 Oct 2026" in the given IANA timezone. Parts are assembled by hand so the month never becomes "Sept". */
export function formatDate(isoInstant: string, timeZone: string): string {
  const date = new Date(isoInstant);
  if (Number.isNaN(date.getTime())) return '';
  const parts = new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone,
  }).formatToParts(date);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${pick('day')} ${pick('month')} ${pick('year')}`;
}
