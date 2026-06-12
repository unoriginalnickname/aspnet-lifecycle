# Project History

Chronological log of what was done each session, why, and what comes next.

---

## Session 1 — 11 Jun 2026

### Starting point
Existing project with three overview documents (`aspnet-01-quick.md`, `aspnet-02-indepth.md`, `aspnet-03-reference.md`) and a `UseRouting.md` deep dive. Content was accurate but structured as flat documents rather than a navigable reference.

### What was built
- `build.py` — generates `aspnet.html` from modular `.md` files
- Split into `content/startup/` and `content/per-request/` folder structure
- Initial startup files: `add-controllers.md`, `add-problem-details.md`, `add-db-context.md`, `add-authentication.md`, `add-cors.md`, `add-health-checks.md`, `add-swagger-gen.md`, `service-lifetimes.md`, `ordering-rules.md`, `the-gap.md`, `map-controllers.md`
- Initial per-request files: `exception-handler.md`, `https-redirection.md`, `static-files.md`, `cors.md`, `authentication.md`, `routing.md`, `authorization.md`, `health-check.md`, `controller.md`, `filters.md`, `binding.md`, `your-action.md`, `result.md`, `serialisation.md`
- `guidelines.md` created with initial 11 ambiguity types and writing rules
- HTML tree UI with startup and per-request tabs

### Key decisions
- Startup/per-request split as the organising principle — the most important conceptual distinction in the framework
- Tree navigation reflecting actual pipeline order
- Guidelines written to serve both junior readers and senior reviewers

---

## Session 2 — 12 Jun 2026

### Benchmarking
- Compared against mostlylucid.net Parts 1 and 4 — our content more accurate and deeper; identified their CORS/auth ordering error
- Compared against andrewlock.net — confirmed `UseRouting` auto-insertion mechanics, `IStartupFilter` gap, `UsePathBase` mention
- Compared against aspnetcore.readthedocs.io (1.0 docs) — identified content root vs web root gap
- Compared against official learn.microsoft.com middleware table — systematic coverage audit

### New files added
- `content/per-request/http-context.md` — HttpContext class listing, all properties with when-populated notes; moved to top of per-request tree
- `content/per-request/status-code-pages.md` — UseStatusCodePages, three registration styles, relationship to UseExceptionHandler
- `content/per-request/rate-limiter.md` — four algorithms, partitioning, 429/Retry-After, gap positioning
- `content/per-request/response-caching.md` — UseResponseCompression (BREACH warning), UseResponseCaching, UseOutputCaching (.NET 7+), tag invalidation
- `content/startup/add-http-client.md` — IHttpClientFactory, three patterns, lifetime trap, delegating handlers
- `content/startup/add-logging.md` — ILogger, six levels, structured logging, scopes, LoggerMessage source generator
- `content/startup/environments.md` — ASPNETCORE_ENVIRONMENT, three standard values, practical consequences
- `content/startup/istartupfilter.md` — mechanism, execution order, HostFilteringMiddleware, ForwardedHeadersMiddleware, what breaks

### Files significantly expanded
- `exception-handler.md` — re-execution is internal pipeline re-invocation (not new HTTP request), `IExceptionHandler` (.NET 8), automatic logging mechanism explained (`ExceptionHandlerMiddlewareImpl` + `LoggerMessage`), `HasStarted` caveat, `IExceptionHandlerFeature`, dev page Accept-header behaviour
- `https-redirection.md` — HSTS added, browser vs server distinction, preload warning
- `authorization.md` — step-by-step middleware walkthrough, `IAuthorizationHandler`, resource-based auth, `FallbackPolicy`, 401 vs 403 precise mechanism
- `filters.md` — async variants, `ServiceFilter` vs `TypeFilter`, `IResourceFilter`, full nesting diagram
- `binding.md` — inference rules as numbered steps, `IValidatableObject`, custom `IModelBinder`, `IFormFile` security note
- `result.md` — full result table, `Unauthorized()` vs `Forbid()` mechanism, `CreatedAtAction`, `Problem()`, `TypedResults`
- `your-action.md` — `CancellationToken` injection, sequential vs parallel awaits, `ConfigureAwait` honest assessment
- `health-check.md` — liveness vs readiness, Kubernetes probe YAML, custom ResponseWriter, securing endpoints, `IHealthCheck`
- `controller.md` — `ControllerBase` vs `Controller`, `[ApiController]` behaviours, full `HttpContext`/`User`/`Request` property access, interface/implementation separation explained
- `the-gap.md` — auto-insertion conditions (`IServiceProviderIsService`), suppression rule, CORS exception, terminal middleware positioning, `Startup.Configure` trap

### Tree changes
- `http-context.md` moved to top of per-request tree
- `response-caching.md` moved outside MVC box (it's pipeline middleware, not MVC)
- `health-check.md` moved inside MVC box (it's endpoint middleware)
- `service-lifetimes.md` moved to top of startup phase 1
- `environments.md` moved to end of phase 1 (affects service registration)
- `rate-limiter.md` placed in the gap between routing and authorization

### Guidelines updated
- Types 12–17 added:
  - **12** — vague mutation verbs ("picks up", "attaches", "writes onto")
  - **13** — incomplete step sequence for per-request middleware
  - **14** — false universals ("every", "always" applied to conditional behaviour)
  - **15** — referent displacement (pronoun after noun displacement)
  - **16** — overconstrained rules ("declared first", "must always")
  - **17** — actor erasure (passive construction hiding the actor)
- Type 4 extended to cover vague qualifiers (the "logs internally" case)
- Document structure section updated to all 33 files
- Writing process step 4 updated to name all high-priority types explicitly
- Last updated date: 12 Jun 2026

### Accuracy fixes
- `exception-handler.md` — "logs internally" was ambiguous (type 4 qualifier); verified against `ExceptionHandlerMiddlewareImpl` source — middleware logs automatically via `ILoggerFactory`; rewrote to name the mechanism precisely
- Reverted ChatGPT's incorrect "no automatic logging" claim after source verification
- traceId overclaim ("every log line is tagged") fixed in three files: `exception-handler.md`, `add-problem-details.md`, `http-context.md` — changed to "logging providers can include the traceId when configured"
- `add-controllers.md` — "ordered and used" → "constructed and used"
- `authentication.md` — "typically 15 minutes to 1 hour" removed; replaced with reason tokens are short-lived
- `authentication.md` — "`it` is always the subject" → named `ClaimTypes.NameIdentifier`, added null case
- `map-controllers.md` — referent displacement (`it stamps`) → `RequireAuthorization()` stamps; actor erasure (`it is not built`) → `EndpointRoutingMiddleware` does not compile it
- `controller.md` — "always populated" → "populated by the time your action runs"
- `serialisation.md` — "`Content-Type` is set automatically" → "`ObjectResult` sets `Content-Type` automatically via the output formatter"
- `service-lifetimes.md` — "must always be Scoped" → "must be Scoped"
- `content/exception-handler.md` (top-level stub) — rewritten; was three versions behind with three known inaccuracies
- Clean architecture sweep — `add-db-context.md`, `service-lifetimes.md`, `controller.md` updated to explain interface/implementation separation
- `static-files.md` — content root vs web root distinction added
- Emoji removed from all code comments across all files
- Text contrast improved throughout HTML (body text, table cells, tree labels)

### External review
- ChatGPT reviewed `exception-handler.md` — 9/11 points correct, 2 incorrect (automatic logging claim, re-execution framing)
- Swedish-language review by second reviewer confirmed remaining precision issues; all five points addressed
- Lesson documented: verify every correction against primary sources before accepting — ChatGPT was wrong on the logging claim

### Remaining open items
- andrewlock.net audit: `UsePathBase` mention (we use it as an example in the-gap but don't explain the middleware), `MessageReceived` event hook on `JwtBearerOptions` (token from query string, used by SignalR/WebSockets)
- mostlylucid.net Part 4 comparison: three items from their routing article already added (custom constraints, route priority order, `WithOrder()`); no remaining gaps identified
- The `SyntaxWarning` in `build.py` about `\*` in the markdown renderer regex — pre-existing, low priority
