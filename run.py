
import argparse
import sys

from cli_help import show_help


def build_parser():
    parser = argparse.ArgumentParser(
        description="Nexus Forge Alpha"
    )

    parser.add_argument("--input", help="Scenario JSON path")
    parser.add_argument(
        "--scenario-seed",
        type=int,
        default=42,
    )
    parser.add_argument("--plant-cause")
    parser.add_argument("--dataset")
    parser.add_argument("--facility")
    parser.add_argument("--commodity")
    parser.add_argument("--month")

    return parser


def main():
    args = sys.argv[1:]

    # Display the custom help screen ONLY for this command.
    if args == ["help"]:
        show_help()
        return

    parser = build_parser()
    parsed = parser.parse_args(args)

    # TODO: Pass parsed arguments to the application logic.
    print("Nexus Forge Alpha")
    print(f"Input: {parsed.input}")
    print(f"Seed: {parsed.scenario_seed}")
    print(f"Cause: {parsed.plant_cause}")
    print(f"Dataset: {parsed.dataset}")
    print(f"Facility: {parsed.facility}")
    print(f"Commodity: {parsed.commodity}")
    print(f"Month: {parsed.month}")


if __name__ == "__main__":
    main()
