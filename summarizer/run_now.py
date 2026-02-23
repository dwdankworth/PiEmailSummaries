from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from summarizer.service import run_summarizer_cycle


def main() -> None:
    run_summarizer_cycle(trigger_digest=True)


if __name__ == "__main__":
    main()
