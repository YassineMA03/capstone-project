# Capstone License Analyzer

A modular tool that automatically detects and classifies open-source licenses in GitHub repositories and local projects. It downloads only license-related files (no full clone), scans them with [ScanCode](https://github.com/aboutcode-org/scancode-toolkit), and uses Mistral AI to produce a final license determination with conflict resolution.

---

## 🔍 How It Works

1. **Fetch** — Retrieves license-related files from GitHub API or uses local files
2. **Download** — Downloads only LICENSE, README, COPYRIGHT files (5-30 files typically)
3. **Scan** — Runs ScanCode to detect every license mention, match score, and location
4. **Extract** — Builds structured context around each mention (surrounding lines, file roles, SPDX expressions)
5. **Classify** — Sends evidence to Mistral AI, which returns SPDX expression, confidence score, and main vs. excluded licenses
6. **Save** — Outputs JSON data and human-readable report
7. **Clean up** — Temporary files automatically deleted (use `--keep-temp` to preserve)

---
## Pipeline Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                               │
│  python main.py --link https://github.com/owner/repo            │
│         OR                                                       │
│  python main.py --folder /path/to/local/project                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │         main.py (orchestrator)      │
        │  - Parses CLI arguments             │
        │  - Loads environment variables      │
        │  - Coordinates all modules          │
        └────────────────┬───────────────────┘
                         │
        ┌────────────────┴───────────────────┐
        │                                    │
        ▼ (if --link)                        ▼ (if --folder)
┌───────────────────┐              ┌────────────────────┐
│ github_downloader │              │   Skip download     │
│  - Parse URL      │              │   Use local files   │
│  - Get API token  │              └─────────┬──────────┘
│  - Download files │                        │
└────────┬──────────┘                        │
         │                                   │
         └───────────────┬───────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │      scancode_runner.py        │
         │  - Run ScanCode toolkit        │
         │  - Generate JSON output        │
         └───────────┬───────────────────┘
                     │
                     ▼
         ┌───────────────────────────────┐
         │ license_context_extractor.py  │
         │  - Parse ScanCode JSON         │
         │  - Extract license mentions    │
         │  - Get surrounding context     │
         │  - Classify file roles         │
         └───────────┬───────────────────┘
                     │
                     ▼
         ┌───────────────────────────────┐
         │      llm_analyzer.py           │
         │  - Build prompt from mentions  │
         │  - Call Mistral API            │
         │  - Validate response           │
         │  - Return license decision     │
         └───────────┬───────────────────┘
                     │
                     ▼
         ┌───────────────────────────────┐
         │      main.py (save results)    │
         │  - Create output directory     │
         │  - Save JSON file              │
         │  - Save text report            │
         │  - Print summary               │
         └───────────────────────────────┘
```

---

## 📁 Project Structure

```
capstone-analyzer/
├── main.py                          # Main orchestration script
├── github_downloader.py             # Downloads files from GitHub
├── scancode_runner.py               # Runs ScanCode toolkit
├── license_context_extractor.py    # Processes ScanCode output
├── llm_analyzer.py                  # LLM-based license analysis
├── requirements.txt                 # Python dependencies
├── setup.sh                         # Automated setup script (optional)
├── .env                             # API keys (create this)
└── README.md                        # This file
```

### Module Overview

| Module | Purpose | When It Runs |
|--------|---------|--------------|
| **github_downloader.py** | Downloads LICENSE, README, COPYRIGHT files from GitHub | Only for `--link` (GitHub repos) |
| **scancode_runner.py** | Executes ScanCode toolkit to detect licenses | For both GitHub repos and local folders |
| **license_context_extractor.py** | Extracts license mentions with surrounding context from ScanCode output | After ScanCode completes |
| **llm_analyzer.py** | Uses Mistral AI to analyze evidence and determine final license | After context extraction (if API key provided) |
| **main.py** | Orchestrates the pipeline and handles CLI | Always (entry point) |

---

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd capstone-analyzer
```

### 2. Setup (Choose One Method)

#### Option A: Automated Setup (Recommended)
```bash
bash setup.sh
source venv/bin/activate
```

The script creates a virtual environment, installs dependencies, and generates a `.env` template.

#### Option B: Manual Setup
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# On macOS, if ScanCode needs libmagic:
brew install libmagic

# Verify ScanCode works
scancode --version

# Create .env file
cp .env.example .env
```

### 3. Configure API Keys

Edit `.env` with your credentials:
```bash
nano .env
```

Add:
```env
MISTRAL_API_KEY=your_mistral_key_here
GITHUB_TOKEN=your_github_token_here  # Optional, for higher rate limits
```

### 4. Run Your First Analysis
```bash
# Analyze a GitHub repository
python main.py --link https://github.com/facebook/react

# Analyze a local folder
python main.py --folder /path/to/my/project
```

---

## ⚙️ Configuration (.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `MISTRAL_API_KEY` | **Yes** | API key from [Mistral AI](https://console.mistral.ai/). Without it, ScanCode still runs but LLM classification is skipped. |
| `GITHUB_TOKEN` | No | GitHub personal access token. Not needed for public repos, but increases API rate limit from 60 to 5,000 requests/hour. Get one at [github.com/settings/tokens](https://github.com/settings/tokens). |

Example `.env`:
```env
MISTRAL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 💻 Usage

```bash
python main.py --link <GITHUB_URL> [OPTIONS]
python main.py --folder <PATH> [OPTIONS]
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--link` | One of `--link` or `--folder` | — | GitHub repository URL to analyze |
| `--folder` | One of `--link` or `--folder` | — | Path to a local folder to scan |
| `--output`, `-o` | No | `./license_analysis_results` | Output directory for results |
| `--keep-temp` | No | `false` | Keep temporary downloaded files (debugging) |

### Examples

```bash
# Analyze GitHub repository
python main.py --link https://github.com/twbs/bootstrap

# Analyze local folder
python main.py --folder /path/to/my/project

# Custom output directory
python main.py --link https://github.com/vuejs/vue --output ./results

# Keep temporary files for debugging
python main.py --link https://github.com/angular/angular --keep-temp
```

---

## 📊 Output

### Directory Structure
Results are saved in a **per-project folder**:

```
license_analysis_results/
└── facebook_react/
    ├── analysis_20250211_143022.json    # Full structured data
    └── report_20250211_143022.txt       # Human-readable summary
```

### Terminal Output
```
📋 FINAL LICENSE DETERMINATION
   SPDX Expression:    MIT
   Main Licenses:      MIT
   Excluded Licenses:  None
   Confidence:         95%
   Needs Review:       ✓ No

   Rationale: Repository contains a clear MIT license in the root LICENSE 
   file. No conflicting licenses detected. README confirms MIT licensing.

💾 Results saved to: license_analysis_results/facebook_react/

⏱  Total: 12.4s  (download 3.1s | scancode 7.5s | llm 1.8s)
```

### Text Report (`report_*.txt`)
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
Repository contains a clear MIT license in the root LICENSE file
with exact match (score=100). No conflicting licenses detected.

============================================================
TIMING
------------------------------------------------------------
Download:   3.1s
ScanCode:   7.5s
LLM:        1.8s
Total:      12.4s
```

### JSON File (`analysis_*.json`)
Contains complete structured data:
- All license mentions with context
- File roles and match scores
- SPDX expressions
- LLM decision with rationale
- Timing breakdown

---

## 🎯 Pipeline Details

### For GitHub Repositories (`--link`)
```
1. Parse GitHub URL → Extract owner/repo
2. Download license files → LICENSE, README, COPYRIGHT (via GitHub API)
3. Run ScanCode → Detect all license mentions
4. Extract context → Surrounding lines, file roles, SPDX expressions
5. LLM analysis → Determine main license(s), resolve conflicts
6. Save results → JSON + text report
7. Clean up → Delete temporary files
```

### For Local Folders (`--folder`)
```
1. Run ScanCode → Scan all files in folder
2. Extract context → Surrounding lines, file roles, SPDX expressions
3. LLM analysis → Determine main license(s), resolve conflicts
4. Save results → JSON + text report
```

---

## 🔧 Advanced Features

### LLM Analysis Capabilities

The Mistral AI model provides:
- ✅ **Conflict resolution** — LICENSE file vs README disagreements
- ✅ **Dual licensing detection** — Properly identifies "MIT OR Apache-2.0"
- ✅ **Scope separation** — Distinguishes code licenses from documentation licenses
- ✅ **Historical detection** — Excludes "previously MIT, now GPL" references
- ✅ **Dependency filtering** — Excludes third-party library licenses
- ✅ **Confidence scoring** — 0.0-1.0 scale with human review flag

### Modular Design

Each module is **independent** and can be replaced:
- Swap `llm_analyzer.py` → Use OpenAI, Anthropic, or other LLM providers
- Modify `github_downloader.py` → Support GitLab, Bitbucket, etc.
- Replace `scancode_runner.py` → Use alternative license scanners

Example module replacement:
```python
# In main.py
from my_openai_analyzer import analyze_with_openai

# Replace Mistral with OpenAI
llm_decision = analyze_with_openai(repo_name, license_mentions, api_key)
```

---

## 🛠️ Requirements

- **Python 3.10+**
- **macOS / Linux** (ScanCode does not officially support Windows)
- **Mistral AI API key** for LLM classification

### Dependencies
All installed via `requirements.txt`:
```
scancode-toolkit
mistralai
python-dotenv
pydantic
requests
```

---

## 🚨 Troubleshooting

### Common Issues

**Problem:** ScanCode `libmagic` error  
**Solution:** Install libmagic: `brew install libmagic` (macOS) or use system Python instead of Anaconda

**Problem:** GitHub rate limit (403)  
**Solution:** Add `GITHUB_TOKEN` to `.env` to increase limit from 60 to 5,000 requests/hour

**Problem:** "Skipping LLM analysis"  
**Solution:** `MISTRAL_API_KEY` is missing from `.env`. ScanCode results still saved, but no final classification.

**Problem:** "Extracted 0 license mentions"  
**Solution:** You may have an older ScanCode version. Use `license_context_extractor_ultimate.py` which supports v21, v30, and v32 formats.

### Anaconda Users

If you have Anaconda installed, create venv with system Python:

```bash
# Exit Anaconda environment
conda deactivate

# Remove Anaconda from PATH
export PATH=$(echo "$PATH" | sed 's|/opt/anaconda3/[^:]*:||g')

# Verify system Python
which python3  # Should NOT show /opt/anaconda3/

# Create clean venv
python3 -m venv venv
source venv/bin/activate
```

---

## ⚡ Performance

Typical timings for standard repository:
- **Download**: 2-5 seconds
- **ScanCode**: 10-100 seconds
- **LLM Analysis**: 1-3 seconds
- **Total**: ~10-110 seconds

Large repos (100+ files) may take longer for ScanCode analysis.

---

## 🎓 Project Information

This project is developed as a capstone project in collaboration with [CAST](https://www.castsoftware.com/) at École Polytechnique.
