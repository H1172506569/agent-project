from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repopilot.evaluation.large_file_tail import main


if __name__ == "__main__":
    raise SystemExit(main())
