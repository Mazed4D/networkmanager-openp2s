import re
import sys
from pathlib import Path

HEADERS = ("vpnuiplugin.h", "settingwidget.h")


def normalize(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return " ".join(text.split())


def main() -> int:
    upstream = Path(sys.argv[1])
    compat = Path(__file__).resolve().parent / "compat"
    failed = False
    for name in HEADERS:
        ours = normalize((compat / name).read_text())
        theirs = normalize((upstream / name).read_text())
        if ours == theirs:
            print(f"{name}: matches")
        else:
            print(f"{name}: DIFFERS from the plasma-nm headers in {upstream}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
