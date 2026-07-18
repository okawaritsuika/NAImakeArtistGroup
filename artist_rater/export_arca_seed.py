import argparse
import json
from pathlib import Path

from arca_style_collector import export_arca_style_seed


def main():
    parser = argparse.ArgumentParser(description="Export metadata-only shared-style seed database.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_arca_style_seed(args.source, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
