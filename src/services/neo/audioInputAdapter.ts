export interface AudioDeviceOption {
  deviceId: string;
  label: string;
}

export type CaptureMode = 'vad' | 'manual';

export interface LiveAudioCallbacks {
  onAudioLevel: (level: number) => void;
  onSpeechDetected: (speaking: boolean) => void;
  onAudioSegment: (audioBase64: string, mimeType: string) => void;
  onStatusChange: (active: boolean, error?: string) => void;
}

function selectSupportedMimeType(): string {
  if (typeof MediaRecorder === 'undefined') return 'audio/webm';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ];
  for (const mime of candidates) {
    if (MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return '';
}

async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

export async function listAudioInputDevices(): Promise<AudioDeviceOption[]> {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.enumerateDevices) {
    return [];
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((d) => d.kind === 'audioinput')
    .map((d, index) => ({
      deviceId: d.deviceId,
      label: d.label || `Microphone ${index + 1}`,
    }));
}

/**
 * Real browser microphone capture adapter using Web Audio API (AnalyserNode VAD)
 * and MediaRecorder segments forwarded to Gemini transcription (/api/neo/transcribe).
 */
export class LiveMicrophoneAdapter {
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private rafId: number | null = null;
  private isRunning = false;
  private captureMode: CaptureMode = 'vad';
  private isSpeaking = false;
  private speechStartedAt = 0;
  private lastVoiceAt = 0;
  private callbacks: LiveAudioCallbacks | null = null;
  private mimeType = '';

  isSupported(): boolean {
    return (
      typeof navigator !== 'undefined' &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof MediaRecorder !== 'undefined'
    );
  }

  setCaptureMode(mode: CaptureMode) {
    this.captureMode = mode;
    if (mode === 'manual' && this.recorder && this.recorder.state === 'recording') {
      // Stop any ongoing VAD recording cleanly without discarding unless empty
      this.finishCurrentRecording(false);
    }
  }

  async start(callbacks: LiveAudioCallbacks, deviceId?: string, mode: CaptureMode = 'vad'): Promise<void> {
    if (!this.isSupported()) {
      callbacks.onStatusChange(
        false,
        'Capture microphone non prise en charge par ce navigateur.',
      );
      return;
    }

    this.stop();
    this.callbacks = callbacks;
    this.captureMode = mode;

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      callbacks.onStatusChange(
        false,
        'Accès au microphone refusé. Autorisez le micro dans votre navigateur.',
      );
      return;
    }

    this.mimeType = selectSupportedMimeType();
    this.isRunning = true;

    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.audioCtx = new AudioCtx();
    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 256;
    source.connect(this.analyser);

    const timeDomainData = new Uint8Array(this.analyser.fftSize);
    const SPEECH_THRESHOLD = 0.032;
    const SILENCE_HOLD_MS = 1450;
    const MIN_SPEECH_MS = 550;
    const MAX_SEGMENT_MS = 18000;

    const monitorLoop = () => {
      if (!this.isRunning || !this.analyser) return;

      this.analyser.getByteTimeDomainData(timeDomainData);
      let sumSquares = 0;
      for (let i = 0; i < timeDomainData.length; i += 1) {
        const norm = (timeDomainData[i] - 128) / 128;
        sumSquares += norm * norm;
      }
      const rms = Math.sqrt(sumSquares / timeDomainData.length);
      const displayLevel = Math.min(1, rms * 5.2);
      this.callbacks?.onAudioLevel(displayLevel);

      if (this.captureMode === 'vad') {
        const now = performance.now();
        if (rms >= SPEECH_THRESHOLD) {
          this.lastVoiceAt = now;
          if (!this.isSpeaking) {
            this.isSpeaking = true;
            this.speechStartedAt = now;
            this.callbacks?.onSpeechDetected(true);
            this.beginRecordingSegment();
          } else if (now - this.speechStartedAt >= MAX_SEGMENT_MS) {
            // Flush long continuous speech segment so NÉO analyzes progressively
            this.isSpeaking = false;
            this.callbacks?.onSpeechDetected(false);
            this.finishCurrentRecording(true);
          }
        } else if (this.isSpeaking && now - this.lastVoiceAt >= SILENCE_HOLD_MS) {
          const duration = now - this.speechStartedAt;
          this.isSpeaking = false;
          this.callbacks?.onSpeechDetected(false);
          this.finishCurrentRecording(duration >= MIN_SPEECH_MS);
        }
      }

      this.rafId = requestAnimationFrame(monitorLoop);
    };

    this.rafId = requestAnimationFrame(monitorLoop);
    callbacks.onStatusChange(true);
  }

  startManualRecording(): boolean {
    if (!this.isRunning || !this.stream) return false;
    if (this.recorder && this.recorder.state === 'recording') return false;
    this.isSpeaking = true;
    this.speechStartedAt = performance.now();
    this.callbacks?.onSpeechDetected(true);
    this.beginRecordingSegment();
    return true;
  }

  stopManualRecordingAndSend(): void {
    if (!this.recorder || this.recorder.state !== 'recording') return;
    const duration = performance.now() - this.speechStartedAt;
    this.isSpeaking = false;
    this.callbacks?.onSpeechDetected(false);
    this.finishCurrentRecording(duration >= 350);
  }

  private beginRecordingSegment(): void {
    if (!this.stream || (this.recorder && this.recorder.state === 'recording')) return;
    this.chunks = [];
    const options: MediaRecorderOptions = this.mimeType ? { mimeType: this.mimeType } : {};
    const rec = new MediaRecorder(this.stream, options);
    rec.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) {
        this.chunks.push(ev.data);
      }
    };
    this.recorder = rec;
    rec.start(200);
  }

  private finishCurrentRecording(shouldEmit: boolean): void {
    const rec = this.recorder;
    if (!rec || rec.state !== 'recording') return;
    const activeMime = rec.mimeType || this.mimeType || 'audio/webm';

    rec.onstop = async () => {
      const capturedChunks = [...this.chunks];
      this.chunks = [];
      if (!shouldEmit || capturedChunks.length === 0) return;

      const blob = new Blob(capturedChunks, { type: activeMime });
      if (blob.size < 1200) return;

      const base64 = await blobToBase64(blob);
      this.callbacks?.onAudioSegment(base64, activeMime);
    };

    try {
      rec.stop();
    } catch {
      // ignore recorder stop errors
    }
    this.recorder = null;
  }

  stop(): void {
    this.isRunning = false;
    this.isSpeaking = false;
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.recorder && this.recorder.state === 'recording') {
      try {
        this.recorder.onstop = null;
        this.recorder.stop();
      } catch {
        // ignore
      }
    }
    this.recorder = null;
    this.chunks = [];

    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.analyser = null;
    this.callbacks?.onAudioLevel(0);
    this.callbacks?.onSpeechDetected(false);
    this.callbacks?.onStatusChange(false);
  }
}

export class NeoVoicePlayer {
  private audioEl: HTMLAudioElement | null = null;
  private objectUrl: string | null = null;

  playWavBase64(
    base64Wav: string,
    onEnded?: () => void,
    onError?: (msg: string) => void,
  ): void {
    this.stop();
    try {
      const binary = atob(base64Wav);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      this.objectUrl = url;

      const audio = new Audio(url);
      this.audioEl = audio;
      audio.onended = () => {
        this.cleanupUrl();
        onEnded?.();
      };
      audio.onerror = () => {
        this.cleanupUrl();
        onError?.('Impossible de lire le flux audio généré.');
      };
      audio.play().catch(() => {
        this.cleanupUrl();
        onError?.('Lecture audio bloquée par le navigateur : cliquez pour écouter.');
      });
    } catch {
      onError?.('Décodage du flux audio WAV impossible.');
    }
  }

  stop(): void {
    if (this.audioEl) {
      this.audioEl.pause();
      this.audioEl.currentTime = 0;
      this.audioEl = null;
    }
    this.cleanupUrl();
  }

  private cleanupUrl(): void {
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }
}
