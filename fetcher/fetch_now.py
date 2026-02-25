from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.db import connect, init_schema
from fetcher.service import run_fetch_cycle


def main() -> None:
    connection = connect()
    init_schema(connection)
    connection.close()
    run_fetch_cycle()


if __name__ == "__main__":
    main()
