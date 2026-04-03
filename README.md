# Manifest

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills marketplace for Android app development. Install production-grade skills that extend Claude Code with deep Android and Kotlin expertise.

## Available plugins

| Plugin | Version | Description |
|--------|---------|-------------|
| [android-review-plugin](plugins/android-review-plugin/skills/android-review/README.md) | 1.0.0 | Staff-level Android code review for Kotlin, Jetpack Compose, coroutines, memory leaks, architecture, and production-scale pitfalls |

## android-review

The flagship skill in this marketplace. Invoke `/android-review` in Claude Code to get a structured code review from a staff-engineer perspective, organized by severity:

- **Blocking** -- crashes, ANRs, memory leaks, data loss
- **Warnings** -- correctness issues, anti-patterns, deprecated APIs
- **Suggestions** -- idiomatic improvements and minor optimizations

### Review categories

| Category | Covers |
|----------|--------|
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

### Quick start

```bash
# Review a feature branch against main
/android-review -branch feature/settings-refactor main

# Quick blocking-issues-only scan
/android-review -branch release/2.1 main -depth quick

# Focus on Compose issues only
/android-review -staged -focus compose

# Firefox for Android — loads Mozilla-specific patterns
/android-review -branch fenix-feature main -firefox
```

### Flags

| Flag | Description |
|------|-------------|
| `-branch FEATURE BASE` | Review diff between two branches |
| `-file PATH` | Review a single file |
| `-staged` | Review staged changes |
| `-unstaged` | Review working tree changes |
| `-focus CATEGORY` | Restrict to one category (`memory`, `compose`, `coroutines`, `arch`, `kotlin`, `security`, `lifecycle`, `threading`, `testing`, `gradle`) |
| `-depth quick\|full` | `quick` = blocking only; `full` = complete review (default) |
| `-firefox` | Load Mozilla/Firefox for Android patterns |
| `-message "TEXT"` | Pass context to the reviewer |
| `-no-save` | Suppress the save-review prompt |

See the [full plugin documentation](plugins/android-review-plugin/skills/android-review/README.md) for details on the gather script, reference guides, and additional usage examples.

### Reference guides

The skill includes specialized reference documents loaded contextually during review:

- **Compose stability guide** -- Compose compiler stability inference, recomposition bugs, `remember` vs `rememberSaveable` decision trees
- **Mozilla Firefox patterns** -- Firefox for Android (Fenix) project-specific conventions including Store/Action/Reducer/Middleware, Proto DataStore migration, and Hilt scoping

## Requirements

- **Python 3.10+** -- powers the diff-gathering script
- **Git** -- the project under review must be a git repository
- **ktlint** (optional) -- if available, style issues are reported separately from the code review
