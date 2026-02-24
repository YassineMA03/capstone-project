#!/usr/bin/env python3
"""
LLM License Analyzer Module
Uses Mistral AI to analyze license mentions and determine repository licenses.
"""

import re
import json
from typing import List, Dict, Any
from mistralai import Mistral
from pydantic import BaseModel, Field, ValidationError


# -----------------------------
# Data Models
# -----------------------------

class LicenseDecision(BaseModel):
    """
    Structured output from the LLM license analysis.
    Validated using Pydantic to ensure correct format.
    """
    spdx_expression: str                    # e.g., "MIT" or "Apache-2.0 OR MIT"
    main_licenses: List[str]                # List of main repository licenses
    excluded_licenses: List[str]            # Licenses that don't apply (docs only, etc.)
    confidence: float = Field(..., ge=0.0, le=1.0)  # 0.0 to 1.0
    rationale: str                          # Explanation of the decision
    needs_human_review: bool                # Flag if uncertain/contradictory


# -----------------------------
# Helper Functions
# -----------------------------

def extract_first_json(text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object from LLM response text.
    LLMs sometimes add explanation before/after JSON.
    
    Args:
        text: Raw LLM response text
    
    Returns:
        Parsed JSON object
    
    Raises:
        ValueError: If no valid JSON found
    """
    # Search for JSON object pattern
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON found in output.\n" + text[-800:])
    
    return json.loads(m.group(0))


def safe_join(lines: Any) -> str:
    """
    Safely convert a list of lines to a single string.
    
    Args:
        lines: List of strings or other value
    
    Returns:
        Joined string with | separator
    """
    if not lines:
        return ""
    if isinstance(lines, list):
        return " | ".join(str(x) for x in lines)
    return str(lines)


def clip_text(t: Any, n: int = 700) -> str:
    """
    Clip text to maximum length for inclusion in prompts.
    
    Args:
        t: Text to clip
        n: Maximum length
    
    Returns:
        Clipped text with ellipsis if truncated
    """
    if t is None:
        return "null"
    s = str(t).strip()
    return s if len(s) <= n else s[:n] + "…"


def build_prompt_from_mentions(repo: str, mentions: List[Dict[str, Any]]) -> str:
    """
    Build the LLM prompt from extracted license mentions.
    Creates a structured prompt with all evidence for the LLM to analyze.
    
    Args:
        repo: Repository name
        mentions: List of license mention dictionaries
    
    Returns:
        Complete prompt string for the LLM
    """
    # Collect all mentioned licenses to constrain LLM output
    candidates = set()
    for m in mentions:
        if m.get("license_name"):
            candidates.add(m["license_name"])
        
        # Parse SPDX expressions to get individual licenses
        expr = m.get("spdx_expression")
        if expr:
            for tok in re.split(r"[\s()]+", expr):
                tok = tok.strip()
                # Skip logical operators
                if tok and tok not in {"AND", "OR", "WITH"}:
                    candidates.add(tok)

    # Format evidence blocks for each mention
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

    # Build complete prompt with instructions and evidence
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
- excluded_licenses MUST be a flat JSON array of strings (e.g. ["MIT", "Apache-2.0"]). Do NOT use a nested object.
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
    """
    Analyze license mentions using Mistral LLM.
    Main entry point for LLM analysis.
    
    Args:
        repo: Repository name
        mentions: List of license mention dictionaries
        api_key: Mistral API key
        model_name: Mistral model to use
        temperature: Sampling temperature (0.0 = deterministic)
        max_tokens: Maximum response length
    
    Returns:
        Validated license decision dictionary
    
    Raises:
        ValueError: If LLM output doesn't match expected schema
    """
    # Build the analysis prompt
    prompt = build_prompt_from_mentions(repo, mentions)

    # Initialize Mistral client
    client = Mistral(api_key=api_key)
    
    # Call the LLM
    res = client.chat.complete(
        model=model_name,
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Extract and parse response
    content = res.choices[0].message.content
    data = extract_first_json(content)

    # Validate against schema
    try:
        decision = LicenseDecision(**data)
    except ValidationError as e:
        raise ValueError(
            f"Schema validation failed:\n{e}\n\n"
            f"Parsed JSON:\n{data}\n\n"
            f"Raw output:\n{content}"
        )

    # Return as dictionary
    return decision.model_dump()
