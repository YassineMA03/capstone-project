#!/usr/bin/env python3
"""
Capstone License Analyzer - Lightweight Version
Downloads only license-related files from GitHub (no full clone).
"""

import os
import sys
import json
import tempfile
import shutil
import subprocess
import argparse
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import re
from urllib.parse import urlparse
from dotenv import load_dotenv

# Import the extraction logic
from orchestrator.extract_license_context import extract_license_context_json

# Import LLM API functions
from mistralai import Mistral
from pydantic import BaseModel, Field, ValidationError


# Load environment variables from .env file
load_dotenv()


# -----------------------------
# Models
# -----------------------------

class LicenseDecision(BaseModel):
    spdx_expression: str
    main_licenses: List[str]
    excluded_licenses: List[str]
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    needs_human_review: bool


# -----------------------------
# LLM Helper Functions
# -----------------------------

def extract_first_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object found in LLM response."""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON found in output.\n" + text[-800:])
    return json.loads(m.group(0))


def safe_join(lines: Any) -> str:
    """Safely join context lines."""
    if not lines:
        return ""
    if isinstance(lines, list):
        return " | ".join(str(x) for x in lines)
    return str(lines)


def clip_text(t: Any, n: int = 700) -> str:
    """Clip text to max length."""
    if t is None:
        return "null"
    s = str(t).strip()
    return s if len(s) <= n else s[:n] + "…"


def build_prompt_from_mentions(repo: str, mentions: List[Dict[str, Any]]) -> str:
    """Build prompt for LLM analysis."""
    candidates = set()
    for m in mentions:
        if m.get("license_name"):
            candidates.add(m["license_name"])
        expr = m.get("spdx_expression")
        if expr:
            for tok in re.split(r"[\s()]+", expr):
                tok = tok.strip()
                if tok and tok not in {"AND", "OR", "WITH"}:
                    candidates.add(tok)

    evidence_blocks = []
    for i, m in enumerate(mentions, start=1):
        evidence_blocks.append(f"""
- E{i}
  license_name: {m.get("license_name")}
  spdx_expression: {m.get("spdx_expression")}
  source_file: {m.get("source_file")}
  file_role: {m.get("file_role")}
  match_score: {m.get("match_score")}
  license_text_handling: {m.get("license_text_handling")}
  matched_text: {clip_text(m.get("matched_text"))}
  context_before: {safe_join(m.get("context_before"))}
  context_after: {safe_join(m.get("context_after"))}
  raw_location: {m.get("raw_location")}
""")

    return f"""
You are a software license compliance labeling assistant.

Interpret each field as follows:

license_name / spdx_expression
- Identify the license being mentioned using SPDX identifiers.
- Composite expressions mean multiple licenses are referenced in that context.

source_file
- The file where the license mention appears. File name/path are important signals.

file_role
- Indicates role/authority of the file (license_file, readme, metadata, documentation, source_file, etc.).
- Mentions in license files and README usually carry more authority than documentation/source.

match_score
- Confidence score of the match. 100 often indicates standard boilerplate.

context_before / context_after
- Nearby lines may express intent, scope, exclusions:
  "This project is licensed under…"
  "Documentation is licensed under…"
  "Except for third-party code…"
  "Not licensed under…"

license_text_handling
- full_license_text_present means the complete standard license exists here but is intentionally omitted because it does not convey intent.
- partial_text_included means matched_text is included because it may contain meaningful context.

matched_text
- Only present when partial/contextual; otherwise null.

raw_location
- For traceability only.

TASK:
Given the evidence items below for repository "{repo}", infer the most probable MAIN license(s) of the repository code.
Also identify licenses that are excluded (documentation-only, third-party-only, or explicitly negated).

Rules:
- Use ONLY SPDX identifiers.
- Choose ONLY among these candidate SPDX IDs: {sorted(candidates)}
- Construct a valid SPDX license expression for the MAIN code license(s).
- If uncertain/contradictory, set needs_human_review=true and confidence<=0.6.
- Output ONLY valid JSON. No markdown. No extra text.

Return JSON keys exactly:
spdx_expression, main_licenses, excluded_licenses, confidence, rationale, needs_human_review

Evidence:
{''.join(evidence_blocks)}
""".strip()


def label_repo_with_mistral(
    repo: str,
    mentions: List[Dict[str, Any]],
    api_key: str,
    model_name: str = "mistral-small-latest",
    temperature: float = 0.0,
    max_tokens: int = 600
) -> Dict[str, Any]:
    """Analyze license mentions using Mistral LLM."""
    
    prompt = build_prompt_from_mentions(repo, mentions)

    client = Mistral(api_key=api_key)
    res = client.chat.complete(
        model=model_name,
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    content = res.choices[0].message.content
    data = extract_first_json(content)

    try:
        decision = LicenseDecision(**data)
    except ValidationError as e:
        raise ValueError(f"Schema validation failed:\n{e}\n\nParsed JSON:\n{data}\n\nRaw output:\n{content}")

    return decision.model_dump()


# -----------------------------
# GitHub API Functions
# -----------------------------

def parse_github_url(url: str) -> tuple[str, str]:
    """Parse GitHub URL to extract owner and repo name."""
    # Remove .git suffix if present
    url = url.rstrip('/').replace('.git', '')
    
    # Handle different URL formats
    if 'github.com' in url:
        parts = url.split('github.com/')[-1].split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    
    raise ValueError(f"Invalid GitHub URL: {url}")


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment variables."""
    return os.getenv("GITHUB_TOKEN")


def get_default_branch(owner: str, repo: str, headers: dict) -> str:
    """Get the default branch name of a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("default_branch", "main")
    return "main"


def get_repo_tree(owner: str, repo: str, token: Optional[str] = None) -> List[Dict]:
    """Get repository file tree from GitHub API.
    
    Handles:
    - Correct default branch detection (main/master/etc.)
    - Truncated responses for large repos (uses Search API fallback)
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 Fetching repository structure from GitHub API...")

    # Step 1: Get the real default branch (avoids HEAD ambiguity)
    branch = get_default_branch(owner, repo, headers)
    print(f"   Branch: {branch}")

    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=headers)

    if response.status_code == 404:
        print(f"❌ Repository not found: {owner}/{repo}")
        sys.exit(1)
    elif response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining", "?")
        print(f"❌ API rate limit exceeded (remaining: {remaining}).")
        print(f"   Add GITHUB_TOKEN to .env for higher limits.")
        sys.exit(1)
    elif response.status_code != 200:
        print(f"❌ GitHub API error {response.status_code}: {response.text[:200]}")
        sys.exit(1)

    data = response.json()
    tree = data.get("tree", [])
    truncated = data.get("truncated", False)

    # Step 2: If truncated (>100k files), fall back to targeted Search API
    if truncated:
        print(f"   ⚠️  Tree truncated (large repo). Using Search API fallback...")
        tree = search_license_files_via_api(owner, repo, headers)
    
    return tree


def search_license_files_via_api(owner: str, repo: str, headers: dict) -> List[Dict]:
    """Fallback for huge repos: search GitHub for license, readme, copyright files only."""
    search_terms = ["license", "licence", "readme", "copyright"]

    found = {}  # path -> item, deduplicated

    for term in search_terms:
        url = f"https://api.github.com/search/code?q=filename:{term}+repo:{owner}/{repo}&per_page=20"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            items = response.json().get("items", [])
            for item in items:
                path = item.get("path", "")
                # Apply the same strict filter as is_license_related_file
                if path and is_license_related_file(path) and path not in found:
                    found[path] = {"path": path, "type": "blob"}
        elif response.status_code == 403:
            print(f"   ⚠️  Search API rate limited, using partial results")
            break

        # Search API has a stricter rate limit — small delay
        time.sleep(0.5)

    print(f"   Found {len(found)} files via Search API")
    return list(found.values())


def is_license_related_file(path: str) -> bool:
    """Return True only for LICENSE, README, and COPYRIGHT files."""
    name = Path(path).name.lower()

    # Only match files whose name starts with one of these three keywords
    return (
        name.startswith("license")
        or name.startswith("licence")
        or name.startswith("readme")
        or name.startswith("copyright")
    )


def download_file_content(owner: str, repo: str, path: str, token: Optional[str] = None) -> Optional[str]:
    """Download file content from GitHub."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
    
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.text
        return None
    except Exception as e:
        print(f"⚠️  Failed to download {path}: {e}")
        return None


def download_license_files(owner: str, repo: str, dest_dir: Path, token: Optional[str] = None) -> List[Path]:
    """Download only license-related files from GitHub."""
    
    # Get repository tree
    tree = get_repo_tree(owner, repo, token)
    
    # Filter license-related files
    license_files = [
        item for item in tree 
        if item['type'] == 'blob' and is_license_related_file(item['path'])
    ]
    
    print(f"\n📄 Found {len(license_files)} license-related files:")
    for item in license_files:
        print(f"  - {item['path']}")
    
    if not license_files:
        print("❌ No license files found in repository")
        return []
    
    # Download files
    print(f"\n⬇️  Downloading files...")
    downloaded = []
    
    for item in license_files:
        file_path = item['path']
        content = download_file_content(owner, repo, file_path, token)
        
        if content:
            # Create directory structure
            local_path = dest_dir / file_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save file
            with open(local_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(content)
            
            downloaded.append(local_path)
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ Failed: {file_path}")
    
    print(f"\n✓ Downloaded {len(downloaded)} files")
    return downloaded


# -----------------------------
# Scanning Functions
# -----------------------------

def run_scancode(repo_path: Path, output_file: Path, specific_files: List[Path] = None) -> Path:
    """Run ScanCode on specific files or directory."""
    print(f"\n🔍 Running ScanCode analysis...")
    
    try:
        # Always scan the repo directory — ScanCode requires relative paths
        # for multiple inputs, and scanning the directory is simpler & reliable.
        cmd = [
            "scancode",
            "--license",
            "--json-pp", str(output_file),
            str(repo_path)
        ]
        
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        print(f"✓ ScanCode analysis complete")
        return output_file
        
    except subprocess.CalledProcessError as e:
        print(f"✗ ScanCode failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("✗ ScanCode not found. Please install it:", file=sys.stderr)
        print("  pip install scancode-toolkit", file=sys.stderr)
        sys.exit(1)


# -----------------------------
# Output Functions
# -----------------------------

def save_results(results: Dict[str, Any], output_dir: Path, repo_name: str, owner: str = ""):
    """Save analysis results to a per-project folder."""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_label = f"{owner}_{repo_name}" if owner else repo_name
    
    # Create per-project folder
    project_dir = output_dir / project_label
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Save JSON results
    json_file = project_dir / f"analysis_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    
    # Create text report — header + timing only
    txt_file = project_dir / f"report_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"LICENSE ANALYSIS REPORT: {owner}/{repo_name}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        
        if "llm_decision" in results:
            decision = results["llm_decision"]
            f.write("FINAL LICENSE DETERMINATION\n")
            f.write("-" * 60 + "\n")
            f.write(f"SPDX Expression:    {decision.get('spdx_expression', 'N/A')}\n")
            f.write(f"Main Licenses:      {', '.join(decision.get('main_licenses', []))}\n")
            f.write(f"Excluded Licenses:  {', '.join(decision.get('excluded_licenses', [])) or 'None'}\n")
            f.write(f"Confidence:         {decision.get('confidence', 0):.0%}\n")
            f.write(f"Needs Review:       {'Yes' if decision.get('needs_human_review') else 'No'}\n")
            f.write(f"\nRationale:\n{decision.get('rationale', 'N/A')}\n")
        else:
            f.write("No LLM decision available.\n")
        
        # Timing
        timing = results.get("timing", {})
        if timing:
            f.write(f"\n{'=' * 60}\n")
            f.write("TIMING\n")
            f.write(f"-" * 60 + "\n")
            f.write(f"Download:   {timing.get('download_seconds', 0):.1f}s\n")
            f.write(f"ScanCode:   {timing.get('scancode_seconds', 0):.1f}s\n")
            f.write(f"LLM:        {timing.get('llm_seconds', 0):.1f}s\n")
            f.write(f"Total:      {timing.get('total_seconds', 0):.1f}s\n")
    
    # Print to terminal — compact header only
    if "llm_decision" in results:
        decision = results["llm_decision"]
        print(f"\n📋 FINAL LICENSE DETERMINATION")
        print(f"   SPDX Expression:    {decision.get('spdx_expression', 'N/A')}")
        print(f"   Main Licenses:      {', '.join(decision.get('main_licenses', []))}")
        print(f"   Excluded Licenses:  {', '.join(decision.get('excluded_licenses', [])) or 'None'}")
        print(f"   Confidence:         {decision.get('confidence', 0):.0%}")
        print(f"   Needs Review:       {'⚠️  Yes' if decision.get('needs_human_review') else '✓ No'}")
        print(f"\n   Rationale: {decision.get('rationale', 'N/A')}")
    
    print(f"\n💾 Results saved to: {project_dir}/")


# -----------------------------
# Main Pipeline
# -----------------------------

def analyze_repository(
    repo_url: str,
    output_dir: Path,
    api_key: str = None,
    keep_temp: bool = False
):
    """Main pipeline to analyze a repository's licenses (lightweight mode)."""
    
    total_start = time.time()
    
    # Parse GitHub URL
    try:
        owner, repo = parse_github_url(repo_url)
        repo_name = repo
        print(f"🔍 Analyzing: {owner}/{repo}")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Get GitHub token if available
    github_token = get_github_token()
    if github_token:
        print("✓ Using GitHub token for API access")
    else:
        print("ℹ️  No GitHub token found (add GITHUB_TOKEN to .env for higher rate limits)")
    
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp(prefix="capstone_"))
    repo_dir = temp_dir / repo_name
    repo_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # --- Download ---
        dl_start = time.time()
        downloaded_files = download_license_files(owner, repo, repo_dir, github_token)
        dl_elapsed = time.time() - dl_start
        print(f"⏱  Download: {dl_elapsed:.1f}s")
        
        if not downloaded_files:
            print("❌ No license files to analyze")
            sys.exit(1)
        
        # --- ScanCode ---
        sc_start = time.time()
        scancode_output = temp_dir / "scancode_results.json"
        run_scancode(repo_dir, scancode_output, downloaded_files)
        sc_elapsed = time.time() - sc_start
        print(f"⏱  ScanCode: {sc_elapsed:.1f}s")
        
        # Extract license context
        print(f"\n📝 Extracting license context...")
        license_mentions = extract_license_context_json(
            str(scancode_output),
            str(repo_dir),
            score_threshold=99.0
        )
        print(f"✓ Extracted {len(license_mentions)} license mentions")
        
        # LLM analysis (if API key provided)
        results = {
            "repository": repo_url,
            "analyzed_at": datetime.now().isoformat(),
            "files_analyzed": [str(f.relative_to(repo_dir)) for f in downloaded_files],
            "license_mentions": license_mentions
        }
        
        llm_elapsed = 0.0
        if api_key and license_mentions:
            print(f"\n🤖 Analyzing licenses with Mistral AI...")
            llm_start = time.time()
            try:
                llm_decision = label_repo_with_mistral(
                    repo_name,
                    license_mentions,
                    api_key
                )
                results["llm_decision"] = llm_decision
                print(f"✓ LLM analysis complete")
            except Exception as e:
                print(f"⚠️  LLM analysis failed: {e}")
                results["llm_error"] = str(e)
            llm_elapsed = time.time() - llm_start
            print(f"⏱  LLM: {llm_elapsed:.1f}s")
        elif not api_key:
            print("\n⚠️  Skipping LLM analysis (no API key in .env)")
        else:
            print("\n⚠️  No license mentions found for LLM analysis")
        
        total_elapsed = time.time() - total_start
        
        # Store timing info in results
        results["timing"] = {
            "download_seconds": round(dl_elapsed, 1),
            "scancode_seconds": round(sc_elapsed, 1),
            "llm_seconds": round(llm_elapsed, 1),
            "total_seconds": round(total_elapsed, 1),
        }
        
        # Save results
        save_results(results, output_dir, repo_name, owner)
        
        # Print timing summary
        print(f"\n⏱  Total: {total_elapsed:.1f}s  (download {dl_elapsed:.1f}s | scancode {sc_elapsed:.1f}s | llm {llm_elapsed:.1f}s)")
        
    finally:
        # Cleanup
        if not keep_temp:
            shutil.rmtree(temp_dir)
            print(f"🧹 Cleaned up temporary files")
        else:
            print(f"📁 Temporary files kept at: {temp_dir}")


# -----------------------------
# CLI
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Capstone License Analyzer - Lightweight version (downloads only license files)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --link https://github.com/twbs/bootstrap
  %(prog)s --link https://github.com/facebook/react --output ./results
  
Configuration:
  Create a .env file with:
    MISTRAL_API_KEY=your_mistral_key_here
    GITHUB_TOKEN=your_github_token_here (optional, for higher rate limits)
        """
    )
    
    parser.add_argument(
        "--link",
        required=True,
        help="GitHub repository URL to analyze"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="./license_analysis_results",
        help="Output directory for results (default: ./license_analysis_results)"
    )
    
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary downloaded files (for debugging)"
    )
    
    args = parser.parse_args()
    
    # Get API key from .env
    api_key = os.getenv("MISTRAL_API_KEY")
    
    if not api_key:
        print("⚠️  No MISTRAL_API_KEY found in .env file")
        print("   Create a .env file with: MISTRAL_API_KEY=your_key_here")
        print("   Continuing without LLM analysis...\n")
    
    # Run analysis
    analyze_repository(
        repo_url=args.link,
        output_dir=Path(args.output),
        api_key=api_key,
        keep_temp=args.keep_temp
    )


if __name__ == "__main__":
    main()