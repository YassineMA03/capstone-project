# Capstone License Analyzer

A lightweight tool that automatically detects and classifies open-source licenses in any public GitHub repository. It downloads only license-related files (no full clone), scans them with [ScanCode](https://github.com/aboutcode-org/scancode-toolkit), and uses a Mistral AI LLM to produce a final license determination.

## How It Works

1. **Fetch** — Retrieves the repository file tree via the GitHub API and identifies license-related files (LICENSE, README, COPYRIGHT).
2. **Download** — Downloads only those files (typically 5–30 files, even for very large repos).
3. **Scan** — Runs ScanCode to detect every license mention, match score, and location.
4. **Extract** — Builds structured context around each mention (surrounding lines, file role, SPDX expression).
5. **Classify** — Sends the evidence to Mistral AI, which returns a final SPDX expression, confidence score, and list of main vs. excluded licenses.
6. **Clean up** — All temporarily downloaded files are automatically deleted once the analysis is complete. Use `--keep-temp` to preserve them for debugging.

## Quick Start

```bash
# 1. Clone the project
git clone <your-repo-url>
cd capstone-analyzer
```

### If you have Anaconda installed (recommended first step)

Anaconda's Python conflicts with ScanCode's `libmagic` dependency. Run this **before** creating your virtual environment:

```bash
# Exit any active environments
deactivate
conda deactivate

# Remove Anaconda from PATH for this session
export PATH=$(echo "$PATH" | sed 's|/opt/anaconda3/[^:]*:||g')

# Verify you're using system/Homebrew Python
which python3
# Should show /usr/bin/python3 or /opt/homebrew/bin/python3
# Should NOT show /opt/anaconda3/...

# Delete old venv if it exists
rm -rf venv

# Create a clean venv
python3 -m venv venv
source venv/bin/activate
```

### Setup with the setup script (recommended)

```bash
bash setup.sh
source venv/bin/activate
```

The script creates the virtual environment, installs all dependencies, verifies imports, and generates a `.env` template.

### Manual setup (if the setup script fails)

```bash
# Create and activate venv (skip if already done above)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# On macOS, if ScanCode complains about libmagic:
brew install libmagic

# Verify ScanCode works
scancode --version

# Create .env file
cp .env.example .env   # or create it manually (see Configuration below)
```

### Add your API keys and run

```bash
# Edit .env with your keys
nano .env

# Run your first analysis
python capstone_lite.py --link https://github.com/twbs/bootstrap
```

## Configuration (.env)

Create a `.env` file in the project root. The setup script generates one automatically if it doesn't exist.

| Variable          | Required | Description                                                                                                                                                                                                                                        |
| ----------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MISTRAL_API_KEY` | **Yes**  | API key from [Mistral AI](https://console.mistral.ai/). Without it, the tool still runs ScanCode but skips the LLM classification step.                                                                                                            |
| `GITHUB_TOKEN`    | No       | A GitHub personal access token. Not needed for public repos, but raises the API rate limit from 60 to 5,000 requests/hour. Useful when analyzing many repos in a row. Get one at [github.com/settings/tokens](https://github.com/settings/tokens). |

Example `.env`:

```
MISTRAL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Usage

```
python capstone_lite.py --link <GITHUB_URL> [OPTIONS]
python capstone_lite.py --folder <PATH> [OPTIONS]
```

You must provide either `--link` (GitHub URL) or `--folder` (local path), but not both.

### Arguments

| Argument         | Required                      | Default                      | Description                                                             |
| ---------------- | ----------------------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `--link`         | One of `--link` or `--folder` | —                            | GitHub repository URL to analyze (scans root-level license files only). |
| `--folder`       | One of `--link` or `--folder` | —                            | Path to a local folder to scan with ScanCode.                           |
| `--output`, `-o` | No                            | `./license_analysis_results` | Base directory for output. A subfolder is created per project.          |
| `--keep-temp`    | No                            | `false`                      | Keep the temporary downloaded files (only applies to `--link`).         |

### Examples

```bash
# Analyze a GitHub repository
python capstone_lite.py --link https://github.com/facebook/react

# Analyze a local folder
python capstone_lite.py --folder /path/to/my/project

# Custom output directory
python capstone_lite.py --link https://github.com/vuejs/vue --output ./my_results
```

## Output

Results are saved in a **per-project folder** under `license_analysis_results/`:

```
capstone-analyzer/
├── capstone_lite.py
├── extract_license_context.py
└── license_analysis_results/
    ├── facebook_react/
    │   ├── analysis_20250211_143022.json
    │   └── report_20250211_143022.txt
    └── Homebrew_brew/
        ├── analysis_20250211_150112.json
        └── report_20250211_150112.txt
```

### Terminal Output

```
📋 FINAL LICENSE DETERMINATION
   SPDX Expression:    MIT
   Main Licenses:      MIT
   Excluded Licenses:  None
   Confidence:         95%
   Needs Review:       ✓ No

   Rationale: The root LICENSE file contains the full MIT license text with a 100% match score. All other license mentions are from third-party vendor dependencies.

💾 Results saved to: ./license_analysis_results/facebook_react/

⏱  Total: 12.4s  (download 3.1s | scancode 7.5s | llm 1.8s)
```

### Report File

The text report contains the license determination header and timing breakdown — no verbose license-mention details:

```
============================================================
LICENSE ANALYSIS REPORT: facebook/react
Generated: 2025-02-11 14:30:22
============================================================

FINAL LICENSE DETERMINATION
------------------------------------------------------------
SPDX Expression:    MIT
Main Licenses:      MIT
Excluded Licenses:  None
Confidence:         95%
Needs Review:       No

Rationale:
The root LICENSE file contains the full MIT license text with a 100%
match score. All other license mentions are from third-party vendor
dependencies.

============================================================
TIMING
------------------------------------------------------------
Download:   3.1s
ScanCode:   7.5s
LLM:        1.8s
Total:      12.4s
```

### JSON File

The JSON file contains the full structured data: all license mentions with file roles, match scores, context, SPDX expressions, the LLM decision, and timing.

## Project Structure

```
capstone-analyzer/
├── capstone_lite.py              # Main script — pipeline orchestrator
├── extract_license_context.py    # ScanCode output → structured context
├── requirements.txt              # Python dependencies
├── setup.sh                      # Automated setup script
├── .env                          # API keys (not committed)
├── .gitignore
└── README.md
```

## Requirements

- **Python 3.10+**
- **macOS / Linux** (ScanCode does not officially support Windows)
- A Mistral AI API key for LLM classification

### Important: Anaconda Users

If you have Anaconda installed, see the [Quick Start](#if-you-have-anaconda-installed-recommended-first-step) section — you must create your venv with system Python, not Anaconda's.

## Troubleshooting

**ScanCode `libmagic` error** — You're likely using an Anaconda-created venv. Recreate it with system Python (see above). You can also try `brew install libmagic` on macOS.

**GitHub rate limit (403)** — Add a `GITHUB_TOKEN` to your `.env` file to increase the limit from 60 to 5,000 requests/hour.

**"Skipping LLM analysis"** — The `MISTRAL_API_KEY` is missing from `.env`. ScanCode results are still saved, but without the final classification.

**ScanCode `Invalid inputs: all input paths must be relative`** — Make sure you're using the latest version of `capstone_lite.py` which scans the directory instead of passing individual file paths.

## License

This project is developed as a capstone project at Télécom Paris, in collaboration with [CAST](https://www.castsoftware.com/) at École Polytechnique.
