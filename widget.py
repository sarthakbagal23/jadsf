"""Always-on-top desktop widget for Windows (plain Tkinter, no extra installs).

Run:  python widget.py        (or double-click start_widget.bat)
Drag to move, right-click to close. Refreshes every minute; school data
comes from the cache EDITH keeps (so it never blocks), and a background
thread refreshes grades/assignments every 15 minutes.
"""
import threading
import tkinter as tk

BG, FG, DIM, ACC = "#0b1220", "#e2e8f0", "#64748b", "#38bdf8"


def build():
    root = tk.Tk()
    root.title("EDITH")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.93)
    root.configure(bg=BG, padx=14, pady=10)
    root.geometry("+40+40")
    label = tk.Label(root, bg=BG, fg=FG, justify="left", anchor="nw",
                     font=("Consolas", 10), text="EDITH starting...")
    label.pack()

    drag = {}
    root.bind("<ButtonPress-1>", lambda e: drag.update(x=e.x, y=e.y))
    root.bind("<B1-Motion>", lambda e: root.geometry(
        f"+{root.winfo_x() + e.x - drag['x']}+{root.winfo_y() + e.y - drag['y']}"))
    root.bind("<Button-3>", lambda e: root.destroy())
    return root, label


def render(d):
    lines = [f"EDITH   {d['time']}", d["weather"], ""]
    for name, days in d["countdowns"][:3]:
        lines.append(f"{name:<10} {days:>3} days")
    mins = d["study_today_min"]
    act = d["study_active"]
    lines += ["", f"Studied today: {mins} min" + (f"  [timing {act['subject']}]" if act else "")]
    if d["grades"]:
        lines += ["", "GRADES"]
        for g in d["grades"][:8]:
            s = g["score"]
            s = f"{s:.0f}%" if isinstance(s, (int, float)) else str(s)
            lines.append(f"{g['course'][:22]:<22} {s:>5}")
    if d["due"]:
        lines += ["", "DUE SOON"]
        for i in d["due"][:5]:
            lines.append(f"{i['due'][5:10]} {i['title'][:28]}")
    return "\n".join(lines)


def refresh_school():
    try:
        from integrations import school
        school.grades()
        school.upcoming_work(7)
    except Exception as e:
        print(f"[widget] school refresh failed: {e}")


def main():
    import time
    from integrations.personal import dashboard_data
    root, label = build()
    state = {"busy": False}

    def worker():
        try:
            text = render(dashboard_data())
        except Exception as e:
            text = f"EDITH widget error:\n{e}"
        root.after(0, lambda: label.config(text=text))   # UI update back on the Tk thread
        state["busy"] = False

    def tick():
        if not state["busy"]:               # network (weather) must never freeze the window
            state["busy"] = True
            threading.Thread(target=worker, daemon=True).start()
        root.after(60_000, tick)

    def school_loop():                      # daemon thread: closing the widget exits at once
        while True:
            refresh_school()
            time.sleep(15 * 60)

    tick()
    threading.Thread(target=school_loop, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
