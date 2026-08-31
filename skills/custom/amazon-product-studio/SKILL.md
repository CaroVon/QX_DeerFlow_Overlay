---
name: amazon-product-studio
description: Use this skill for Amazon product research and competitive analysis tasks, such as "research this Amazon niche", "analyze competitors for keyword X", "generate a competitor matrix report", or full product idea validation. Orchestrates the qx Amazon tools (data collection, MOD competitor matrix) into a structured product research workflow.
---

# Amazon Product Studio Skill

## Overview

This skill drives Amazon product research end-to-end using the QX toolset:
`collect_amazon_data_tool` (lightweight market snapshot) and
`competitor_matrix_tool` (full MOD analysis: zoning, metrics, chapters,
optional charts/PPTX).

## When to Use This Skill

- User asks about an Amazon niche, category, or keyword competitive landscape
- User wants a competitor matrix / pricing analysis / zone positioning
- User is validating a product idea before strategy/PRD work

## Workflow

### Step 1: Clarify the target

Confirm with the user: keyword (English works best), marketplace (default
amazon.com), and whether to spend real API credits (`source: rainforest`) or
run on offline demo data (`source: mock`). If unclear and the user seems to be
testing, default to `mock` and say so.

### Step 2: Market snapshot (cheap first)

Call `collect_amazon_data_tool` with top_n=20. Summarize for the user:
price range / avg rating / review volume / zone counts / top ASINs.

### Step 3: Full MOD matrix (when depth is needed)

Call `competitor_matrix_tool` reusing the collected `data_dir` semantics
(prior collection is auto-replayed from the archive — do NOT re-collect).
Choose options with the user:
- `skip_llm`: faster, data-only chapters
- `with_visuals`: SVG charts + PPTX artifact (needs rendering backend)

### Step 4: Report back

Present: zone structure (premium/value/core/risk), cost estimate, key chapter
insights, and artifact paths (pptx / charts). Offer follow-ups: strategy,
PRD, presentation deck.

## Notes

- Real Rainforest calls cost credits (1 + N products + review pages). Always
  confirm before spending.
- Output artifacts land under QX_OUTPUT_DIR; cite the paths verbatim so the
  user can find them.
