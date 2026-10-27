"""Voice layer (optional). Text mode works without any of this installed.

Install with:  pip install -r requirements-voice.txt
Wake word needs a free Picovoice key: console.picovoice.ai (free tier),
set as PICOVOICE_ACCESS_KEY in .env.

Pipeline: Porcupine wake word ("Jarvis") -> record until silence ->
faster-whisper STT (local) -> brain -> pyttsx3 TTS (Windows SAPI voice).
"""
import io
import queue
import threading
import time

from config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_VOICE_ID,
    PICOVOICE_ACCESS_KEY,
    WAKE_WORD,
)

SAMPLE_RATE = 16000

# Global flag to immediately halt audio playback on interrupt
_stop_speaking = threading.Event()
_is_speaking = False


def stop_speaking():
    """Immediately kill any ongoing speech output."""
    global _is_speaking
    _stop_speaking.set()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass
    _is_speaking = False


def _speak_elevenlabs(text, oww_model=None):
    """Play speech using ElevenLabs with instant interrupt support."""
    global _is_speaking
    import pygame
    import requests
    import sounddevice as sd
    import numpy as np

    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error ({resp.status_code}): {resp.text}")

    audio_bytes = io.BytesIO(resp.content)
    _stop_speaking.clear()
    _is_speaking = True

    pygame.mixer.music.load(audio_bytes)
    pygame.mixer.music.play()

    # Microphone stream to detect user voice interruption or wake word while speaking
    audio_q = queue.Queue()
    def mic_callback(indata, frames, time_info, status):
        audio_q.put(indata.copy())

    mic_stream = None
    try:
        mic_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                    dtype="int16", blocksize=1280,
                                    callback=mic_callback)
        mic_stream.start()
    except Exception:
        mic_stream = None

    interrupted = False
    voice_frames = 0
    while pygame.mixer.music.get_busy():
        if _stop_speaking.is_set():
            pygame.mixer.music.stop()
            interrupted = True
            break

        # Check mic queue for voice interrupt
        if mic_stream and not audio_q.empty():
            try:
                chunk = audio_q.get_nowait()
                # Check wake word during playback
                if oww_model:
                    pred = oww_model.predict(chunk.flatten())
                    for name, score in pred.items():
                        if score >= 0.20:
                            print("\n[Interrupted by 'Hey Jarvis'!]")
                            pygame.mixer.music.stop()
                            interrupted = True
                            oww_model.reset()
                            break
                if interrupted:
                    break

                # Also detect loud voice interrupt (shouting 'stop' / talking)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32)**2)))
                if rms > 120.0:  # clearly above speaker bleed
                    voice_frames += 1
                    if voice_frames >= 3:  # ~240ms of speech
                        print("\n[Interrupted!]")
                        pygame.mixer.music.stop()
                        interrupted = True
                        break
                else:
                    voice_frames = max(0, voice_frames - 1)
            except queue.Empty:
                pass

        time.sleep(0.04)

    if mic_stream:
        try:
            mic_stream.stop()
            mic_stream.close()
        except Exception:
            pass

    _is_speaking = False
    return interrupted


def _speak_local(text):
    """Fallback to local Windows SAPI voice."""
    global _is_speaking
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 185)
        voices = engine.getProperty("voices")
        for v in voices:
            if "david" in v.name.lower() or "male" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        _is_speaking = True
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass
    finally:
        _is_speaking = False


def speak(text, oww_model=None):
    """Speak text out loud using ElevenLabs or local fallback."""
    stop_speaking()
    if ELEVENLABS_API_KEY:
        try:
            return _speak_elevenlabs(text, oww_model=oww_model)
        except Exception as e:
            print(f"[ElevenLabs TTS note: {e}]")
    _speak_local(text)
    return False


_whisper_model = None

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _whisper_model


def _transcribe(audio):
    model = get_whisper()
    segments, _ = model.transcribe(audio, language="en")
    return " ".join(s.text for s in segments).strip()


def listen_once(max_seconds=10, min_seconds=2):
    """Record from mic until speech finishes. Returns transcribed text."""
    import numpy as np
    import sounddevice as sd

    audio_q = queue.Queue()

    def callback(indata, frames, time_info, status):
        audio_q.put(indata.copy())

    chunks = []
    chunk_seconds = 0.25
    max_chunks = int(max_seconds / chunk_seconds)
    min_chunks = int(min_seconds / chunk_seconds)

    print("Listening (speak now)...", end="", flush=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="float32", blocksize=int(SAMPLE_RATE * chunk_seconds),
                        callback=callback):
        silent_count = 0
        for i in range(max_chunks):
            try:
                data = audio_q.get(timeout=1)
            except queue.Empty:
                break
            chunks.append(data)
            print(".", end="", flush=True)
            rms = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
            # silence threshold lowered for laptop mics
            if rms < 0.003:
                silent_count += 1
            else:
                silent_count = 0

            # Only stop after minimum recording time and at least 1.5s of silence
            if i >= min_chunks and silent_count >= 6:
                break

    print(" done recording.")
    if not chunks:
        return ""
    audio = np.concatenate(chunks).flatten()
    print("Transcribing...")
    text = _transcribe(audio)
    return text


def _wait_for_wake_word(model=None):
    """Block until openWakeWord hears 'Hey Jarvis'."""
    import numpy as np
    from openwakeword.model import Model
    import sounddevice as sd

    oww = model or Model(wakeword_models=["hey_jarvis_v0.1.onnx"], inference_framework="onnx")
    chunk_samples = 1280  # 80ms at 16kHz
    audio_q = queue.Queue()

    def callback(indata, frames, time_info, status):
        audio_q.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=chunk_samples,
                        callback=callback):
        while True:
            pcm = audio_q.get()
            prediction = oww.predict(pcm.flatten())
            for name, score in prediction.items():
                if score >= 0.20:  # sensitive threshold for laptop mic
                    oww.reset()
                    return True


def voice_loop():
    """Full voice loop: wake word ('Hey Jarvis') -> listen -> think -> speak, forever."""
    from brain import ask
    import memory
    from openwakeword.model import Model

    print("[voice] Loading 'Hey Jarvis' wake-word model (openWakeWord)...")
    try:
        oww = Model(wakeword_models=["hey_jarvis_v0.1.onnx"], inference_framework="onnx")
    except Exception as e:
        print(f"[voice] Error loading wake word model: {e}")
        return

    print("[voice] Warming up local speech-to-text (Whisper)...")
    get_whisper()

    print("Listening for 'Hey Jarvis'... (Ctrl+C to stop)")
    speak("JARVIS voice system online. I'm listening.")
    while True:
        try:
            _wait_for_wake_word(oww)
        except (KeyboardInterrupt, EOFError):
            print("\nPowering down.")
            speak("Powering down, sir.")
            break
        except Exception as e:
            print(f"[voice] error: {e}")
            time.sleep(1)
            continue

        print("\n[Wake word detected] Listening...")
        speak("Yes?")
        text = listen_once()
        if not text:
            print("(no speech detected)")
            continue
        print(f"you: {text}")
        history = memory.recent_history(10)
        messages = [{"role": r, "content": t} for r, t in history]
        messages.append({"role": "user", "content": text})
        reply = ask(messages)
        memory.log("user", text)
        memory.log("assistant", reply)
        print(f"JARVIS: {reply}")
        interrupted = speak(reply, oww_model=oww)
        if interrupted:
            print("[Interrupt detected: stopping reply and listening]")
        time.sleep(0.3)
        print("\nListening for 'Hey Jarvis'...")
