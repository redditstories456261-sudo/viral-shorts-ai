import { useEffect, useRef, useState } from 'react';
import { formatBytes } from '../lib/api';
import { ResumableUploader, type UploadSnapshot } from '../lib/upload';

export interface CompletedUpload {
  uploadId: string;
  storageKey: string;
  file: File;
}

interface UploadCardProps {
  onComplete: (upload: CompletedUpload) => void;
}

const IDLE_SNAPSHOT: UploadSnapshot = { state: 'idle', sentBytes: 0, totalBytes: 0, error: null };

export default function UploadCard({ onComplete }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const uploaderRef = useRef<ResumableUploader | null>(null);
  const onCompleteRef = useRef(onComplete);
  const notifiedRef = useRef(false);
  onCompleteRef.current = onComplete;

  const [file, setFile] = useState<File | null>(null);
  const [snap, setSnap] = useState<UploadSnapshot>(IDLE_SNAPSHOT);

  useEffect(() => {
    return () => {
      uploaderRef.current?.abort();
    };
  }, []);

  const handleFiles = (files: FileList | null) => {
    const picked = files?.[0];
    if (!picked) return;
    if (!picked.type.startsWith('video/')) {
      setFile(null);
      setSnap({ state: 'idle', sentBytes: 0, totalBytes: 0, error: 'That file is not a video. Please choose a video file.' });
      return;
    }
    notifiedRef.current = false;
    uploaderRef.current?.abort();
    const uploader = new ResumableUploader(picked, (s) => {
      setSnap(s);
      if (s.state === 'complete' && !notifiedRef.current) {
        notifiedRef.current = true;
        const uploadId = uploader.getUploadId();
        const storageKey = uploader.getStorageKey();
        if (uploadId && storageKey) {
          onCompleteRef.current({ uploadId, storageKey, file: picked });
        }
      }
    });
    uploaderRef.current = uploader;
    setFile(picked);
    void uploader.start();
  };

  const chooseDifferent = () => {
    uploaderRef.current?.abort();
    uploaderRef.current = null;
    notifiedRef.current = false;
    setFile(null);
    setSnap(IDLE_SNAPSHOT);
    if (inputRef.current) inputRef.current.value = '';
  };

  const percent = snap.totalBytes > 0 ? Math.round((snap.sentBytes / snap.totalBytes) * 100) : 0;
  const active = snap.state === 'hashing' || snap.state === 'uploading';

  const statusLabel =
    snap.state === 'hashing'
      ? 'Preparing upload…'
      : snap.state === 'uploading'
        ? `Uploading… ${percent}%`
        : snap.state === 'paused'
          ? `Paused at ${percent}%`
          : snap.state === 'error'
            ? 'Upload interrupted'
            : snap.state === 'complete'
              ? 'Upload complete'
              : 'Choose a video to begin';

  return (
    <section className="rounded-3xl bg-neutral-900 p-5 shadow-xl ring-1 ring-white/10">
      <h2 className="text-lg font-semibold">Upload your video</h2>
      <p className="mt-1 text-sm text-neutral-400">
        Your video is sent in small pieces, so a shaky connection will not ruin the upload.
      </p>

      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/*"
        className="hidden"
        aria-label="Choose video file"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {!file ? (
        <div className="mt-4">
          {snap.error && (
            <p className="mb-3 rounded-2xl bg-red-500/10 px-4 py-3 text-sm text-red-300 ring-1 ring-red-500/30">
              {snap.error}
            </p>
          )}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="w-full rounded-2xl bg-violet-600 px-6 py-4 text-lg font-bold text-white shadow-lg shadow-violet-600/30 transition hover:bg-violet-500 active:scale-[0.99]"
          >
            Choose video
          </button>
          <p className="mt-2 text-center text-xs text-neutral-500">MP4 works best on Android</p>
        </div>
      ) : (
        <div className="mt-4 rounded-2xl bg-neutral-950/60 p-4 ring-1 ring-white/10">
          <p className="truncate text-sm font-semibold text-neutral-100">{file.name}</p>
          <p className="mt-0.5 text-xs text-neutral-500">{formatBytes(file.size)}</p>

          <div
            className="mt-3 h-3 overflow-hidden rounded-full bg-neutral-800"
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Upload progress"
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 to-pink-500 transition-all duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-sm">
            <span className="text-neutral-300">{statusLabel}</span>
            <span className="font-semibold text-neutral-100">{percent}%</span>
          </div>
          {snap.state === 'error' && snap.error && (
            <p className="mt-2 text-sm text-red-300">{snap.error}</p>
          )}

          <div className="mt-4 flex gap-2">
            {active && (
              <button
                type="button"
                onClick={() => uploaderRef.current?.pause()}
                className="flex-1 rounded-xl bg-neutral-800 px-4 py-3 font-semibold text-neutral-100 transition active:scale-[0.98]"
              >
                Pause
              </button>
            )}
            {snap.state === 'paused' && (
              <button
                type="button"
                onClick={() => uploaderRef.current?.resume()}
                className="flex-1 rounded-xl bg-violet-600 px-4 py-3 font-bold text-white transition active:scale-[0.98]"
              >
                Resume
              </button>
            )}
            {snap.state === 'error' && (
              <button
                type="button"
                onClick={() => uploaderRef.current?.retry()}
                className="flex-1 rounded-xl bg-violet-600 px-4 py-3 font-bold text-white transition active:scale-[0.98]"
              >
                Retry upload
              </button>
            )}
            {snap.state !== 'complete' && (
              <button
                type="button"
                onClick={chooseDifferent}
                className="flex-1 rounded-xl bg-neutral-800 px-4 py-3 font-semibold text-neutral-300 transition active:scale-[0.98]"
              >
                Change video
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
