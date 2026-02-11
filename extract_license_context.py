import json
from pathlib import Path
import argparse
import re


# -----------------------------
# Helpers
# -----------------------------

def classify_file_role(path: str) -> str:
    name = Path(path).name.lower()

    if name.startswith(("license", "copying")):
        return "license_file"
    if "readme" in name:
        return "readme"
    if name in {"package.json", "metadata.json"}:
        return "metadata"
    if "docs" in Path(path).parts:
        return "documentation"
    if name.endswith((".py", ".js", ".c", ".cpp", ".java", ".ts", ".go", ".rs")):
        return "source_file"
    return "other"


def is_separator(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped == ""
        or stripped.startswith("#")
        or stripped.startswith("##")
        or stripped in {"---", "====", "----"}
    )


def extract_context(lines, start, end, max_before=5, max_after=3):
    before = []
    for i in range(start - 1, max(-1, start - max_before - 1), -1):
        if is_separator(lines[i]):
            break
        before.append(lines[i].rstrip())
    before.reverse()

    after = []
    for i in range(end, min(len(lines), end + max_after)):
        if is_separator(lines[i]):
            break
        after.append(lines[i].rstrip())

    return before, after


def resolve_file_path(project_root: Path, rel_file: str) -> Path | None:
    rel = Path(rel_file)

    candidates = [
        project_root / rel,
        project_root.parent / rel,
        project_root / Path(*rel.parts[1:]) if len(rel.parts) > 1 else None,
    ]

    for c in candidates:
        if c and c.exists():
            return c
    return None


# -----------------------------
# Core extraction logic
# -----------------------------

def extract_license_context_json(
    scancode_json_path: str,
    project_root: str,
    score_threshold: float = 99.0,
):
    scancode_json_path = Path(scancode_json_path)
    project_root = Path(project_root)

    with open(scancode_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = []

    for detection in data.get("license_detections", []):
        license_expr = detection.get("license_expression_spdx")

        for match in detection.get("reference_matches", []):
            rel_file = match["from_file"]
            file_path = resolve_file_path(project_root, rel_file)

            if not file_path:
                continue

            start_line = match["start_line"]
            end_line = match["end_line"]
            score = match["score"]

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            start = start_line - 1
            end = end_line

            context_before, context_after = extract_context(lines, start, end)

            if score >= score_threshold:
                license_text_handling = "full_license_text_present"
                matched_text = None
            else:
                license_text_handling = "partial_text_included"
                matched_text = [
                    l.rstrip() for l in lines[start:end]
                ]

            obj = {
                "license_name": license_expr.split()[0],
                "spdx_expression": license_expr,
                "source_file": rel_file,
                "file_role": classify_file_role(rel_file),
                "match_score": score,
                "context_before": context_before,
                "context_after": context_after,
                "license_text_handling": license_text_handling,
                "matched_text": matched_text,
                "raw_location": {
                    "start_line": start_line,
                    "end_line": end_line,
                },
            }

            results.append(obj)

    return results


# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        action="append",
        nargs=2,
        metavar=("SCANCODE_JSON", "PROJECT_ROOT"),
        required=True,
        help="Pair: scancode.json path + project root",
    )
    parser.add_argument("--out", default="licenses_context.json")

    args = parser.parse_args()

    all_results = []

    for json_path, root in args.project:
        print(f"Processing {root}...")
        all_results.extend(
            extract_license_context_json(json_path, root)
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"✔ License context extracted to {args.out}")
