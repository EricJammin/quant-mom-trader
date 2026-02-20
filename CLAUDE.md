# CLAUDE.md

Systematic swing trading strategy (long-only) for S&P 500 stocks. Python project.

## Specification

See @trading-strategy-spec.md for the complete strategy rules, pipeline architecture, backtesting workflow, and acceptance criteria. Always reference this spec before making architectural decisions.

# Review Plan Before Implementation

Review the current plan thoroughly before making any code changes. For every issue or recommendation, explain the concrete tradeoffs, give an opinionated recommendation, and ask for user input before assuming a direction.

## Engineering Preferences

Use these to guide your recommendations (override with project-specific CLAUDE.md preferences if they exist):

- DRY is important: flag repetition aggressively
- Well-tested code is non-negotiable: prefer too many tests over too few
- Code should be "engineered enough": not under-engineered (fragile, hacky) and not over-engineered (premature abstraction, unnecessary complexity)
- Err on the side of handling more edge cases, not fewer
- Bias toward explicit over clever; thoughtfulness over speed

## Review Pipeline

Work through each section sequentially. After each section, pause and ask for feedback before moving on.

### 1. Architecture Review

Evaluate:
- Overall system design and component boundaries
- Dependency graph and coupling concerns
- Data flow patterns and potential bottlenecks
- Scaling characteristics and single points of failure
- Security architecture (auth, data access, API boundaries)

### 2. Code Quality Review

Evaluate:
- Code organization and module structure
- DRY violations (be aggressive here)
- Error handling patterns and missing edge cases (call these out explicitly)
- Technical debt hotspots
- Areas that are over-engineered or under-engineered relative to engineering preferences

### 3. Test Review

Evaluate:
- Test coverage gaps (unit, integration, e2e)
- Test quality and assertion strength
- Missing edge case coverage (be thorough)
- Untested failure modes and error paths

### 4. Performance Review

Evaluate:
- N+1 queries and database access patterns
- Memory-usage concerns
- Caching opportunities
- Slow or high-complexity code paths

## Issue Reporting Format

For every specific issue found (bug, smell, design concern, or risk):

1. Describe the problem concretely, with file and line references
2. Present 2-3 options, including "do nothing" where that's reasonable
3. For each option, specify: implementation effort, risk, impact on other code, and maintenance burden
4. Give your recommended option and why, mapped to engineering preferences above
5. Ask explicitly whether the user agrees or wants to choose a different direction before proceeding

## Workflow

- Do not assume priorities on timeline or scale
- After each section, pause and ask for feedback before moving on
- Use AskUserQuestion for structured option selection

## Before Starting

Ask if the user wants one of two options:

1. **BIG CHANGE**: Work through this interactively, one section at a time (Architecture → Code Quality → Tests → Performance) with at most 4 top issues in each section
2. **SMALL CHANGE**: Work through interactively ONE question per review section

## Tips

- Combine with `.claude/rules/` files for project-specific review criteria
- Engineering preferences above can be overridden by your project's CLAUDE.md
- For deeper analysis, use this command with Opus model

## Project Structure

```
momentum_pullback_system/
├── config.py              # ALL tunable parameters — single source of truth
├── data/                  # Data fetching and caching (abstract + concrete implementations)
├── pipeline/              # Strategy logic: regime_filter, universe_filter, momentum_rank, entry_trigger, risk_manager
├── backtest/              # Engine, portfolio tracker, metrics, monte carlo, parameter sweep
├── live/                  # Phase 2 only — scanner and alerter
├── reports/               # HTML/chart generation for backtest results
├── scripts/               # CLI entry points (download_data, run_backtest, run_parameter_sweep)
└── tests/                 # Unit tests per pipeline module
```

## Code Style

- Python 3.10+
- Type hints on all function signatures
- Docstrings on all public functions (one-line summary + params + returns)
- Use pandas DataFrames for tabular data throughout
- Use pathlib for file paths, not os.path
- f-strings for string formatting
- No wildcard imports

## Commands

- `pip install -r requirements.txt`: Install dependencies
- `python scripts/download_data.py`: Download and cache historical data
- `python scripts/run_backtest.py`: Run full backtest with current config
- `python scripts/run_parameter_sweep.py`: Run parameter sensitivity analysis
- `pytest tests/`: Run all unit tests

## Key Principles

- **Modularity is critical.** Pipeline modules must not depend on whether data is historical or live. They accept DataFrames and return results. The data layer handles the abstraction.
- **config.py is the single source of truth** for all tunable parameters. Never hardcode parameter values in pipeline or backtest modules.
- **Conservative assumptions in backtesting:** Enter at next day's open (not signal day's close). If both stop and target are breached in same bar, assume stop was hit. Model slippage and commissions.
- **Build incrementally.** Follow the build order in the spec (Section 11). Test each module before moving to the next.

## Important Warnings

- Do NOT use `Backtesting.py` library — we are building a custom engine for full control over the pipeline logic.
- Do NOT download data on every backtest run. Cache data locally in `data/cache/` as Parquet files.
- Do NOT modify acceptance criteria after seeing backtest results. They are defined upfront in the spec (Section 6).

## Token Efficiency

- Use /clear between unrelated tasks to reset context.
- For large refactors, work on one module at a time rather than touching many files simultaneously.
- Reference files with @path/to/file.py rather than pasting contents into chat.
- Keep this file under 100 lines.
