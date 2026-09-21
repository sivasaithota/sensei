"""Run with: python -m sensei.investment packet.json new-output-directory."""
import argparse
import json
from pathlib import Path
from .cycle import run_cycle, replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet_or_run_directory')
    parser.add_argument('output_directory', nargs='?')
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    if args.replay:
        result = replay(args.packet_or_run_directory)
    else:
        if not args.output_directory:
            parser.error('output_directory is required for a new run')
        result = run_cycle(json.loads(Path(args.packet_or_run_directory).read_text()), args.output_directory)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in ('READY', 'AI_CHOSE_CASH') else 1


if __name__ == '__main__':
    raise SystemExit(main())
