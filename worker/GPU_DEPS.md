# GPU / system dependencies (NOT pip-installable here)

These components cannot be bundled in `requirements.txt` and are installed
by the **infra team** in **`Dockerfile.gpu`** (project root `docker/`
directory). The worker code integrates with them through the interfaces
listed below; if any of them is missing at runtime the pipeline raises a
clear error instead of silently degrading.

## 1. NVIDIA GPU drivers + CUDA toolkit
- **Installs in:** `Dockerfile.gpu` (infra-owned), e.g. `FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`
  plus the NVIDIA Container Toolkit on the host so `torch.cuda.is_available()`
  is true inside the container.
- **Integration interface:** `torch.cuda.is_available()`,
  `torch.cuda.get_device_name(0)`, `torch.cuda.get_device_properties(0)`
  in `worker/pipeline/transcribe.py`. Device auto-selects `"cuda"` when
  available, else `"cpu"` (compute_type `float16` on CUDA, `int8` on CPU).
- **If missing:** transcription still runs on CPU (slower); nothing breaks.

## 2. PyTorch CUDA wheel
- **Installs in:** `Dockerfile.gpu` via
  `pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cu121`
  (the default PyPI wheel is CPU-only).
- **Integration interface:** imported as `torch` in
  `worker/pipeline/transcribe.py`.

## 3. ffmpeg system binary (with libass; nvenc for GPU encoding)
- **Installs in:** `Dockerfile.gpu`, e.g. `apt-get install -y ffmpeg` or the
  johnvansickle static build (needed for `h264_nvenc` + `libass`).
- **Integration interface:** invoked via `subprocess` in
  `worker/pipeline/audio.py::extract_audio` and
  `worker/pipeline/render.py::build_ffmpeg_cmd` / `run`.
  Located with `shutil.which("ffmpeg")`; a missing binary raises
  `RuntimeError` with install instructions.
- **Encoder auto-detect:** `render.py` runs `ffmpeg -encoders` at runtime and
  prefers `h264_nvenc` when present, else `libx264` (`VIDEO_CODEC=auto`).

## 4. faster-whisper model weights
- **Not bundled:** downloaded on first use by `faster-whisper` (CTranslate2)
  into `~/.cache/huggingface` (or `HF_HUB_CACHE`). For offline/air-gapped
  hosts, infra should pre-warm the cache in `Dockerfile.gpu`:
  `RUN python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3')"`
  and/or set `WHISPER_MODEL` to a smaller model (`medium`, `small`).
