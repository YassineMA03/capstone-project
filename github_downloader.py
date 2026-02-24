#!/usr/bin/env python3
"""
GitHub File Downloader Module - FIXED VERSION
Downloads license-related files from GitHub repositories without cloning.

FIX: Added direct file download attempt before using API tree/search.
This fixes issues with large repos like mono/mono where LICENSE exists
but isn't found via tree/search APIs.
"""

import os
import sys
import time
import requests
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_github_token() -> Optional[str]:
    """
    Get GitHub token from environment variables.
    This increases API rate limits from 60 to 5000 requests/hour.
    """
    return os.getenv("GITHUB_TOKEN")


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Parse GitHub URL to extract owner and repository name.
    
    Args:
        url: GitHub repository URL (e.g., https://github.com/owner/repo)
    
    Returns:
        Tuple of (owner, repo_name)
    
    Raises:
        ValueError: If URL format is invalid
    """
    # Remove trailing slash and .git suffix
    url = url.rstrip('/').replace('.git', '')
    
    # Extract owner and repo from URL
    if 'github.com' in url:
        parts = url.split('github.com/')[-1].split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    
    raise ValueError(f"Invalid GitHub URL: {url}")


def get_default_branch(owner: str, repo: str, headers: dict) -> str:
    """
    Get the default branch name of a repository (main, master, etc.).
    
    Args:
        owner: Repository owner
        repo: Repository name
        headers: HTTP headers for API request
    
    Returns:
        Default branch name (defaults to 'main' if unable to determine)
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json().get("default_branch", "main")
    
    return "main"


def try_download_common_files(owner: str, repo: str, branch: str, token: Optional[str] = None) -> Dict[str, str]:
    """
    NEW FUNCTION: Try to download common license files directly.
    This bypasses tree/search API issues for large repos.
    
    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name to download from
        token: Optional GitHub token
    
    Returns:
        Dictionary mapping filename to content (only successful downloads)
    """
    # Common license file names to try
    common_files = [
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "LICENCE",
        "LICENCE.txt",
        "LICENCE.md",
        "README.md",
        "README.txt",
        "README",
        "COPYRIGHT",
        "COPYRIGHT.txt",
        "COPYING",
        "COPYING.txt",
        "PATENTS",
        "PATENTS.txt",
    ]
    
    found_files = {}
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    
    print(f"🔍 Attempting direct download of common license files...")
    
    for filename in common_files:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                found_files[filename] = response.text
                print(f"  ✓ Found {filename}")
        except Exception:
            # Silently skip files that don't exist
            pass
    
    if found_files:
        print(f"  📄 Downloaded {len(found_files)} files directly")
    
    return found_files


def get_repo_tree(owner: str, repo: str, token: Optional[str] = None) -> List[Dict]:
    """
    Get repository file tree from GitHub API.
    Handles large repositories by falling back to Search API if needed.
    
    Args:
        owner: Repository owner
        repo: Repository name
        token: Optional GitHub personal access token
    
    Returns:
        List of file/directory objects from GitHub tree
    """
    # Prepare headers with authentication if token provided
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"📡 Fetching repository structure from GitHub API...")

    # Get the actual default branch name
    branch = get_default_branch(owner, repo, headers)
    print(f"   Branch: {branch}")

    # Request the full repository tree recursively
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=headers)

    # Handle various error cases
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

    # If tree is truncated (>100k files), use targeted search
    if truncated:
        print(f"   ⚠️  Tree truncated (large repo). Using Search API fallback...")
        tree = search_license_files_via_api(owner, repo, headers)
    
    return tree


def search_license_files_via_api(owner: str, repo: str, headers: dict) -> List[Dict]:
    """
    Fallback for huge repos: search GitHub for license files only.
    Used when the tree API returns truncated results.
    
    Args:
        owner: Repository owner
        repo: Repository name
        headers: HTTP headers for API request
    
    Returns:
        List of found license-related files
    """
    # Search terms for license-related files
    search_terms = ["license", "licence", "readme", "copyright", "copying", "patent"]
    found = {}  # path -> item, deduplicated

    for term in search_terms:
        # Search for files matching the term
        url = f"https://api.github.com/search/code?q=filename:{term}+repo:{owner}/{repo}&per_page=20"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            items = response.json().get("items", [])
            for item in items:
                path = item.get("path", "")
                # Only keep files that match our strict filter
                if path and is_license_related_file(path) and path not in found:
                    found[path] = {"path": path, "type": "blob"}
        elif response.status_code == 403:
            print(f"   ⚠️  Search API rate limited, using partial results")
            break

        # Small delay to avoid rate limiting
        time.sleep(0.5)

    print(f"   Found {len(found)} files via Search API")
    return list(found.values())


def is_license_related_file(path: str) -> bool:
    """
    Check if a file is license-related based on its name.
    Only matches root-level LICENSE, README, COPYRIGHT, COPYING, and PATENT files.
    
    Args:
        path: File path
    
    Returns:
        True if file is license-related
    """
    # Only check files in the root directory
    if '/' in path:
        return False
    
    name = Path(path).name.lower()
    
    # Match files starting with these keywords
    return (
        name.startswith("license") or
        name.startswith("licence") or
        name.startswith("readme") or
        name.startswith("copyright") or
        name.startswith("copying") or
        name.startswith("patent")
    )


def download_file_content(owner: str, repo: str, path: str, branch: str = "HEAD", token: Optional[str] = None) -> Optional[str]:
    """
    Download a single file's content from GitHub.
    
    Args:
        owner: Repository owner
        repo: Repository name
        path: Path to file within repository
        branch: Branch name (default: HEAD)
        token: Optional GitHub personal access token
    
    Returns:
        File content as string, or None if download failed
    """
    # Use raw.githubusercontent.com for direct file access
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    
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
    """
    Download only license-related files from a GitHub repository.
    Main entry point for the download module.
    
    NEW: Now tries direct download first, then falls back to tree/search API.
    This fixes issues with large repos like mono/mono.
    
    Args:
        owner: Repository owner
        repo: Repository name
        dest_dir: Destination directory to save files
        token: Optional GitHub personal access token
    
    Returns:
        List of paths to successfully downloaded files
    """
    downloaded = []
    
    # Get default branch first
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    branch = get_default_branch(owner, repo, headers)
    
    # STRATEGY 1: Try downloading common files directly (fast, works for large repos)
    direct_files = try_download_common_files(owner, repo, branch, token)
    
    if direct_files:
        print(f"\n💾 Saving directly downloaded files...")
        for filename, content in direct_files.items():
            local_path = dest_dir / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(local_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(content)
            
            downloaded.append(local_path)
            print(f"  ✓ {filename}")
    
    # STRATEGY 2: If direct download found everything, we're done
    # Otherwise, try tree/search API to find additional files
    if len(direct_files) < 4:  # Expect at least LICENSE + README
        print(f"\n🔍 Searching for additional license files via API...")
        
        # Get repository tree
        tree = get_repo_tree(owner, repo, token)
        
        # Filter for license-related files in root directory only
        license_files = [
            item for item in tree 
            if item['type'] == 'blob' and is_license_related_file(item['path'])
        ]
        
        print(f"\n📄 Found {len(license_files)} additional files via tree:")
        for item in license_files:
            filename = item['path']
            # Skip if already downloaded
            if filename in direct_files:
                print(f"  ⊗ {filename} (already downloaded)")
                continue
            
            print(f"  - {filename}")
            content = download_file_content(owner, repo, filename, branch, token)
            
            if content:
                local_path = dest_dir / filename
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(local_path, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(content)
                
                downloaded.append(local_path)
                print(f"    ✓ Downloaded")
            else:
                print(f"    ✗ Failed")
    
    if not downloaded:
        print("❌ No license files found in repository")
        return []
    
    print(f"\n✅ Total downloaded: {len(downloaded)} files")
    return downloaded