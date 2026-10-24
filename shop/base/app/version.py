"""Current git short SHA of the running code (read from .git without shelling out)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git_short_sha() -> str:
    git = REPO / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1]
            ref_file = git / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:7]
            packed = git / "packed-refs"
            for line in packed.read_text().splitlines():
                if line.endswith(ref):
                    return line.split(" ")[0][:7]
            return "unknown"
        return head[:7]
    except OSError:
        return "unknown"
