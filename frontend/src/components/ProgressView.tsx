import { useEffect, useRef, useState } from 'react';
import { getJobClips, getJobProgress, type Clip, type JobProgress } from '../lib/api';

interface ProgressViewProps {
  jobId: string;
  onDone: (clips: Clip[]) => void;
  onError: (message: string) => void;
}

interface Stage {
  key: string;
  label: string;
}

// The pipeline's real stages, in order. Stage 0 (Uploading) is always shown
// as done because the upload finished before the job was created.
const STAGES: Stage[] = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'transcribing', label: 'Transcribing' },
  { key: 'findingviralmoments', label: 'Finding viral moments' },
  { key: 'analyzingaudio', label: 'Analyzing audio' },
  { key: 'detectingfaces', label: 'Detecting faces' },
  { key: 'trackingactivespeaker', label: 'Tracking active speaker' },
  { key: 'creating916crop', label: 'Creating 9:16 crop' },
  { key: 'generatingcaptions', label: 'Generating captions' },
  { key: 'renderingshorts', label: 'Rendering Shorts' },
  { key: 'finalizing', label: 'Finalizing' },
];

const DONE_STATUSES = ['completed', 'complete', 'done', 'finished', 'succeeded', 'success'];
const FAILED_STATUSES = ['failed', 'error', 'cancelled', 'canceled'];
const POLL_INTERVAL_MS = 2000;

function normalizeStage(value: string | null | undefined): string {
  return (value ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function isDoneStatus(status: string): boolean {
  return DONE_STATUSES.includes(status.toLowerCase());
}

function isFailedStatus(status: string): boolean {
  return FAILED_STATUSES.includes(status.toLowerCase());
}

function currentStageIndex(progress: JobProgress): number {
  const key = normalizeStage(progress.current_stage);
  if (key) {
    const found = STAGES.findIndex((s) => s.key === key || key.includes(s.key));
    if (found >= 0) return found;
  }
  // Fallback: estimate from the overall percent when the backend stage name
  // does not match the known list.
  const pct = Math.max(0, Math.min(100, Number(progress.progress) || 0));
  const estimated = Math.floor((pct / 100) * STAGES.length);
  return Math.max(1, Math.min(STAGES.length - 1, estimated));
}

function StageIcon({ state }: { state: 'done' | 'active' | 'upcoming' }) {
  if (state === 'done') {
    return (
      <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
      </svg>
    );
  }
  if (state === 'active') {
    return (
      <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 animate-spin text-violet-400" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
        <path strokeLinecap="round" d="M12 3a9 9 0 1 0 9 9" />
      </svg>
    );
  }
  return <span className="h-5 w-5 shrink-0 rounded-full border-2 border-neutral-700" aria-hidden="true" />;
}

export default function ProgressView({ jobId, onDone, onError }: ProgressViewProps) {
  const [latest, setLatest] = useState<JobProgress | null>(null);
  const onDoneRef = useRef(onDone);
  const onErrorRef = useRef(onError);
  onDoneRef.current = onDone;
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const progress = await getJobProgress(jobId);
        if (cancelled) return;
        setLatest(progress);
        if (isDoneStatus(progress.status)) {
          const { clips } = await getJobClips(jobId);
          if (!cancelled) onDoneRef.current(clips);
          return;
        }
        if (isFailedStatus(progress.status)) {
          if (!cancelled) {
            onErrorRef.current(progress.error || 'Video processing failed. Please try again.');
          }
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (!cancelled) {
          onErrorRef.current(err instanceof Error ? err.message : 'Lost connection to the server.');
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const done = latest !== null && isDoneStatus(latest.status);
  const currentIndex = done ? STAGES.length : latest ? currentStageIndex(latest) : 1;
  const percent = latest ? Math.max(0, Math.min(100, Math.round(Number(latest.progress) || 0))) : 0;
  const currentLabel = STAGES[Math.min(currentIndex, STAGES.length - 1)].label;

  return (
    <section className="rounded-3xl bg-neutral-900 p-5 shadow-xl ring-1 ring-white/10">
      <h2 className="text-lg font-semibold">Creating your shorts</h2>
      <p className="mt-1 text-sm text-neutral-400">
        {done
          ? 'Wrapping up…'
          : `Stage ${Math.min(currentIndex + 1, STAGES.length)} of ${STAGES.length}: ${currentLabel}`}
      </p>

      <div
        className="mt-4 h-3 overflow-hidden rounded-full bg-neutral-800"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Overall progress"
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-500 to-pink-500 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mt-2 text-right text-sm font-semibold text-neutral-300">{percent}%</p>

      <ol className="mt-4 space-y-1.5">
        {STAGES.map((stage, i) => {
          const state: 'done' | 'active' | 'upcoming' =
            i === 0 || i < currentIndex ? 'done' : i === currentIndex && !done ? 'active' : 'upcoming';
          return (
            <li
              key={stage.key}
              className={`flex items-center gap-3 rounded-xl px-3 py-2.5 ring-1 transition ${
                state === 'active'
                  ? 'bg-violet-600/15 ring-violet-500/40'
                  : state === 'done'
                    ? 'ring-white/5'
                    : 'opacity-50 ring-white/5'
              }`}
              aria-current={state === 'active' ? 'step' : undefined}
            >
              <StageIcon state={state} />
              <span
                className={`text-sm font-medium ${
                  state === 'active' ? 'text-neutral-100' : 'text-neutral-400'
                }`}
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
