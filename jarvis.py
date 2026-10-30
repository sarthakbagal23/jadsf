"""Legacy entry point retained for compatibility. Use edith.py for EDITH.

Text mode (default):      python edith.py           (type + spoken replies)
Talk mode (push-to-talk): python edith.py --talk     (press Enter to speak)
Voice mode (wake word):   python edith.py --voice    (say "EDITH" hands-free)
"""
import argparse

import memory
from brain import ask


def _speak_safe(text):
    """Speak out loud using ElevenLabs if available, falling back to local TTS."""
    try:
        from voice import speak
        speak(text)
    except Exception:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 185)
            voices = engine.getProperty("voices")
            for v in voices:
                if "david" in v.name.lower() or "male" in v.name.lower():
                    engine.setProperty("voice", v.id)
                    break
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass


def text_loop():
    print("EDITH online. Type 'quit' to exit.\n")
    while True:
        try:
            user = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nPowering down.")
            _speak_safe("Powering down, sir.")
            break
        if user.lower() in ("quit", "exit"):
            print("Powering down.")
            _speak_safe("Powering down, sir.")
            break
        if not user:
            continue
        history = memory.recent_history(10)
        messages = [{"role": r, "content": t} for r, t in history]
        messages.append({"role": "user", "content": user})
        reply = ask(messages)
        memory.log("user", user)
        memory.log("assistant", reply)
        print(f"EDITH: {reply}\n")
        _speak_safe(reply)


def talk_loop():
    """Push-to-talk: press Enter → speak → EDITH listens, thinks, speaks back."""
    from voice import listen_once, speak
    print("EDITH online (talk mode). Press Enter to speak, 'quit' to exit.\n")
    speak("EDITH online, sir. Press Enter when you want to talk.")
    while True:
        try:
            cmd = input("[press Enter to talk] ").strip()
        except (EOFError, KeyboardInterrupt):
            speak("Powering down, sir.")
            break
        if cmd.lower() in ("quit", "exit"):
            speak("Powering down, sir.")
            break
        print("Listening...")
        text = listen_once()
        if not text:
            print("(didn't catch that)\n")
            continue
        print(f"you: {text}")
        history = memory.recent_history(10)
        messages = [{"role": r, "content": t} for r, t in history]
        messages.append({"role": "user", "content": text})
        reply = ask(messages)
        memory.log("user", text)
        memory.log("assistant", reply)
        print(f"EDITH: {reply}\n")
        speak(reply)


def main():
    ap = argparse.ArgumentParser(description="EDITH — your own AI assistant")
    ap.add_argument("--voice", action="store_true",
                    help="full voice loop (wake word + mic + speech)")
    ap.add_argument("--talk", action="store_true",
                    help="push-to-talk mode (press Enter to speak, no wake word needed)")
    args = ap.parse_args()
    if args.voice:
        from voice import voice_loop
        voice_loop()
    elif args.talk:
        talk_loop()
    else:
        text_loop()


if __name__ == "__main__":
    main()
