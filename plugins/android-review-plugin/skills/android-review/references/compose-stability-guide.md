# Compose Stability & Recomposition Reference

Deep reference for diagnosing and fixing recomposition problems. Load this when reviewing
Compose UI code with suspected performance or correctness issues.

---

## How the Compiler Decides to Skip Recomposition

The Compose compiler marks each `@Composable` parameter as either **stable** or **unstable**.

- If **all** parameters are stable and **none** have changed since the last composition → Compose **skips** the composable (the fast path).
- If **any** parameter is unstable → Compose **always** recomposes (even if the value didn't change).

A type is considered **stable** by the compiler if:
1. It's a primitive (`Int`, `Boolean`, `String`, etc.)
2. It has the `@Stable` or `@Immutable` annotation
3. It's a Kotlin `object`
4. It's a lambda (lambdas are always considered stable)
5. All public properties are themselves stable and are `val`

A type is considered **unstable** if:
- It's a `List`, `Map`, `Set` (even with only stable contents — the compiler can't verify the contents won't mutate)
- It has any `var` property
- It contains an unstable field
- It's from a module that wasn't compiled with the Compose compiler (e.g., a pure Kotlin module)

---

## Common Stability Bugs

### 1. `List<T>` as a Composable parameter

```kotlin
// Unstable — List is not guaranteed immutable by the compiler
@Composable
fun TaskList(tasks: List<Task>) { ... }

// Fix A: Use kotlinx-collections-immutable
@Composable
fun TaskList(tasks: ImmutableList<Task>) { ... }

// Fix B: Wrap in a @Stable holder
@Stable
class TaskListState(val tasks: List<Task>)

// Fix C (Compose 1.5+): The compiler is smarter now but still verify with metrics
```

### 2. Data class with an unstable field

```kotlin
// Unstable — List<Tag> makes the whole class unstable
data class Article(
    val id: String,
    val title: String,
    val tags: List<Tag>,  // ← unstable field
)

// Fix: annotate @Immutable if you guarantee no mutation
@Immutable
data class Article(
    val id: String,
    val title: String,
    val tags: List<Tag>,  // safe because we promise not to mutate
)
```

**Note:** `@Immutable` is a contract you're making to the compiler. Only add it if you
guarantee the object and all its transitively reachable state never changes after construction.
Lying to the compiler here causes subtle, hard-to-reproduce UI bugs.

### 3. ViewModel passed directly to a composable

```kotlin
// Bad — ViewModel is never stable; this disables skipping for the entire subtree
@Composable
fun ProfileScreen(viewModel: ProfileViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    ProfileContent(state = state, onAction = viewModel::handleAction)
}

// Good — only stable types cross the composable boundary
@Composable
fun ProfileScreen(viewModel: ProfileViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    ProfileContent(state = state, onAction = viewModel::handleAction)
}

@Composable
private fun ProfileContent(state: ProfileUiState, onAction: (ProfileAction) -> Unit) {
    // This composable can now be skipped correctly
}
```

### 4. Lambda captures changing every recomposition

```kotlin
// Bad — creates a new lambda on every recomposition of the parent
@Composable
fun ItemList(items: List<Item>, onDelete: (Item) -> Unit) {
    items.forEach { item ->
        ItemRow(
            item = item,
            onClick = { onDelete(item) }  // new lambda every time
        )
    }
}

// Fix: use rememberUpdatedState when you need the latest value
@Composable
fun ItemList(items: List<Item>, onDelete: (Item) -> Unit) {
    val currentOnDelete by rememberUpdatedState(onDelete)
    items.forEach { item ->
        val currentItem by rememberUpdatedState(item)
        ItemRow(
            item = item,
            onClick = remember { { currentOnDelete(currentItem) } }
        )
    }
}
```

### 5. `derivedStateOf` missing for computed stable values

```kotlin
// Bad — the composable recomposes every time scrollState changes,
// even though isScrolled only changes from false→true once
@Composable
fun Header(scrollState: ScrollState) {
    val isScrolled = scrollState.value > 0  // triggers recomposition on every scroll pixel
    if (isScrolled) ElevatedHeader() else FlatHeader()
}

// Good — recomposes only when isScrolled flips
@Composable
fun Header(scrollState: ScrollState) {
    val isScrolled by remember { derivedStateOf { scrollState.value > 0 } }
    if (isScrolled) ElevatedHeader() else FlatHeader()
}
```

---

## Checking Stability With Compiler Metrics

Enable in `build.gradle.kts`:

```kotlin
composeCompiler {
    metricsDestination = layout.buildDirectory.dir("compose_metrics")
    reportsDestination = layout.buildDirectory.dir("compose_metrics")
}
```

Run: `./gradlew assembleDebug`

Look for in `*-composables.txt`:
```
restartable skippable scheme("[...]") fun TaskList(
  stable tasks: ImmutableList<Task>    ← good
)

restartable scheme("[...]") fun ArticleRow(
  unstable article: Article            ← bad — this will never skip
)
```

Any `unstable` parameter on a frequently-called composable (list items, anything in a
scrolling container) is a performance issue worth fixing.

---

## `remember` vs `rememberSaveable` Decision Tree

| Situation | Use |
|---|---|
| Expensive object, doesn't need to survive config change | `remember { }` |
| User-visible UI state (expanded, selected, scroll position) | `rememberSaveable { }` |
| State that must survive process death (navigation args, form input) | `rememberSaveable` + custom `Saver` or `SavedStateHandle` in ViewModel |
| State derived from stable inputs | `remember(key) { derivedStateOf { } }` |

---

## Side Effect Decision Tree

| Need | Hook |
|---|---|
| One-time initialization when composable enters composition | `LaunchedEffect(Unit)` |
| Re-run when a value changes | `LaunchedEffect(key)` |
| Clean up when composable leaves composition | `DisposableEffect` + `onDispose {}` |
| Run on every recomposition (rare — analytics, logging) | `SideEffect` |
| Expose a coroutine scope to event handlers | `rememberCoroutineScope()` |
| Collect a Flow as state | `collectAsStateWithLifecycle()` |

**Common mistake:** Using `LaunchedEffect(Unit)` when the key should be a real value.
If the LaunchedEffect depends on a parameter that can change (userId, featureFlag, tabId),
that parameter must be the key, or the effect will run once and then silently ignore future changes.
