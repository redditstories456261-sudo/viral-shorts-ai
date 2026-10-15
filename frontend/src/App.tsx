import { useCallback, useState } from 'react';
import UploadCard, { type CompletedUpload } from './components/UploadCard';
import JobForm, { type JobParams } from './components/JobForm';
import ProgressView from './components/ProgressView';
import ClipCard from './components/ClipCard';
import ErrorView from './components/ErrorView';
import { createJob, deleteJob, type Clip } from './lib/api';

type Phase = 'upload' | 'configure' | 'processing' | 'results';

export default function App() {
  const [phase, setPhase] = useState<Phase>('upload');
  const [uploaded, setUploaded] = useState<CompletedUpload | null>(null);
  const [jobParams, setJobParams] = useState<JobParams | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleUploadComplete = useCallback((info: CompletedUpload) => {
    setUploaded(info);
    setPhase('configure');
  }, []);

  const startJob = async (params: JobParams, previousJobId: string | null) => {
    if (!uploaded) return;
    setBusy(true);
    try {
      if (previousJobId) {
        try {
          await deleteJob(previousJobId);
        } catch {
          // A stale failed job must not block the retry.
        }
      }
      const res = await createJob({
        upload_id: uploaded.uploadId,
        language: params.language,
        num_shorts: params.num_shorts,
        clip_duration_min: params.clip_duration_min,
        clip_duration_max: params.clip_duration_max,
      });
      setJobId(res.job_id);
      setError(null);
      setPhase('processing');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the job. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = (params: JobParams) => {
    setJobParams(params);
    void startJob(params, null);
  };

  const handleRetry = () => {
    if (!jobParams || busy) return;
    void startJob(jobParams, jobId);
  };

  const handleDone = useCallback((found: Clip[]) => {
    setClips(found);
    setPhase('results');
  }, []);

  const handleProgressError = useCallback((message: string) => {
    setError(message);
  }, []);

  const handleStartOver = async () => {
    if (jobId) {
      try {
        await deleteJob(jobId);
      } catch {
        // Resetting the UI must not depend on the delete succeeding.
      }
    }
    setUploaded(null);
    setJobParams(null);
    setJobId(null);
    setClips([]);
    setError(null);
    setBusy(false);
    setPhase('upload');
  };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-white/10 bg-black/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-xl items-center gap-3 px-4 py-3">
          <img src="/icons/icon-192.svg" alt="Viral Shorts AI logo" className="h-9 w-9" />
          <h1 className="text-xl font-black tracking-wide text-neutral-100">
            VIRAL SHORTS <span className="text-violet-400">AI</span>
          </h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-xl space-y-4 px-4 py-5 pb-16">
        {error ? (
          <ErrorView message={error} busy={busy} onRetry={handleRetry} />
        ) : phase === 'upload' ? (
          <UploadCard onComplete={handleUploadComplete} />
        ) : phase === 'configure' && uploaded ? (
          <JobForm
            fileName={uploaded.file.name}
            fileSize={uploaded.file.size}
            busy={busy}
            onGenerate={handleGenerate}
          />
        ) : phase === 'processing' && jobId ? (
          <ProgressView key={jobId} jobId={jobId} onDone={handleDone} onError={handleProgressError} />
        ) : phase === 'results' ? (
          <section className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-neutral-100">
                {clips.length === 1 ? '1 viral short ready' : `${clips.length} viral shorts ready`}
              </h2>
              <button
                type="button"
                onClick={() => void handleStartOver()}
                className="shrink-0 rounded-xl bg-neutral-800 px-4 py-2.5 text-sm font-bold text-neutral-200 ring-1 ring-white/10 transition active:scale-[0.97]"
              >
                New video
              </button>
            </div>
            {clips.length === 0 ? (
              <div className="rounded-3xl bg-neutral-900 p-6 text-center ring-1 ring-white/10">
                <p className="text-sm text-neutral-300">
                  The AI finished but did not find strong moments in this video. Try a longer
                  video or different duration settings.
                </p>
              </div>
            ) : (
              clips.map((clip, i) => <ClipCard key={clip.clip_id} clip={clip} index={i} />)
            )}
          </section>
        ) : null}
      </main>

      <footer className="mx-auto w-full max-w-xl px-4 pb-8 text-center text-xs text-neutral-600">
        Viral Shorts AI · your videos are processed on your own backend
      </footer>
    </div>
  );
}
