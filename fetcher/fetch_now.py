from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fetcher.service import run_fetch_cycle


def main() -> None:
    run_fetch_cycle()


if __name__ == "__main__":
    main()
