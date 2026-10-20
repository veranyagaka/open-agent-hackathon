
BANNER = r"""
 _   _ _____  _____ _   _  _____
| \ | | ____|X| ____| \ | |/ ____|
|  \| |  _|  | |    |  \| | |  __
| |\  | |___ | |___ | |\  | |__| |
|_| \_|_____| \_____|_| \_|\_____|

           N E X U S   F O R G E
"""


def show_help():
    print(BANNER)
    print("Nexus Forge Alpha")
    print("Scenario-driven analysis and theory generation")

    print("\nUSAGE")
    print("  python run.py help")
    print("  python run.py [OPTIONS]")

    print("\nEXAMPLES")
    print("  python run.py --input input_examples/case1.json")
    print("  python run.py --scenario-seed 42 --plant-cause late_order")
    print(
        '  python run.py --dataset data/generated/default '
        '--facility FAC-017 --commodity "oxytocin 10IU inj" '
        '--month 2026-03'
    )

    print("\nOPTIONS")
    print("  help                  Show this help screen")
    print("  --input PATH          Load a scenario JSON file")
    print("  --scenario-seed INT   Set the scenario seed")
    print("  --plant-cause NAME    Select a scenario cause")
    print("  --dataset PATH        Specify dataset directory")
    print("  --facility ID         Select a facility")
    print("  --commodity NAME      Select a commodity")
    print("  --month YYYY-MM       Select reporting month")

    print("\nNexus Forge | Alpha release")
