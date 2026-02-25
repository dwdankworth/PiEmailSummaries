from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.db import initialize_database


def main() -> None:
    initialize_database()


if __name__ == "__main__":
    main()
