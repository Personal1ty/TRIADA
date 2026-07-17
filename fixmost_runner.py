import argparse
import sys

from fixmost_client import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
from fixmost_client import call_fixmost
from fixmost_output import extract_json_text, extract_text


SPECIALIZED_INSTRUCTIONS = {
    "summarize-file": (
        "Summarize this source file. "
        "Return responsibilities, key functions, main dependencies, and risks."
    ),
    "summarize-diff": (
        "Summarize this diff. "
        "Return intent, behavior changes, risk areas, and validation suggestions."
    ),
    "extract-endpoints": (
        "Extract all endpoints, methods, auth patterns, and payload shapes. "
        "Group similar routes when useful."
    ),
    "analyze-logs": (
        "Summarize these logs. "
        "Return the likely issue, evidence, and next checks."
    ),
}


def read_text_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def resolve_prompt(args):
    if getattr(args, "prompt", None) is not None:
        return args.prompt
    if getattr(args, "input_file", None):
        return read_text_file(args.input_file)
    return sys.stdin.read()


def resolve_system_prompt(args):
    if getattr(args, "system", None) is not None:
        return args.system
    if getattr(args, "system_file", None):
        return read_text_file(args.system_file)
    return DEFAULT_SYSTEM_PROMPT


def build_specialized_prompt(mode, payload):
    return f"{SPECIALIZED_INSTRUCTIONS[mode]}\n\nINPUT:\n{payload}"


def run_prompt(prompt, system_prompt, json_mode=False):
    payload = call_fixmost(prompt, system_prompt)
    if json_mode:
        return extract_json_text(payload)
    return extract_text(payload)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Delegate low-risk analytical tasks to FixMost / corp-coder."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    handoff_parser = subparsers.add_parser("handoff")
    prompt_group = handoff_parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--input-file")
    handoff_parser.add_argument("--json", action="store_true")
    handoff_parser.add_argument("--system")
    handoff_parser.add_argument("--system-file")

    for command in SPECIALIZED_INSTRUCTIONS:
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--input-file")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "handoff":
            prompt = resolve_prompt(args)
            system_prompt = resolve_system_prompt(args)
            print(run_prompt(prompt, system_prompt, json_mode=args.json))
            return

        payload = resolve_prompt(args)
        prompt = build_specialized_prompt(args.command, payload)
        print(run_prompt(prompt, DEFAULT_SYSTEM_PROMPT, json_mode=False))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
