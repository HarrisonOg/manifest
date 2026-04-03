# Mozilla Firefox for Android — Project-Specific Patterns

This reference is loaded when reviewing code in the Firefox for Android (Fenix) codebase.
It covers Mozilla-specific conventions that differ from general Android best practices.

---

## Components / Service Locator

Firefox uses no DI framework. All dependencies live in a single `Components` class with lazy initialization via `lazyMonitored` delegates. This is a deliberate choice for transparency, compile-time safety, and zero reflection overhead.

### Access patterns

```kotlin
// From Fragment
val store = requireComponents.core.store

// From any Context
val settings = context.components.settings

// From Composable
val components = LocalContext.current.components
```

### Review flags

- **Creating a dependency manually that already exists in `Components`** — 🟡 Warning. Check `Components.kt` before instantiating services, repositories, or use cases.
- **Accessing `Components` from a background thread before app init completes** — 🟡 Warning. Some components are lazily initialized and may not be thread-safe during early startup.

---

## Mozilla State Pattern

Firefox uses a custom unidirectional state management pattern built around `Store`, `Action`, `Reducer`, and `Middleware`. This is distinct from MVI/Redux-style libs like Orbit or MVI-Core.

### Core types

```kotlin
// State is a data class — always immutable, always copied on change
data class BrowserState(
    val tabs: List<TabSessionState> = emptyList(),
    val selectedTabId: String? = null,
)

// Actions are sealed classes — one per state mutation type
sealed class BrowserAction : Action {
    data class AddTabAction(val tab: TabSessionState) : BrowserAction()
    data object RemoveAllTabsAction : BrowserAction()
}

// Reducer is a pure function — no side effects, no coroutines
fun browserStateReducer(state: BrowserState, action: BrowserAction): BrowserState =
    when (action) {
        is BrowserAction.AddTabAction -> state.copy(tabs = state.tabs + action.tab)
        is BrowserAction.RemoveAllTabsAction -> state.copy(tabs = emptyList())
    }
```

### Store hierarchy

- **Global stores** (`AppStore`, `BrowserStore`) — persist for app lifetime, held in `Components`
- **Screen-scoped stores** — created per Fragment, destroyed with Fragment, persisted across config changes via `StoreProvider`

### Review flags

- **Reducer doing IO or launching coroutines** — 🔴 Blocking. Reducers must be pure and synchronous.
- **State class with mutable fields (`var`)** — 🔴 Blocking. All state must be `val`.
- **State class not a `data class`** — 🟡 Warning. Non-data-class state can't be diffed correctly by observers.
- **Direct state mutation** — 🔴 Blocking. Never mutate state directly; always go through `store.dispatch(action)`.
- **Android platform types (`Context`, `View`) in State** — 🔴 Blocking. State must contain only Kotlin/Java data types for testability and to avoid leaks.

---

## Middleware

Middleware sits between dispatch and reducer. It's the designated layer for side effects: async IO, navigation, telemetry, persistence.

### Structure

```kotlin
// Class-based, dependencies injected via constructor (often as lambdas for lifecycle safety)
class SettingsMiddleware(
    private val storage: suspend () -> SettingsStorage,
    private val navController: () -> NavController,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : Middleware<SettingsState, SettingsAction> {

    private val scope = CoroutineScope(ioDispatcher)

    override fun invoke(
        store: Store<SettingsState, SettingsAction>,
        next: (SettingsAction) -> Unit,
        action: SettingsAction,
    ) {
        val preReductionState = store.state  // capture state before reducer runs
        next(action)                         // MUST call — passes action down the chain

        when (action) {
            is SettingsAction.Init -> scope.launch {
                val data = storage().load()
                withContext(Dispatchers.Main) {
                    store.dispatch(SettingsAction.DataLoaded(data))
                }
            }
            is SettingsAction.Save -> scope.launch {
                storage().save(store.state)
            }
            is SettingsAction.BackClicked -> {
                navController().popBackStack()
            }
        }
    }
}
```

### Review flags

- **Middleware not calling `next(action)`** — 🔴 Blocking. Breaks the chain — reducer never runs, state never updates. Only omit `next()` intentionally to consume/swallow an action.
- **Middleware blocking on IO without a coroutine scope** — 🔴 Blocking. All async work must use a CoroutineScope, not block the middleware chain.
- **Middleware using `GlobalScope`** — 🟡 Warning. Use an owned `CoroutineScope(Dispatchers.IO)` so work can be cancelled.
- **Dependencies injected as direct references instead of lambdas** — 🟡 Warning. Middleware outlives some dependencies (e.g., `NavController`); use `() -> NavController` or `WeakReference` to avoid lifecycle issues.
- **Middleware with side effects that aren't tested** — 🟡 Warning. Middleware is the intentional side-effect layer; it must have unit tests covering each action it handles.

---

## Controller / Interactor Pattern

Firefox uses a two-layer pattern for handling user interactions. Controllers handle business logic; Interactors delegate UI events to the appropriate Controller(s).

> **Note:** Per [RFC #1466](https://github.com/mozilla-mobile/firefox-android/pull/1466), Interactors are considered historical and are being refactored out. New screens may skip the Interactor and have Composables dispatch actions directly to Stores. But both patterns are still active in the codebase.

### Controller

```kotlin
class DefaultSettingsController(
    private val store: SettingsStore,
    private val navController: NavController,
    private val settings: Settings,
) : SettingsController {
    override fun handleSettingChanged(key: String, value: Boolean) {
        store.dispatch(SettingsAction.Update(key, value))
        settings.preferences.edit().putBoolean(key, value).apply()
    }
    override fun handleNavigateToDetail(settingId: String) {
        navController.navigate(SettingsFragmentDirections.actionToDetail(settingId))
    }
}
```

### Interactor (multi-controller routing)

```kotlin
class HomeInteractor(
    private val sessionController: SessionControlController,
    private val bookmarksController: BookmarksController,
    private val pocketController: PocketStoriesController,
) : HomepageInteractor {
    override fun onTabClicked(tabId: String) = sessionController.handleTabClicked(tabId)
    override fun onBookmarkClicked(bookmark: Bookmark) = bookmarksController.handleBookmarkClicked(bookmark)
    override fun onStoryClicked(story: PocketStory) = pocketController.handleStoryClicked(story)
}
```

### Review flags

- **Controller doing UI work directly** (setting view properties, showing dialogs) — 🟡 Warning. Controllers handle logic and dispatch; UI updates belong in Bindings or Composables.
- **Interactor containing business logic** — 🟡 Warning. Interactors should only delegate to Controllers.
- **Controller holding `Activity` reference directly** — 🔴 Blocking. Use a lambda `() -> Activity` or `WeakReference` to avoid leaks.

---

## State Observation

Firefox has four patterns for observing Store state. Use the right one for the context.

### 1. `consumeFrom` — XML Fragment (simplest)

```kotlin
// In onViewCreated — Mozilla helper, lifecycle-managed automatically
consumeFrom(localeSettingsStore) { state ->
    localeView.update(state)
}
```

### 2. `flowScoped` — Complex Flow transformations

```kotlin
// In onStart — when you need map/filter/combine on the state flow
store.flowScoped(viewLifecycleOwner, Dispatchers.Main) { flow ->
    flow.map { state -> state.tabs.size }
        .distinctUntilChanged()
        .collect { count -> updateTabCount(count) }
}
```

### 3. `observeAsComposableState` — Mozilla Compose helper

```kotlin
// Mozilla-specific extension with lifecycle awareness
val state by store.observeAsComposableState { it }
```

### 4. `collectAsState` — Standard Compose

```kotlin
// Standard Jetpack Compose pattern
val labsFeatures by remember { store.stateFlow.map { it.labsFeatures } }
    .collectAsState(initial = store.state.labsFeatures)
```

### Review flags

- **Flow collection without `distinctUntilChanged()`** — 🟡 Warning. Causes excess UI updates on every state emission, even when the observed slice hasn't changed.
- **Observing store without lifecycle scoping** (e.g., `store.observe(this)` where `this` is Fragment instead of `viewLifecycleOwner`) — 🔴 Blocking. Leaks the Fragment.

---

## Binding Pattern

Bindings connect Store state changes to UI updates. They extend `AbstractBinding<State>` from mozilla-components and are lifecycle-managed automatically.

```kotlin
class SearchSelectorBinding(
    private val toolbarView: HomeToolbarView,
    browserStore: BrowserStore,
) : AbstractBinding<BrowserState>(browserStore) {

    override suspend fun onState(flow: Flow<BrowserState>) {
        flow.map { it.search.selectedOrDefaultSearchEngine }
            .distinctUntilChanged()
            .collect { engine ->
                toolbarView.updateSearchEngine(engine)
            }
    }
}
```

### Review flags

- **Binding missing `distinctUntilChanged()` on observed state slice** — 🟡 Warning. Without it, UI updates fire on every state emission.
- **Binding containing business logic** (dispatching actions, calling use cases) — 🟡 Warning. Bindings should only map state to UI. Side effects belong in Middleware.

---

## `fragmentStore` / StoreProvider

Screen-scoped Stores are persisted across configuration changes using `StoreProvider`, not ViewModel. This is the standard Firefox pattern.

```kotlin
// In Fragment — store survives config changes automatically
private val store by fragmentStore(SearchFragmentState()) { restoredState ->
    SearchFragmentStore(
        initialState = restoredState,
        middleware = listOf(
            SearchMiddleware(requireComponents.core.engine),
            SearchTelemetryMiddleware(),
        ),
    )
}
```

### Review flags

- **Creating Store directly in Fragment without `fragmentStore` / `StoreProvider`** — 🟡 Warning. Store will be recreated on config change, losing state.

---

## Jetpack Compose Migration

Firefox is incrementally migrating from Fragment + View to Compose. Mixed codebases have specific pitfalls.

### Interop boundary rules

```kotlin
// Correct: ComposeView inside a Fragment
class MyFragment : Fragment() {
    override fun onCreateView(...) = ComposeView(requireContext()).apply {
        setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed)
        setContent { MyScreen(store = store) }
    }
}
```

### Dispatching actions from Composables

In Firefox, dispatching actions directly from Composable onClick lambdas **is the correct pattern**. This differs from the general Android convention of routing through a ViewModel. Per the canonical `HistoryFragmentExample.kt`:

```kotlin
@Composable
private fun HistoryScreen(store: HistoryStore) {
    val state = store.observeAsState(initialValue = HistoryState.initial) { it }
    LazyColumn {
        items(state.displayItems) { item ->
            HistoryItem(
                item = item,
                onClick = { store.dispatch(HistoryAction.OpenItem(item)) },  // correct
            )
        }
    }
}
```

> **Override:** This supersedes the general ARCH check that flags "business logic in a Composable." In Firefox, Composables dispatch Actions; Middleware handles the side effects.

### Review flags

- **`ViewCompositionStrategy` not set on `ComposeView`** — 🔴 Blocking in Fragment context. Without it, the Composition is disposed on every `onDestroyView`, causing memory leaks and state loss during back stack operations.
- **Accessing `FragmentManager` from inside a Composable** — 🟡 Warning. Pass navigation callbacks as lambdas; composables shouldn't know about Fragment transactions.
- **`LocalContext.current as Activity`** — 🟡 Warning. This cast fails in preview and test; use `as? Activity ?: return`.
- **`collectAsState()` without lifecycle awareness for long-running flows** — 🟡 Warning. For flows that outlive the visible UI, prefer `collectAsStateWithLifecycle()` or `observeAsComposableState`.

---

## Proto DataStore Migration

Firefox is migrating from `SharedPreferences` to `Proto DataStore`. Flag any code that regresses this.

### Correct usage

```kotlin
// Reading — always via Flow, never blocking
val setting: Flow<Boolean> = dataStore.data
    .catch { e -> if (e is IOException) emit(AppSettings.getDefaultInstance()) else throw e }
    .map { it.someFlag }

// Writing — suspend function, never runBlocking
suspend fun updateFlag(value: Boolean) {
    dataStore.updateData { current -> current.toBuilder().setSomeFlag(value).build() }
}
```

### Review flags

- **`runBlocking { dataStore.data.first() }`** — 🔴 Blocking. ANR on main thread, deadlock in tests. Must be `suspend` or consumed as `Flow`.
- **DataStore accessed outside a coroutine scope** — 🔴 Blocking.
- **`SharedPreferences` still written in a class that has a DataStore counterpart** — 🟡 Warning. Flag as migration regression.
- **Missing `.catch { }` on `dataStore.data`** — 🟡 Warning. DataStore can throw `IOException` on corrupt/missing files.
- **Proto schema change without migration** — 🟡 Warning. Removing or renaming a field without a migration strategy causes silent data loss on upgrade.

---

## Navigation Patterns

Firefox uses Android Navigation Component with typed helpers. `HomeActivity` is the single NavHost container.

- **`Fragment.nav()`** — Mozilla extension for safe navigation with crash-safe `NavController` access. Prefer over raw `findNavController().navigate()`.
- **`BrowserDirection`** — Enum indicating which fragment is opening the browser (28+ sources).
- **`GlobalDirections`** — Enum for common navigation targets (Home, Bookmarks, History, Settings) with pre-configured `NavDirections`.

### Review flags

- **Using `findNavController().navigate()` directly instead of `nav()` helper** — 🔵 Suggestion. The `nav()` extension handles edge cases and crash safety.

---

## Settings Wrapper

`Settings.kt` wraps `SharedPreferences` with typed Kotlin delegates (`counterPreference`, `featureFlagBooleanPreference`, `lazyBooleanPreference`). Access via `context.settings()`.

### Review flags

- **Bypassing `Settings` wrapper to access `SharedPreferences` directly** — 🟡 Warning. All preference access should go through `Settings` for consistency, type safety, and feature flag support.

---

## Testing Conventions

- Firefox uses **JUnit 4** (not 5) with **MockK** for mocking and **Robolectric** for Android framework emulation. Don't suggest JUnit 5 migrations.
- Coroutine tests use **`runTest`** with **`UnconfinedTestDispatcher()`** for synchronous store dispatch testing.
- GeckoView-dependent code requires device tests (`@UiThreadTest` / Espresso) — pure business logic tests should be pure JUnit with no GeckoView dependency.

### Store testing

```kotlin
@Test
fun `WHEN ToggleFeature dispatched THEN feature is toggled in state`() = runTest {
    val store = LabsStore(initialState = LabsState.INITIAL, middleware = listOf())
    store.dispatch(LabsAction.ToggleFeature(feature))
    assertTrue(store.state.labsFeatures.first().enabled)
}
```

### Middleware testing with `CaptureActionsMiddleware`

```kotlin
@Test
fun `WHEN Init dispatched THEN features loaded from settings`() =
    runTest(UnconfinedTestDispatcher()) {
        val capture = CaptureActionsMiddleware<LabsState, LabsAction>()
        createStore(captureMiddleware = capture, scope = backgroundScope)

        capture.assertLastAction(LabsAction.UpdateFeatures::class) { action ->
            assertEquals(1, action.features.size)
        }
    }
```

### Test middleware injection

```kotlin
// Inject a test middleware to observe dispatched actions without real side effects
var initObserved = false
val spy: Middleware<LabsState, LabsAction> = { _, next, action ->
    if (action == LabsAction.InitAction) initObserved = true
    next(action)
}
LabsStore(initialState = LabsState.INITIAL, middleware = listOf(spy))
assertTrue(initObserved)
```

### Telemetry testing

Use `FenixGleanTestRule` from `helpers/` when testing Glean telemetry pings. It initializes WorkManager and Glean in test mode.

### Review flags

- **`Thread.sleep()` in tests** — 🟡 Warning. Use `TestCoroutineScheduler.advanceTimeBy()`.
- **`runBlocking` in tests** — 🟡 Warning. Use `runTest`.

---

## Naming Conventions

| Pattern | Convention |
|---|---|
| Screen composable | `FooScreen.kt` — one top-level `@Composable fun FooScreen(...)` |
| Store | `FooStore` — one per screen, created via `fragmentStore` |
| State class | `FooState` (new) or `FooFragmentState` (legacy) |
| Action | `FooAction` sealed class |
| Reducer | `fooReducer` — top-level function, referenced as `::fooReducer` |
| Middleware | `FooMiddleware` — class implementing `Middleware<S, A>` |
| Controller | `DefaultFooController` implementing `FooController` interface |
| Interactor | `FooInteractor` — delegates to one or more Controllers |
| Binding | `FooBinding` extending `AbstractBinding<State>` |
| ViewModel | `FooViewModel` — rare; most state lives in Stores. Only for cases requiring Android ViewModel lifecycle |
| Repository | `FooRepository` interface + `DefaultFooRepository` impl |
