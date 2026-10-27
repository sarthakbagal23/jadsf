import sys, os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

# Make sure we run from the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import memory
from brain import ask
from voice import speak, stop_speaking

def text_loop():
    print("=" * 50)
    print("   JARVIS online. Type to talk. 'quit' to exit.")
    print("   (Press Enter on empty line or Ctrl+C to interrupt speech)")
    print("=" * 50 + "\n")
    speak("JARVIS online. Ready when you are.")
    while True:
        try:
            user = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            stop_speaking()
            print("\nPowering down.")
            speak("Powering down, sir.")
            break
        if user.lower() in ("quit", "exit", "bye"):
            stop_speaking()
            print("Powering down.")
            speak("Goodbye, sir.")
            break
        if not user:
            stop_speaking()
            continue
        stop_speaking()
        print("JARVIS: thinking...")
        history = memory.recent_history(10)
        messages = [{"role": r, "content": t} for r, t in history]
        messages.append({"role": "user", "content": user})
        reply = ask(messages)
        memory.log("user", user)
        memory.log("assistant", reply)
        print(f"JARVIS: {reply}\n")
        speak(reply)

if __name__ == "__main__":
    text_loop()
