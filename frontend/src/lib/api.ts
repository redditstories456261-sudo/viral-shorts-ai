// Typed HTTP client for the Viral Shorts AI backend.
//
// The backend base URL comes only from the VITE_API_URL environment variable
// (set at build time). No API keys or secrets are ever used from this client.

const rawBase = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
export const API_BASE: string = rawBase.replace(/\/+$/, '');

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { error?: unknown; message?: unknown };
    if (typeof data.error === 'string' && data.error) return data.error;
    if (typeof data.message === 'string' && data.message) return data.message;
  } catch {
    // The error body was not JSON; fall through to the status text.
  }
  return `Request failed with status ${res.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), init);
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.');
  }
  if (!res.ok) throw new Error(await parseError(res));
  const text = await res.text();
  return (text ? (JSON.parse(text) as T) : undefined) as T;
}

export type Language = 'auto' | 'en' | 'hi' | 'ur';

export interface InitUploadInput {
  filename: string;
  total_size: number;
  mime_type: string;
}

export interface InitUploadResult {
  upload_id: string;
  chunk_size: number;
}

export interface UploadStatusResult {
  received_bytes: number;
  total_size: number;
}

export interface CompleteUploadResult {
  upload_id: string;
  storage_key: string;
}

export interface CreateJobInput {
  upload_id: string;
  language: Language;
  num_shorts: number;
  clip_duration_min: number;
  clip_duration_max: number;
}

export interface CreateJobResult {
  job_id: string;
}

export interface JobProgress {
  job_id: string;
  status: string;
  progress: number;
  current_stage: string;
  error: string | null;
}

export interface Clip {
  clip_id: string;
  title: string;
  hook: string;
  description: string;
  score: number;
  duration: number;
  start_time: number;
  end_time: number;
}

export interface JobClipsResult {
  clips: Clip[];
}

export function initUpload(input: InitUploadInput): Promise<InitUploadResult> {
  return request<InitUploadResult>('/api/upload/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export function uploadChunk(
  uploadId: string,
  offset: number,
  total: number,
  chunk: Blob,
): Promise<{ received_bytes: number }> {
  const end = offset + chunk.size;
  return request<{ received_bytes: number }>(`/api/upload/${uploadId}/chunk?offset=${offset}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/octet-stream',
      'Content-Range': `bytes ${offset}-${end - 1}/${total}`,
    },
    body: chunk,
  });
}

export function getUploadStatus(uploadId: string): Promise<UploadStatusResult> {
  return request<UploadStatusResult>(`/api/upload/${uploadId}/status`);
}

export function completeUpload(uploadId: string, checksumHex: string): Promise<CompleteUploadResult> {
  return request<CompleteUploadResult>(`/api/upload/${uploadId}/complete`, {
    method: 'POST',
    headers: { 'X-Content-Checksum': checksumHex },
  });
}

export function createJob(input: CreateJobInput): Promise<CreateJobResult> {
  return request<CreateJobResult>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export function getJobProgress(jobId: string): Promise<JobProgress> {
  return request<JobProgress>(`/api/jobs/${jobId}/progress`);
}

export function getJobClips(jobId: string): Promise<JobClipsResult> {
  return request<JobClipsResult>(`/api/jobs/${jobId}/clips`);
}

export async function deleteJob(jobId: string): Promise<void> {
  await request<void>(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

/** The backend answers with a 302 redirect to the clip file; usable as a
 *  <video> src and as a download anchor href. */
export function clipDownloadUrl(clipId: string): string {
  return apiUrl(`/api/clips/${clipId}/download`);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}

/** Seconds -> "m:ss", e.g. 75 -> "1:15". */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}
