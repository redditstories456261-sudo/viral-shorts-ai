import { useState } from 'react';
import { formatBytes, type Language } from '../lib/api';

export interface JobParams {
  language: Language;
  num_shorts: number;
  clip_duration_min: number;
  clip_duration_max: number;
}

interface JobFormProps {
  fileName: string;
  fileSize: number;
  busy: boolean;
  onGenerate: (params: JobParams) => void;
}

const DURATIONS = [30, 45, 60, 75, 90] as const;

const LANGUAGES: Array<{ value: Language; label: string }> = [
  { value: 'auto', label: 'Auto Detect' },
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'ur', label: 'Urdu' },
];

const selectClass =
  'mt-2 w-full rounded-2xl bg-neutral-800 px-4 py-3 text-base font-medium text-neutral-100 ring-1 ring-white/10';

export default function JobForm({ fileName, fileSize, busy, onGenerate }: JobFormProps) {
  const [language, setLanguage] = useState<Language>('auto');
  const [numShorts, setNumShorts] = useState(5);
  const [minDuration, setMinDuration] = useState<number>(30);
  const [maxDuration, setMaxDuration] = useState<number>(60);

  const clampShorts = (value: number) => Math.max(1, Math.min(20, value));

  const handleMinChange = (value: number) => {
    setMinDuration(value);
    if (value > maxDuration) setMaxDuration(value);
  };

  const handleMaxChange = (value: number) => {
    setMaxDuration(value);
    if (value < minDuration) setMinDuration(value);
  };

  const handleGenerate = () => {
    onGenerate({
      language,
      num_shorts: clampShorts(numShorts),
      clip_duration_min: minDuration,
      clip_duration_max: maxDuration,
    });
  };

  return (
    <section className="rounded-3xl bg-neutral-900 p-5 shadow-xl ring-1 ring-white/10">
      <h2 className="text-lg font-semibold">How should the AI cut it?</h2>

      <div className="mt-3 flex items-center gap-3 rounded-2xl bg-neutral-950/60 px-4 py-3 ring-1 ring-white/10">
        <svg viewBox="0 0 24 24" className="h-6 w-6 shrink-0 text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-neutral-100">{fileName}</p>
          <p className="text-xs text-neutral-500">{formatBytes(fileSize)} · uploaded</p>
        </div>
      </div>

      <label htmlFor="language" className="mt-5 block text-sm font-semibold text-neutral-300">
        Video language
      </label>
      <select
        id="language"
        value={language}
        onChange={(e) => setLanguage(e.target.value as Language)}
        className={selectClass}
      >
        {LANGUAGES.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </select>

      <span id="shorts-count-label" className="mt-5 block text-sm font-semibold text-neutral-300">
        Number of shorts
      </span>
      <div className="mt-2 flex items-center gap-3" role="group" aria-labelledby="shorts-count-label">
        <button
          type="button"
          aria-label="Fewer shorts"
          onClick={() => setNumShorts((n) => clampShorts(n - 1))}
          disabled={numShorts <= 1}
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-neutral-800 text-2xl font-bold text-neutral-100 ring-1 ring-white/10 transition active:scale-95 disabled:opacity-40"
        >
          −
        </button>
        <div className="flex-1 rounded-2xl bg-neutral-800 py-3 text-center text-xl font-bold ring-1 ring-white/10">
          {numShorts}
        </div>
        <button
          type="button"
          aria-label="More shorts"
          onClick={() => setNumShorts((n) => clampShorts(n + 1))}
          disabled={numShorts >= 20}
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-neutral-800 text-2xl font-bold text-neutral-100 ring-1 ring-white/10 transition active:scale-95 disabled:opacity-40"
        >
          +
        </button>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="min-duration" className="text-sm font-semibold text-neutral-300">
            Min length
          </label>
          <select
            id="min-duration"
            value={minDuration}
            onChange={(e) => handleMinChange(Number(e.target.value))}
            className={selectClass}
          >
            {DURATIONS.map((d) => (
              <option key={d} value={d}>
                {d}s
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="max-duration" className="text-sm font-semibold text-neutral-300">
            Max length
          </label>
          <select
            id="max-duration"
            value={maxDuration}
            onChange={(e) => handleMaxChange(Number(e.target.value))}
            className={selectClass}
          >
            {DURATIONS.map((d) => (
              <option key={d} value={d}>
                {d}s
              </option>
            ))}
          </select>
        </div>
      </div>

      <button
        type="button"
        onClick={handleGenerate}
        disabled={busy}
        className="mt-6 w-full rounded-2xl bg-gradient-to-r from-violet-600 to-pink-600 px-6 py-4 text-lg font-black tracking-wide text-white shadow-lg shadow-violet-600/30 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60"
      >
        {busy ? 'STARTING…' : 'GENERATE VIRAL SHORTS'}
      </button>
    </section>
  );
}
