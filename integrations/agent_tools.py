"""Plugin shim: loads EDITH's agent tools (browser/laptop control, playbooks) into the chat brain."""
try:
    import playwright  # noqa: F401
except ImportError:
    raise RuntimeError("playwright not installed - pip install playwright && playwright install chromium")

from edith_agent.tools import TOOLS  # noqa: E402,F401
