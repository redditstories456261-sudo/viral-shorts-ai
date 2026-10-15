interface ErrorViewProps {
  message: string;
  busy: boolean;
  onRetry: () => void;
}

export default function ErrorView({ message, busy, onRetry }: ErrorViewProps) {
  return (
    <section className="rounded-3xl bg-red-950/40 p-6 text-center shadow-xl ring-1 ring-red-500/30">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-500/15">
        <svg viewBox="0 0 24 24" className="h-7 w-7 text-red-400" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
      </div>
      <h2 className="mt-3 text-lg font-bold text-neutral-100">Something went wrong</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm text-neutral-300">{message}</p>
      <p className="mt-1 text-xs text-neutral-500">Your uploaded video is kept, so retrying is quick.</p>
      <button
        type="button"
        onClick={onRetry}
        disabled={busy}
        className="mt-5 w-full rounded-2xl bg-violet-600 px-6 py-4 text-lg font-bold text-white shadow-lg shadow-violet-600/30 transition hover:bg-violet-500 active:scale-[0.99] disabled:opacity-60"
      >
        {busy ? 'RETRYING…' : 'RETRY'}
      </button>
    </section>
  );
}
