# android-review

A [Claude Code skill](https://docs.anthropic.com/en/docs/claude-code/skills) that performs staff-level Android code reviews for Kotlin, Jetpack Compose, coroutines/Flow, memory leaks, architecture, and production-scale pitfalls.

## What it does

When invoked, the skill gathers changed Kotlin files (via branch diff, staged changes, or single file), optionally runs ktlint, and delivers a structured review organized by severity:

- **Blocking** -- issues that will cause crashes, ANRs, memory leaks, or data loss in production
- **Warnings** -- correctness issues, anti-patterns, and deprecated API usage
- **Suggestions** -- idiomatic improvements and minor optimizations

## Review categories

| Category | Covers |
|---|---|
| Memory | Context leaks, view leaks, coroutine/Flow leaks, handler leaks |
| Coroutines | Dispatcher misuse, structured concurrency, Flow correctness, cancellation |
| Compose | Recomposition, side effects, state management, performance |
| Architecture | ViewModel boundaries, repository patterns, Hilt/DI scoping |
| Kotlin | Null safety, idioms, sealed type exhaustiveness, suspend correctness |
| Security | Logging PII, hardcoded secrets, WebView risks, intent safety |
| Lifecycle | Fragment observation, back handling, navigation timing |
| Threading | Main-thread IO, SharedPreferences, bitmap decoding |
| Testing | Testability, coroutine test patterns, implementation coupling |
| Gradle | Compose compiler/BOM mismatches, dependency scoping, ProGuard/R8, AGP/SDK levels |

## Reference guides

The skill ships with two reference documents that are loaded during review:

- **`references/compose-stability-guide.md`** -- Deep reference on Compose compiler stability inference, common recomposition bugs, `remember` vs `rememberSaveable` decision trees, and how to read compiler metrics output. Loaded when Compose code is detected in the diff or `-focus compose` is set.
- **`references/mozilla-firefox-patterns.md`** -- Firefox for Android (Fenix) project-specific patterns including the Mozilla `Store`/`Action`/`Reducer`/`Middleware` state management pattern, Proto DataStore migration rules, Compose interop boundary rules, Hilt scoping conventions, and testing standards (JUnit 4 + MockK). Loaded when the `-firefox` flag is passed.

## The gather script

`scripts/gather_diff.py` collects files and diffs for review and outputs a structured JSON manifest.

```
Usage:
  python3 scripts/gather_diff.py --branch feature-branch main
  python3 scripts/gather_diff.py --file path/to/File.kt
  python3 scripts/gather_diff.py --staged
  python3 scripts/gather_diff.py --unstaged
```

The script:
1. Identifies changed `.kt`/`.kts` files, filtering out build outputs, generated code, and non-code assets
2. Extracts full file content and unified diffs with changed line ranges
3. Runs `ktlint` (if available) and includes lint findings in the manifest
4. Outputs everything as JSON for the skill to consume

Additional flags: `--no-ktlint`, `--depth quick|full`, `--focus CATEGORY`.

## Usage

```bash
# Review a feature branch against main
/android-review -branch feature/settings-refactor main

# Review a single file
/android-review -file app/src/main/java/com/example/SettingsViewModel.kt

# Quick blocking-issues-only scan
/android-review -branch release/2.1 main -depth quick

# Focus on Compose issues only
/android-review -branch compose-migration main -focus compose

# Firefox-specific review with Mozilla patterns
/android-review -branch fenix-feature main -firefox

# Review staged changes before committing
/android-review -staged

# Review unstaged working tree changes
/android-review -unstaged

# Pass context to the reviewer
/android-review -branch feature/sync main -message "pay attention to coroutine scoping"

# Suppress the save prompt
/android-review -branch feature/auth main -no-save

# Combine flags
/android-review -branch release/3.0 main -depth quick -firefox -message "block on anything crash-worthy"
```

## Installation

Place this repository inside your Claude Code skills directory (`~/.claude/skills/`). The skill is automatically discovered by Claude Code when the directory contains a `SKILL.md` file.

## Requirements

- Python 3.10+ (for `gather_diff.py`)
- Git (the project being reviewed must be a git repository)
- ktlint (optional -- if available, style issues are reported separately from the code review)
