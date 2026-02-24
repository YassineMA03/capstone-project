#!/usr/bin/env python3
"""
ScanCode Context Extractor Module - ULTIMATE VERSION
Processes ScanCode JSON output to extract license mentions with context.

SUPPORTS ALL THREE SCANCODE FORMATS:
- ScanCode v32.0+ (files[].license_detections[].matches)
- ScanCode v30.0+ (license_detections[].reference_matches)
- ScanCode v21.x and earlier (files[].licenses)
"""

import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def classify_file_role(path: str) -> str:
    """
    Classify the role/type of a file based on its name and path.
    
    Args:
        path: File path
    
    Returns:
        File role category (license_file, readme, metadata, etc.)
    """
    name = Path(path).name.lower()
    parts = Path(path).parts

    # Check file name patterns
    if name.startswith(("license", "copying")):
        return "license_file"
    if "readme" in name:
        return "readme"
    if name in {"package.json", "metadata.json"}:
        return "metadata"
    if "docs" in parts:
        return "documentation"
    if name.endswith((".py", ".js", ".c", ".cpp", ".java", ".ts", ".go", ".rs")):
        return "source_file"
    
    return "other"


def is_separator(line: str) -> bool:
    """
    Check if a line is a separator (empty, comment, or divider).
    Used to determine where to stop when extracting context.
    
    Args:
        line: Line of text
    
    Returns:
        True if line is a separator
    """
    stripped = line.strip()
    return (
        stripped == "" or
        stripped.startswith("#") or
        stripped.startswith("##") or
        stripped in {"---", "====", "----"}
    )


def extract_context(
    lines: List[str],
    start: int,
    end: int,
    max_before: int = 5,
    max_after: int = 3
) -> Tuple[List[str], List[str]]:
    """
    Extract surrounding context lines before and after a license match.
    Stops at separator lines (empty lines, headers, etc.).
    
    Args:
        lines: All lines from the file
        start: Start line index of the match
        end: End line index of the match
        max_before: Maximum lines to extract before the match
        max_after: Maximum lines to extract after the match
    
    Returns:
        Tuple of (lines_before, lines_after)
    """
    # Extract lines before the match
    before = []
    for i in range(start - 1, max(-1, start - max_before - 1), -1):
        if i < 0 or i >= len(lines):
            break
        if is_separator(lines[i]):
            break
        before.append(lines[i].rstrip())
    before.reverse()  # Put them in forward order

    # Extract lines after the match
    after = []
    for i in range(end, min(len(lines), end + max_after)):
        if is_separator(lines[i]):
            break
        after.append(lines[i].rstrip())

    return before, after


def resolve_file_path(project_root: Path, rel_file: str) -> Optional[Path]:
    """
    Resolve a relative file path to an absolute path.
    Tries multiple common path variations.
    
    Args:
        project_root: Root directory of the project
        rel_file: Relative file path from ScanCode output
    
    Returns:
        Resolved absolute path, or None if file not found
    """
    rel = Path(rel_file)

    # Try different possible locations
    candidates = [
        project_root / rel,                          # Direct child
        project_root.parent / rel,                   # Parent directory
        project_root / Path(*rel.parts[1:]) if len(rel.parts) > 1 else None,  # Skip first part
    ]

    # Return first existing path
    for c in candidates:
        if c and c.exists():
            return c
    
    return None


def process_v32_format(data: dict, project_root: Path, score_threshold: float) -> List[Dict]:
    """
    Process ScanCode v32.0+ format (files[].license_detections[].matches).
    
    In v32, license information is nested under each file, not at the top level.
    
    Args:
        data: Parsed ScanCode JSON
        project_root: Project root directory
        score_threshold: Score threshold for full license text
    
    Returns:
        List of license mention dictionaries
    """
    results = []

    # Process each file
    for file_info in data.get("files", []):
        rel_file = file_info.get("path")
        if not rel_file or file_info.get("type") == "directory":
            continue

        file_path = resolve_file_path(project_root, rel_file)
        if not file_path:
            continue

        # Get SPDX expression from file-level detection
        spdx_expr = file_info.get("detected_license_expression_spdx", "")

        # Process each license detection in this file
        for detection in file_info.get("license_detections", []):
            license_expr = detection.get("license_expression", "")
            
            # Use SPDX from file level if available, otherwise from detection
            if not spdx_expr:
                spdx_expr = license_expr.upper() if license_expr else "Unknown"

            # Process each match within the detection
            for match in detection.get("matches", []):
                start_line = match.get("start_line", 1)
                end_line = match.get("end_line", 1)
                score = match.get("score", 0.0)

                # Read the source file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                except Exception:
                    continue

                # Convert to 0-based indexing
                start = start_line - 1
                end = end_line

                # Extract surrounding context
                context_before, context_after = extract_context(lines, start, end)

                # Decide whether to include matched text
                if score >= score_threshold:
                    license_text_handling = "full_license_text_present"
                    matched_text = None
                else:
                    license_text_handling = "partial_text_included"
                    matched_text = [line.rstrip() for line in lines[start:end]] if end <= len(lines) else []

                # Build structured output
                obj = {
                    "license_name": license_expr if license_expr else "Unknown",
                    "spdx_expression": spdx_expr,
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


def process_v30_format(data: dict, project_root: Path, score_threshold: float) -> List[Dict]:
    """
    Process ScanCode v30.0+ format (license_detections[].reference_matches).
    
    Args:
        data: Parsed ScanCode JSON
        project_root: Project root directory
        score_threshold: Score threshold for full license text
    
    Returns:
        List of license mention dictionaries
    """
    results = []

    # Process each license detection
    for detection in data.get("license_detections", []):
        license_expr = detection.get("license_expression_spdx")

        # Process each reference match within the detection
        for match in detection.get("reference_matches", []):
            rel_file = match["from_file"]
            file_path = resolve_file_path(project_root, rel_file)

            # Skip if we can't find the file
            if not file_path:
                continue

            # Get match details
            start_line = match["start_line"]
            end_line = match["end_line"]
            score = match["score"]

            # Read the source file
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue

            # Convert to 0-based indexing
            start = start_line - 1
            end = end_line

            # Extract surrounding context
            context_before, context_after = extract_context(lines, start, end)

            # Decide whether to include matched text
            if score >= score_threshold:
                license_text_handling = "full_license_text_present"
                matched_text = None
            else:
                license_text_handling = "partial_text_included"
                matched_text = [line.rstrip() for line in lines[start:end]]

            # Build structured output
            obj = {
                "license_name": license_expr.split()[0] if license_expr else "Unknown",
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


def process_v21_format(data: dict, project_root: Path, score_threshold: float) -> List[Dict]:
    """
    Process ScanCode v21.x and earlier format (files[].licenses).
    
    Args:
        data: Parsed ScanCode JSON
        project_root: Project root directory
        score_threshold: Score threshold for full license text
    
    Returns:
        List of license mention dictionaries
    """
    results = []

    # Process each file
    for file_info in data.get("files", []):
        rel_file = file_info.get("path")
        if not rel_file:
            continue

        file_path = resolve_file_path(project_root, rel_file)
        if not file_path:
            continue

        # Process each license in the file
        for license_info in file_info.get("licenses", []):
            # Get license details
            license_key = license_info.get("key", "unknown")
            spdx_key = license_info.get("spdx_license_key", license_key.upper())
            license_name = license_info.get("name", spdx_key)
            score = license_info.get("score", 0.0)
            start_line = license_info.get("start_line", 1)
            end_line = license_info.get("end_line", 1)

            # Read the source file
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue

            # Convert to 0-based indexing
            start = start_line - 1
            end = end_line

            # Extract surrounding context
            context_before, context_after = extract_context(lines, start, end)

            # Decide whether to include matched text
            if score >= score_threshold:
                license_text_handling = "full_license_text_present"
                matched_text = None
            else:
                license_text_handling = "partial_text_included"
                matched_text = [line.rstrip() for line in lines[start:end]] if end <= len(lines) else []

            # Build structured output
            obj = {
                "license_name": license_name,
                "spdx_expression": spdx_key,
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


def detect_scancode_format(data: dict) -> str:
    """
    Detect which ScanCode format is being used.
    
    Args:
        data: Parsed ScanCode JSON
    
    Returns:
        Format version: "v32", "v30", "v21", or "unknown"
    """
    # Check for v32 format: files with license_detections containing matches
    if "files" in data:
        for file_info in data.get("files", []):
            if "license_detections" in file_info:
                for detection in file_info.get("license_detections", []):
                    if "matches" in detection:
                        return "v32"
    
    # Check for v30 format: top-level license_detections with reference_matches
    if "license_detections" in data:
        for detection in data.get("license_detections", []):
            if "reference_matches" in detection:
                return "v30"
    
    # Check for v21 format: files with licenses array
    if "files" in data:
        for file_info in data.get("files", []):
            if "licenses" in file_info:
                return "v21"
    
    return "unknown"


def extract_license_context_json(
    scancode_json_path: str,
    project_root: str,
    score_threshold: float = 99.0,
) -> List[Dict]:
    """
    Extract license mentions with context from ScanCode JSON output.
    Main entry point for this module.
    
    SUPPORTS ALL SCANCODE FORMATS:
    - v32.0+ (files[].license_detections[].matches)
    - v30.0+ (license_detections[].reference_matches)
    - v21.x and earlier (files[].licenses)
    
    Automatically detects which format is being used.
    
    Args:
        scancode_json_path: Path to ScanCode JSON output file
        project_root: Root directory of the scanned project
        score_threshold: Score above which we consider it full license text
                        (99.0+ means exact standard license match)
    
    Returns:
        List of license mention dictionaries with context
    """
    scancode_json_path = Path(scancode_json_path)
    project_root = Path(project_root)

    # Load ScanCode results
    with open(scancode_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Detect format
    format_version = detect_scancode_format(data)
    
    # Process based on detected format
    if format_version == "v32":
        print("   Detected ScanCode v32.0+ format (files[].license_detections[].matches)")
        results = process_v32_format(data, project_root, score_threshold)
    elif format_version == "v30":
        print("   Detected ScanCode v30.0+ format (license_detections[].reference_matches)")
        results = process_v30_format(data, project_root, score_threshold)
    elif format_version == "v21":
        print("   Detected ScanCode v21.x format (files[].licenses)")
        results = process_v21_format(data, project_root, score_threshold)
    else:
        print("   ⚠️  Warning: Unknown ScanCode format, no licenses extracted")
        print(f"   JSON keys found: {list(data.keys())}")
        results = []

    return results