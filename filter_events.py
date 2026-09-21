#!/usr/bin/env python3
import json
import sys

LEVELS = ["critical", "warn", "info"]
COLORS = {"critical": "\033[1;31m", "warn": "\033[33m", "info": "\033[2m"}
NAMES = {"critical": "критичных", "warn": "предупреждений", "info": "информационных"}
RESET = "\033[0m"


def ask():
    print("Что показать?  1 - critical, 2 - warn, 3 - info, 4 - всё, q - выход")
    raw = input("> ").split()
    if "q" in raw:
        return None
    if "4" in raw:
        return LEVELS
    picked = [LEVELS[int(x) - 1] for x in raw if x in ("1", "2", "3")]
    return picked or ["critical"]


def show(events, levels):
    shown = [e for e in events if e["level"] in levels]
    print(f"\nevents.json: {len(events)} событий, показываю {', '.join(levels)}\n")
    for i, e in enumerate(shown, 1):
        lvl = e["level"]
        print(f"{i:>3}. {COLORS[lvl]}{lvl:<8}{RESET} {e['event']}")

    print()
    for lvl in levels:
        print(f"{NAMES[lvl]} {sum(e['level'] == lvl for e in shown)}")
    print(f"скрыто {len(events) - len(shown)}")


def main():
    args = sys.argv[1:]
    with open("events.json", encoding="utf-8") as f:
        events = json.load(f)

    if args:
        levels = LEVELS if "all" in args else [a for a in args if a in LEVELS]
        if not levels:
            sys.exit("уровни: " + ", ".join(LEVELS) + ", all")
        show(events, levels)
        return

    while True:
        levels = ask()
        if levels is None:
            break
        show(events, levels)
        print("\nEnter - назад в меню, q - выход")
        if input("> ").strip() == "q":
            break
        print()


if __name__ == "__main__":
    main()
