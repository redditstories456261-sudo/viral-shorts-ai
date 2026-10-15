// Resumable, chunked file uploader for the /api/upload/* endpoints.
//
// Flow: init -> PUT 5 MB chunks (Content-Range) -> complete with the
// X-Content-Checksum (SHA-256 hex) header. Pause/resume work within a
// session; retry re-syncs with the server's received_bytes before continuing.

import { completeUpload, getUploadStatus, initUpload, uploadChunk } from './api';
import { Sha256 } from './sha256';

export type UploadState = 'idle' | 'hashing' | 'uploading' | 'paused' | 'error' | 'complete';

export interface UploadSnapshot {
  state: UploadState;
  sentBytes: number;
  totalBytes: number;
  error: string | null;
}

export type UploadSnapshotListener = (snapshot: UploadSnapshot) => void;

const DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024;
const HASH_SLICE_SIZE = 8 * 1024 * 1024;
const MAX_CHUNK_ATTEMPTS = 3;

class UploadHalted extends Error {
  constructor() {
    super('Upload halted');
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class ResumableUploader {
  private readonly file: File;
  private readonly listener: UploadSnapshotListener;
  private readonly totalBytes: number;
  private chunkSize = DEFAULT_CHUNK_SIZE;
  private uploadId: string | null = null;
  private storageKey: string | null = null;
  private checksum: string | null = null;
  private sentBytes = 0;
  private state: UploadState = 'idle';
  private error: string | null = null;
  private running = false;
  private paused = false;

  constructor(file: File, listener: UploadSnapshotListener) {
    this.file = file;
    this.listener = listener;
    this.totalBytes = file.size;
  }

  getUploadId(): string | null {
    return this.uploadId;
  }

  getStorageKey(): string | null {
    return this.storageKey;
  }

  private emit(): void {
    this.listener({
      state: this.state,
      sentBytes: this.sentBytes,
      totalBytes: this.totalBytes,
      error: this.error,
    });
  }

  private setState(state: UploadState): void {
    this.state = state;
    this.emit();
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    this.paused = false;
    this.error = null;
    this.emit();
    try {
      if (this.uploadId === null) {
        this.setState('hashing');
        this.checksum = await this.computeChecksum();
        const init = await initUpload({
          filename: this.file.name,
          total_size: this.totalBytes,
          mime_type: this.file.type || 'video/mp4',
        });
        this.uploadId = init.upload_id;
        if (init.chunk_size > 0) this.chunkSize = init.chunk_size;
        const status = await getUploadStatus(this.uploadId);
        this.sentBytes = Math.min(status.received_bytes, this.totalBytes);
      } else if (this.state === 'error') {
        // Re-sync with the server so a retry continues where it left off.
        const status = await getUploadStatus(this.uploadId);
        this.sentBytes = Math.min(status.received_bytes, this.totalBytes);
      }
      await this.pump();
    } catch (err) {
      if (err instanceof UploadHalted) return;
      this.running = false;
      this.error = err instanceof Error ? err.message : 'Upload failed. Please try again.';
      this.setState('error');
    }
  }

  pause(): void {
    if (this.state !== 'hashing' && this.state !== 'uploading') return;
    this.paused = true;
    this.running = false;
    this.setState('paused');
  }

  resume(): void {
    if (this.state !== 'paused') return;
    void this.start();
  }

  retry(): void {
    if (this.state !== 'error') return;
    void this.start();
  }

  abort(): void {
    this.running = false;
    this.paused = true;
    this.uploadId = null;
    this.storageKey = null;
    this.checksum = null;
    this.sentBytes = 0;
    this.error = null;
    this.setState('idle');
  }

  private async pump(): Promise<void> {
    this.setState('uploading');
    while (this.running && !this.paused && this.sentBytes < this.totalBytes) {
      await this.sendNextChunk();
    }
    if (!this.running || this.paused) {
      if (this.paused) this.setState('paused');
      return;
    }
    if (this.uploadId === null) throw new Error('Upload session was lost. Please start over.');
    const done = await completeUpload(this.uploadId, this.checksum ?? '');
    this.storageKey = done.storage_key;
    this.running = false;
    this.setState('complete');
  }

  private async sendNextChunk(): Promise<void> {
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= MAX_CHUNK_ATTEMPTS; attempt++) {
      if (!this.running || this.paused) throw new UploadHalted();
      try {
        const start = this.sentBytes;
        const end = Math.min(start + this.chunkSize, this.totalBytes);
        const chunk = this.file.slice(start, end);
        if (this.uploadId === null) throw new Error('Upload session was lost. Please start over.');
        const res = await uploadChunk(this.uploadId, start, this.totalBytes, chunk);
        this.sentBytes = Math.min(res.received_bytes, this.totalBytes);
        this.emit();
        return;
      } catch (err) {
        if (err instanceof UploadHalted) throw err;
        lastError = err;
        if (attempt < MAX_CHUNK_ATTEMPTS) await delay(900 * attempt);
      }
    }
    throw lastError instanceof Error
      ? lastError
      : new Error('Could not send this part of the video. Check your connection and retry.');
  }

  private async computeChecksum(): Promise<string> {
    const sha = new Sha256();
    let offset = 0;
    while (offset < this.totalBytes) {
      if (!this.running || this.paused) throw new UploadHalted();
      const end = Math.min(offset + HASH_SLICE_SIZE, this.totalBytes);
      const buf = await this.file.slice(offset, end).arrayBuffer();
      sha.update(new Uint8Array(buf));
      offset = end;
    }
    return sha.hex();
  }
}
