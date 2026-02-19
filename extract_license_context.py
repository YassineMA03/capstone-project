import json
from pathlib import Path
import argparse
import re


# -----------------------------
# Helpers
# -----------------------------

def classify_file_role(path: str) -> str:
    name = Path(path).name.lower()

    if name.startswith(("license", "licence", "copying")):
        return "license_file"
    if "readme" in name:
        return "readme"
    if name in {"package.json", "metadata.json", "pyproject.toml", "setup.py", "cargo.toml"}:
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
    """Try to find the actual file given a relative path from ScanCode."""
    rel = Path(rel_file)

    candidates = [
        project_root / rel,
        project_root.parent / rel,
        project_root / Path(*rel.parts[1:]) if len(rel.parts) > 1 else None,
    ]
    
    # Also try stripping leading directory components one by one
    for i in range(len(rel.parts)):
        candidates.append(project_root / Path(*rel.parts[i:]))

    for c in candidates:
        if c and c.exists():
            return c
    return None


def normalize_to_spdx(license_key: str) -> str:
    """
    Convert ScanCode license keys to proper SPDX identifiers.
    ScanCode uses lowercase with hyphens (gpl-2.0), SPDX uses specific casing (GPL-2.0-only).
    """
    if not license_key:
        return "NOASSERTION"
    
    # Common mappings from ScanCode keys to SPDX identifiers
    mappings = {
        # GPL family
        "gpl-1.0": "GPL-1.0-only",
        "gpl-1.0-plus": "GPL-1.0-or-later",
        "gpl-2.0": "GPL-2.0-only",
        "gpl-2.0-plus": "GPL-2.0-or-later",
        "gpl-3.0": "GPL-3.0-only",
        "gpl-3.0-plus": "GPL-3.0-or-later",
        # LGPL family
        "lgpl-2.0": "LGPL-2.0-only",
        "lgpl-2.0-plus": "LGPL-2.0-or-later",
        "lgpl-2.1": "LGPL-2.1-only",
        "lgpl-2.1-plus": "LGPL-2.1-or-later",
        "lgpl-3.0": "LGPL-3.0-only",
        "lgpl-3.0-plus": "LGPL-3.0-or-later",
        # AGPL
        "agpl-3.0": "AGPL-3.0-only",
        "agpl-3.0-plus": "AGPL-3.0-or-later",
        # Apache
        "apache-2.0": "Apache-2.0",
        "apache-1.0": "Apache-1.0",
        "apache-1.1": "Apache-1.1",
        # MIT
        "mit": "MIT",
        "mit-0": "MIT-0",
        # BSD family
        "bsd-2-clause": "BSD-2-Clause",
        "bsd-3-clause": "BSD-3-Clause",
        "bsd-new": "BSD-3-Clause",
        "bsd-simplified": "BSD-2-Clause",
        "bsd-4-clause": "BSD-4-Clause",
        "0bsd": "0BSD",
        # Other common
        "isc": "ISC",
        "mpl-2.0": "MPL-2.0",
        "mpl-1.0": "MPL-1.0",
        "mpl-1.1": "MPL-1.1",
        "cc0-1.0": "CC0-1.0",
        "unlicense": "Unlicense",
        "wtfpl": "WTFPL",
        "zlib": "Zlib",
        "boost-1.0": "BSL-1.0",
        "bsl-1.0": "BSL-1.0",
        "curl": "curl",
        "x11": "X11",
        "x11-lucent": "X11",
        "artistic-2.0": "Artistic-2.0",
        "epl-1.0": "EPL-1.0",
        "epl-2.0": "EPL-2.0",
        "cddl-1.0": "CDDL-1.0",
        "cddl-1.1": "CDDL-1.1",
        # Exceptions
        "universal-foss-exception-1.0": "Universal-FOSS-exception-1.0",
        "classpath-exception-2.0": "Classpath-exception-2.0",
        # Special
        "public-domain": "LicenseRef-Public-Domain",
        "other-permissive": "LicenseRef-Permissive",
        "cmu-computing-services": "LicenseRef-CMU-Computing-Services",
        "rsa-md5": "RSA-MD5",
        "unknown": "NOASSERTION",
    }
    
    key_lower = license_key.lower().strip()
    
    # Check direct mapping
    if key_lower in mappings:
        return mappings[key_lower]
    
    # If it already looks like proper SPDX (has uppercase), return as-is
    if any(c.isupper() for c in license_key):
        return license_key
    
    # For unknown keys, create a properly formatted identifier
    # Convert "some-license-1.0" to "Some-License-1.0" style
    parts = license_key.split("-")
    formatted_parts = []
    for part in parts:
        # Don't capitalize version numbers or common lowercase parts
        if part.replace(".", "").isdigit() or part in ["or", "and", "with", "plus"]:
            formatted_parts.append(part)
        else:
            formatted_parts.append(part.upper())
    
    return "-".join(formatted_parts)


# -----------------------------
# Core extraction logic
# -----------------------------

def extract_license_context_json(
    scancode_json_path: str,
    project_root: str,
    score_threshold: float = 50.0,
    debug: bool = False,
):
    """
    Extract license context from ScanCode JSON output.
    
    ScanCode 32.x structure:
    - files[]: array of scanned files
      - path: relative file path
      - detected_license_expression: overall expression for the file
      - detected_license_expression_spdx: SPDX version
      - license_detections[]: detections in this file
        - license_expression: detected expression
        - license_expression_spdx: SPDX version  
        - matches[]: individual matches
          - score: confidence score (0-100)
          - start_line, end_line: location
          - license_expression, license_expression_spdx
          - matched_text: the actual matched text (requires --license-text flag)
          - rule_identifier: which rule matched
    """
    scancode_json_path = Path(scancode_json_path)
    project_root = Path(project_root)

    with open(scancode_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = []
    
    # Debug: show structure
    if debug:
        print(f"  [DEBUG] Keys in scancode output: {list(data.keys())}")
        print(f"  [DEBUG] Number of files: {len(data.get('files', []))}")
        print(f"  [DEBUG] Top-level license_detections: {len(data.get('license_detections', []))}")

    # ScanCode 32.x: iterate over files array
    for file_entry in data.get("files", []):
        rel_file = file_entry.get("path", "")
        
        # Skip directories
        if file_entry.get("type") == "directory":
            continue
        
        # Get the overall detected expression for this file
        file_license_expr_spdx = file_entry.get("detected_license_expression_spdx", "")
        file_license_expr = file_entry.get("detected_license_expression", "")
        
        file_detections = file_entry.get("license_detections", [])
        
        if debug and file_detections:
            print(f"  [DEBUG] File: {rel_file}")
            print(f"    detected_license_expression: {file_license_expr}")
            print(f"    detected_license_expression_spdx: {file_license_expr_spdx}")
            print(f"    license_detections count: {len(file_detections)}")
        
        # Process each detection in the file
        for detection in file_detections:
            det_license_expr_spdx = detection.get("license_expression_spdx", "")
            det_license_expr = detection.get("license_expression", "")
            
            # Use SPDX version if available, otherwise normalize the regular expression
            license_expr = det_license_expr_spdx or normalize_to_spdx(det_license_expr)
            
            matches = detection.get("matches", [])
            
            if debug:
                print(f"    Detection: {det_license_expr} -> {license_expr}")
                print(f"      matches count: {len(matches)}")
            
            # Process each match within the detection
            for match in matches:
                score = match.get("score", 0)
                
                if debug:
                    print(f"      Match score: {score}, threshold: {score_threshold}")
                
                # Skip low-confidence matches
                if score < score_threshold:
                    if debug:
                        print(f"      Skipped (below threshold)")
                    continue
                
                start_line = match.get("start_line", 1)
                end_line = match.get("end_line", 1)
                matched_text_raw = match.get("matched_text", "")
                
                # Match-level expression (may differ from detection-level)
                match_expr_spdx = match.get("license_expression_spdx", "")
                match_expr = match.get("license_expression", "")
                
                # Prefer most specific SPDX expression available
                final_expr = match_expr_spdx or license_expr or normalize_to_spdx(match_expr)
                
                # Try to resolve the file path and extract context
                file_path = resolve_file_path(project_root, rel_file)
                context_before = []
                context_after = []
                
                if file_path and file_path.exists():
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            lines = f.readlines()
                        
                        start = start_line - 1
                        end = end_line
                        context_before, context_after = extract_context(lines, start, end)
                    except Exception:
                        pass
                
                # Determine how to handle license text
                if score >= 99.0:
                    license_text_handling = "full_license_text_present"
                    matched_text = None
                else:
                    license_text_handling = "partial_text_included"
                    if matched_text_raw:
                        matched_text = matched_text_raw[:1000]
                    else:
                        matched_text = None
                
                # Extract the primary license name
                license_name = final_expr.split()[0] if final_expr else "unknown"
                
                obj = {
                    "license_name": license_name,
                    "spdx_expression": final_expr,
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
                
                if debug:
                    print(f"      ✓ Added: {license_name} (score={score})")
    
    # Fallback: if no matches found in files[], try the old structure
    if not results:
        if debug:
            print("  [DEBUG] No results from files[], trying legacy structure...")
        results = _extract_from_legacy_structure(data, project_root, score_threshold, debug)

    return results


def _extract_from_legacy_structure(
    data: dict, 
    project_root: Path, 
    score_threshold: float,
    debug: bool = False
) -> list:
    """
    Fallback extraction for older ScanCode output format where
    license_detections contains reference_matches directly.
    """
    results = []
    
    for detection in data.get("license_detections", []):
        det_license_expr_spdx = detection.get("license_expression_spdx", "")
        det_license_expr = detection.get("license_expression", "")
        license_expr = det_license_expr_spdx or normalize_to_spdx(det_license_expr)
        
        ref_matches = detection.get("reference_matches", [])
        
        if debug:
            print(f"  [LEGACY] Detection: {det_license_expr} -> {license_expr}")
            print(f"    reference_matches count: {len(ref_matches)}")

        for match in ref_matches:
            rel_file = match.get("from_file", "")
            file_path = resolve_file_path(project_root, rel_file)

            if not file_path:
                if debug:
                    print(f"    Could not resolve file: {rel_file}")
                continue

            start_line = match.get("start_line", 1)
            end_line = match.get("end_line", 1)
            score = match.get("score", 0)
            
            if score < score_threshold:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                start = start_line - 1
                end = end_line
                context_before, context_after = extract_context(lines, start, end)
            except Exception:
                context_before, context_after = [], []
                lines = []

            if score >= 99.0:
                license_text_handling = "full_license_text_present"
                matched_text = None
            else:
                license_text_handling = "partial_text_included"
                matched_text = [l.rstrip() for l in lines[start:end]] if lines else None

            license_name = license_expr.split()[0] if license_expr else "unknown"

            obj = {
                "license_name": license_name,
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
            
            if debug:
                print(f"    ✓ Added: {license_name} (score={score})")

    return results


# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract license context from ScanCode JSON output"
    )
    parser.add_argument(
        "--project",
        action="append",
        nargs=2,
        metavar=("SCANCODE_JSON", "PROJECT_ROOT"),
        required=True,
        help="Pair: scancode.json path + project root",
    )
    parser.add_argument("--out", default="licenses_context.json")
    parser.add_argument(
        "--threshold",
        type=float,
        default=50.0,
        help="Minimum match score to include (default: 50.0)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug information"
    )

    args = parser.parse_args()

    all_results = []

    for json_path, root in args.project:
        print(f"Processing {root}...")
        all_results.extend(
            extract_license_context_json(json_path, root, args.threshold, args.debug)
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"✓ License context extracted to {args.out}")
    print(f"  Found {len(all_results)} license mentions")