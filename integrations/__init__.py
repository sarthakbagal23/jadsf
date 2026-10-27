"""Plugin loader: every integration is optional.

A missing key or library skips that plugin with a note — the core still
works. Discord runs as its own bot (integrations/discord_bot.py), not
through this loader.
"""


def get_integration_tools():
    tools = []
    for name in ("personal", "school", "notion", "spotify", "github", "google", "computer", "browser"):
        try:
            mod = __import__(f"integrations.{name}", fromlist=["TOOLS"])
            mod_tools = getattr(mod, "TOOLS", [])
            if mod_tools:
                tools.extend(mod_tools)
                print(f"[plugins] {name}: {len(mod_tools)} tools loaded")
        except Exception as e:
            print(f"[plugins] {name}: skipped ({e})")
    return tools
