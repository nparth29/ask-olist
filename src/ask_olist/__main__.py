"""CLI:  python -m ask_olist "your question" """
import argparse
import sys

from ask_olist import pipeline


def main() -> int:
    parser = argparse.ArgumentParser(prog="ask_olist", description="Ask the Olist database a question in English.")
    parser.add_argument("question", help="your question, in quotes")
    args = parser.parse_args()

    out = pipeline.ask(args.question)

    print("\nANSWER\n" + out["answer"])
    print("\nSQL\n" + out["sql"])
    print("\nASSUMPTIONS")
    for a in out["assumptions"] or ["(none)"]:
        print(f"- {a}")
    if out["rows"]:
        print(f"\nFIRST {len(out['rows'])} ROWS")
        print(" | ".join(out["columns"]))
        for row in out["rows"]:
            print(" | ".join("NULL" if v is None else str(v) for v in row))
    print(f"\n(attempts: {out['attempts']}, latency: {out['latency_s']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
