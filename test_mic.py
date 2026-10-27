import sys, numpy as np, sounddevice as sd
sys.stdout.reconfigure(encoding="utf-8")

print("Testing all input devices...\n")
input_devices = [(i, d) for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
for i, d in input_devices:
    try:
        audio = sd.rec(int(1*16000), samplerate=16000, channels=1, dtype='int16', device=i)
        sd.wait()
        rms = float(np.sqrt(np.mean(audio.astype(np.float32)**2)))
        print(f"  Device {i:2d}: {d['name'][:50]} -> RMS {rms:.1f} {'<-- WORKING' if rms > 50 else ''}")
    except Exception as e:
        print(f"  Device {i:2d}: {d['name'][:50]} -> ERROR: {e}")
