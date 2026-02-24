#!/usr/bin/env python3
"""
Capstone License Analyzer - Main Script
Orchestrates the license analysis pipeline for GitHub repositories and local folders.

Pipeline:
1. Download license files from GitHub (or use local files)
2. Run ScanCode to detect licenses
3. Extract license mentions with context
4. Analyze with LLM to determine final license
5. Save results

Usage:
  python main.py --link https://github.com/owner/repo
  python main.py --folder /path/to/local/project
"""

import os
import sys
import json
import time
import shutil
import tempfile
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from dotenv import load_dotenv

# Import our modules
from github_downloader import (
    parse_github_url,
    get_github_token,
    download_license_files
)
from scancode_runner import run_scancode
from license_context_extractor import extract_license_context_json
from llm_analyzer import label_repo_with_mistral

# Load environment variables from .env file
load_dotenv()


# -----------------------------
# Output Functions
# -----------------------------

def save_results(results: Dict[str, Any], output_dir: Path, repo_name: str, owner: str = ""):
    """
    Save analysis results to disk.
    Creates a per-project folder with JSON and text report.
    
    Args:
        results: Complete analysis results dictionary
        output_dir: Base output directory
        repo_name: Repository name
        owner: Repository owner (for GitHub repos)
    """
    # Create timestamped filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_label = f"{owner}_{repo_name}" if owner else repo_name
    
    # Create per-project folder
    project_dir = output_dir / project_label
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Save complete JSON results
    json_file = project_dir / f"analysis_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    
    # Create human-readable text report
    txt_file = project_dir / f"report_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        # Header
        f.write("=" * 60 + "\n")
        f.write(f"LICENSE ANALYSIS REPORT: {owner}/{repo_name}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        
        # LLM decision (if available)
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
        
        # Timing information
        timing = results.get("timing", {})
        if timing:
            f.write(f"\n{'=' * 60}\n")
            f.write("TIMING\n")
            f.write(f"-" * 60 + "\n")
            if "download_seconds" in timing:
                f.write(f"Download:   {timing.get('download_seconds', 0):.1f}s\n")
            f.write(f"ScanCode:   {timing.get('scancode_seconds', 0):.1f}s\n")
            f.write(f"LLM:        {timing.get('llm_seconds', 0):.1f}s\n")
            f.write(f"Total:      {timing.get('total_seconds', 0):.1f}s\n")
    
    # Print summary to terminal
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
# Pipeline Functions
# -----------------------------

def analyze_repository(
    repo_url: str,
    output_dir: Path,
    api_key: str = None,
    keep_temp: bool = False
):
    """
    Analyze a GitHub repository's licenses.
    
    Pipeline:
    1. Parse GitHub URL
    2. Download license files via API
    3. Run ScanCode
    4. Extract context
    5. LLM analysis
    6. Save results
    
    Args:
        repo_url: GitHub repository URL
        output_dir: Where to save results
        api_key: Mistral API key (optional)
        keep_temp: Whether to keep temporary files
    """
    total_start = time.time()
    
    # Parse GitHub URL to get owner and repo name
    try:
        owner, repo = parse_github_url(repo_url)
        repo_name = repo
        print(f"🔍 Analyzing: {owner}/{repo}")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Get GitHub token (if available)
    github_token = get_github_token()
    if github_token:
        print("✓ Using GitHub token for API access")
    else:
        print("ℹ️  No GitHub token found (add GITHUB_TOKEN to .env for higher rate limits)")
    
    # Create temporary directory for downloaded files
    temp_dir = Path(tempfile.mkdtemp(prefix="capstone_"))
    repo_dir = temp_dir / repo_name
    repo_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # --- STEP 1: Download ---
        dl_start = time.time()
        downloaded_files = download_license_files(owner, repo, repo_dir, github_token)
        dl_elapsed = time.time() - dl_start
        print(f"⏱  Download: {dl_elapsed:.1f}s")
        
        if not downloaded_files:
            print("❌ No license files to analyze")
            sys.exit(1)
        
        # --- STEP 2: Run ScanCode ---
        sc_start = time.time()
        scancode_output = temp_dir / "scancode_results.json"
        run_scancode(repo_dir, scancode_output, downloaded_files)
        sc_elapsed = time.time() - sc_start
        print(f"⏱  ScanCode: {sc_elapsed:.1f}s")
        
        # --- STEP 3: Extract Context ---
        print(f"\n📝 Extracting license context...")
        license_mentions = extract_license_context_json(
            str(scancode_output),
            str(temp_dir),
            score_threshold=99.0
        )
        print(f"✓ Extracted {len(license_mentions)} license mentions")
        
        # Initialize results
        results = {
            "repository": repo_url,
            "analyzed_at": datetime.now().isoformat(),
            "files_analyzed": [str(f.relative_to(repo_dir)) for f in downloaded_files],
            "license_mentions": license_mentions
        }
        
        # --- STEP 4: LLM Analysis (if API key provided) ---
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
        
        # Calculate total time
        total_elapsed = time.time() - total_start
        
        # Store timing information
        results["timing"] = {
            "download_seconds": round(dl_elapsed, 1),
            "scancode_seconds": round(sc_elapsed, 1),
            "llm_seconds": round(llm_elapsed, 1),
            "total_seconds": round(total_elapsed, 1),
        }
        
        # --- STEP 5: Save Results ---
        save_results(results, output_dir, repo_name, owner)
        
        # Print timing summary
        print(f"\n⏱  Total: {total_elapsed:.1f}s  (download {dl_elapsed:.1f}s | scancode {sc_elapsed:.1f}s | llm {llm_elapsed:.1f}s)")
        
    finally:
        # Cleanup temporary files
        if not keep_temp:
            shutil.rmtree(temp_dir)
            print(f"🧹 Cleaned up temporary files")
        else:
            print(f"📁 Temporary files kept at: {temp_dir}")


def analyze_local_folder(
    folder_path: str,
    output_dir: Path,
    api_key: str = None,
):
    """
    Analyze licenses in a local folder.
    
    Pipeline:
    1. Run ScanCode on folder
    2. Extract context
    3. LLM analysis
    4. Save results
    
    Args:
        folder_path: Path to local folder
        output_dir: Where to save results
        api_key: Mistral API key (optional)
    """
    total_start = time.time()
    
    # Validate folder path
    folder = Path(folder_path).resolve()
    if not folder.is_dir():
        print(f"❌ Not a valid directory: {folder}")
        sys.exit(1)
    
    project_name = folder.name
    print(f"🔍 Analyzing local folder: {folder}")
    
    # --- STEP 1: Run ScanCode ---
    sc_start = time.time()
    scancode_output = folder / "scancode_results.json"
    run_scancode(folder, scancode_output)
    sc_elapsed = time.time() - sc_start
    print(f"⏱  ScanCode: {sc_elapsed:.1f}s")
    
    # --- STEP 2: Extract Context ---
    print(f"\n📝 Extracting license context...")
    license_mentions = extract_license_context_json(
        str(scancode_output),
        str(folder.parent),
        score_threshold=99.0
    )
    print(f"✓ Extracted {len(license_mentions)} license mentions")
    
    # Clean up scancode output from the folder
    scancode_output.unlink(missing_ok=True)
    
    # Initialize results
    results = {
        "repository": str(folder),
        "analyzed_at": datetime.now().isoformat(),
        "license_mentions": license_mentions
    }
    
    # --- STEP 3: LLM Analysis (if API key provided) ---
    llm_elapsed = 0.0
    if api_key and license_mentions:
        print(f"\n🤖 Analyzing licenses with Mistral AI...")
        llm_start = time.time()
        try:
            llm_decision = label_repo_with_mistral(
                project_name,
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
    
    # Calculate total time
    total_elapsed = time.time() - total_start
    
    # Store timing information
    results["timing"] = {
        "scancode_seconds": round(sc_elapsed, 1),
        "llm_seconds": round(llm_elapsed, 1),
        "total_seconds": round(total_elapsed, 1),
    }
    
    # --- STEP 4: Save Results ---
    save_results(results, output_dir, project_name)
    
    # Print timing summary
    print(f"\n⏱  Total: {total_elapsed:.1f}s  (scancode {sc_elapsed:.1f}s | llm {llm_elapsed:.1f}s)")


# -----------------------------
# CLI
# -----------------------------

def main():
    """Main entry point - parse arguments and run analysis."""
    
    parser = argparse.ArgumentParser(
        description="Capstone License Analyzer - Analyze licenses from GitHub repos or local folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --link https://github.com/twbs/bootstrap
  %(prog)s --folder /path/to/my/project
  %(prog)s --link https://github.com/facebook/react --output ./results
  
Configuration:
  Create a .env file with:
    MISTRAL_API_KEY=your_mistral_key_here
    GITHUB_TOKEN=your_github_token_here (optional, for higher rate limits)
        """
    )
    
    # Source: either GitHub link or local folder (mutually exclusive)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--link",
        help="GitHub repository URL to analyze"
    )
    source.add_argument(
        "--folder",
        help="Path to a local folder to scan"
    )
    
    # Output directory
    parser.add_argument(
        "--output", "-o",
        default="./license_analysis_results",
        help="Output directory for results (default: ./license_analysis_results)"
    )
    
    # Keep temporary files (debugging option)
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary downloaded files (for debugging, only with --link)"
    )
    
    args = parser.parse_args()
    
    # Get API key from environment
    api_key = os.getenv("MISTRAL_API_KEY")
    
    if not api_key:
        print("⚠️  No MISTRAL_API_KEY found in .env file")
        print("   Create a .env file with: MISTRAL_API_KEY=your_key_here")
        print("   Continuing without LLM analysis...\n")
    
    # Run appropriate analysis pipeline
    if args.link:
        # GitHub repository analysis
        analyze_repository(
            repo_url=args.link,
            output_dir=Path(args.output),
            api_key=api_key,
            keep_temp=args.keep_temp
        )
    else:
        # Local folder analysis
        analyze_local_folder(
            folder_path=args.folder,
            output_dir=Path(args.output),
            api_key=api_key,
        )


if __name__ == "__main__":
    main()
