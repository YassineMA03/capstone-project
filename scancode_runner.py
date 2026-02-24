#!/usr/bin/env python3
"""
ScanCode Runner Module
Executes ScanCode toolkit to analyze license information in files.
"""

import sys
import subprocess
from pathlib import Path
from typing import List
import json

def run_scancode(repo_path: Path, output_file: Path, specific_files: List[Path] = None) -> Path:
    """
    Run ScanCode license detection on a directory or specific files.
    
    ScanCode is an open-source tool that detects licenses, copyrights,
    and other interesting information in source code files.
    
    Args:
        repo_path: Path to repository directory to scan
        output_file: Path where JSON results should be saved
        specific_files: Optional list of specific files to scan (currently unused,
                       we always scan the full directory for simplicity)
    
    Returns:
        Path to the generated output file
    
    Raises:
        SystemExit: If ScanCode fails or is not installed
    """
    print(f"\n🔍 Running ScanCode analysis...")
    
    try:
        # Build ScanCode command
        # --license: Detect licenses
        # --json-pp: Output pretty-printed JSON
        cmd = [
            "scancode",
            "--license",
            "--json-pp", str(output_file),
            str(repo_path)
        ]
        # Open and read the JSON file
        #with open(str(output_file), "r") as file:
        #    data = json.load(file)

        # Print the whole content
        #print(data)
        
        # Execute ScanCode
        subprocess.run(
            cmd,
            check=True,           # Raise exception on non-zero exit
            capture_output=True,  # Capture stdout/stderr
            text=True            # Return strings instead of bytes
        )
        
        print(f"✓ ScanCode analysis complete")
        return output_file
        
    except subprocess.CalledProcessError as e:
        # ScanCode execution failed
        print(f"✗ ScanCode failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)
        
    except FileNotFoundError:
        # ScanCode not installed
        print("✗ ScanCode not found. Please install it:", file=sys.stderr)
        print("  pip install scancode-toolkit", file=sys.stderr)
        sys.exit(1)
