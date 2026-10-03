/** Indeterminate progress: the server does not report a percentage, so the bar only says "working". */
export function Progress({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-8">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuetext={label}
        className="bg-line-soft rounded-pill h-8 w-full overflow-hidden"
      >
        <div className="bg-action rounded-pill h-full w-1/2 animate-pulse" />
      </div>
      <p className="text-body text-muted">{label}</p>
    </div>
  );
}
