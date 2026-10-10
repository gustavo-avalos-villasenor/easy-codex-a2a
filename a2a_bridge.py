"""Entry point deliberately named without 'codex'.

This keeps the long-running A2A bridge out of the match set of a broad
``pkill -f codex``.  The worker still invokes Codex only while handling a
request.
"""

from a2a_bridge_codex import main


if __name__ == "__main__":
    main()
