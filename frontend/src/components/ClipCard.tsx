import { useRef, useState } from 'react';
import { clipDownloadUrl, formatClock, type Clip } from '../lib/api';

interface ClipCardProps {
  clip: Clip;
  index: number;
}

function scoreBadge(score: number): string {
  if (score >= 80) return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40';
  if (score >= 60) return 'bg-amber-500/15 text-amber-300 ring-amber-500/40';
  return 'bg-neutral-500/15 text-neutral-300 ring-neutral-500/40';
}

export default function ClipCard({ clip, index }: ClipCardProps) {
  const cardRef = useRef<HTMLElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [sharing, setSharing] = useState(false);
  const [shareNote, setShareNote] = useState<string | null>(null);

  const downloadUrl = clipDownloadUrl(clip.clip_id);
  const fileName = `viral-short-${index + 1}.mp4`;

  const handlePreview = () => {
    cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const player = videoRef.current;
    if (player) {
      player.currentTime = 0;
      const p = player.play();
      if (p) p.catch(() => {});
    }
  };

  const triggerDownload = () => {
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const handleShare = async () => {
    setSharing(true);
    setShareNote(null);
    try {
      const res = await fetch(downloadUrl);
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const blob = await res.blob();
      const file = new File([blob], fileName, { type: blob.type || 'video/mp4' });
      if (
        typeof navigator.share === 'function' &&
        typeof navigator.canShare === 'function' &&
        navigator.canShare({ files: [file] })
      ) {
        await navigator.share({ files: [file], title: clip.title, text: clip.hook });
      } else {
        triggerDownload();
        setShareNote('This device cannot share video files directly, so the short was downloaded instead.');
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // The user dismissed the share sheet; nothing to do.
      } else {
        triggerDownload();
        setShareNote('Sharing hit a snag, so the short was downloaded instead.');
      }
    } finally {
      setSharing(false);
    }
  };

  return (
    <article ref={cardRef} className="scroll-mt-24 rounded-3xl bg-neutral-900 p-4 shadow-xl ring-1 ring-white/10">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-bold text-neutral-100">Short #{index + 1}</h3>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ring-1 ${scoreBadge(clip.score)}`}>
          {clip.score}/100 virality
        </span>
      </div>

      <video
        ref={videoRef}
        src={downloadUrl}
        controls
        playsInline
        preload="metadata"
        className="mt-3 aspect-[9/16] w-full rounded-2xl object-contain"
      />

      <h4 className="mt-3 text-base font-semibold leading-snug text-neutral-100">{clip.title}</h4>
      <p className="mt-1 text-sm text-violet-300">
        <span className="font-semibold">Hook:</span> {clip.hook}
      </p>
      {clip.description ? <p className="mt-2 text-sm text-neutral-400">{clip.description}</p> : null}
      <p className="mt-2 text-xs text-neutral-500">
        Duration {formatClock(clip.duration)} · {formatClock(clip.start_time)} – {formatClock(clip.end_time)} in the original
      </p>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <button
          type="button"
          onClick={handlePreview}
          className="rounded-xl bg-neutral-800 px-3 py-3 text-sm font-bold text-neutral-100 transition active:scale-[0.97]"
        >
          Preview
        </button>
        <a
          href={downloadUrl}
          download={fileName}
          className="rounded-xl bg-violet-600 px-3 py-3 text-center text-sm font-bold text-white transition active:scale-[0.97]"
        >
          Download
        </a>
        <button
          type="button"
          onClick={() => void handleShare()}
          disabled={sharing}
          className="rounded-xl bg-neutral-800 px-3 py-3 text-sm font-bold text-neutral-100 transition active:scale-[0.97] disabled:opacity-60"
        >
          {sharing ? 'Sharing…' : 'Share'}
        </button>
      </div>
      {shareNote && <p className="mt-2 text-xs text-neutral-400">{shareNote}</p>}
    </article>
  );
}
