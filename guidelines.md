# ASP.NET Core Docs — Writing Guidelines
**Last updated:** 12 Jun 2026

---

## Project goal

A complete ASP.NET Core overview that works as a learning resource for junior developers and as a portfolio piece demonstrating deep framework understanding to senior developers reviewing the work.

One sentence: **teach the system accurately and completely, from first principles, with no gaps a senior would notice.**

---

## Audience

**Junior developers** — learning ASP.NET Core. They need:
- Every concept explained from first principles
- Every term defined on first use
- Concrete examples anchoring every abstract claim
- Clear explanations of what breaks and why, not just what to do

**Senior developers reviewing the portfolio** — evaluating depth of understanding. They will notice:
- Gaps in coverage
- Inaccurate or oversimplified explanations
- Missing edge cases
- Shallow treatment of internal mechanics

They expect to see: the DFA, the auto-insertion sandwich, the silent security holes, the runtime guard, the captive dependency trap, the misplacement bug — the things that separate someone who has used the framework from someone who understands it.

**How the split layout serves both:** the tree gives juniors the picture quickly. The detail panels give seniors the depth. A junior reads the brief label and optionally goes deeper. A senior clicks straight to the parts that reveal understanding.

---

## Document structure

```
aspnet.html                  ← generated output, open in any browser, works offline
build.py                     ← run after editing any .md file: python3 build.py
content/
  startup/                   ← one .md file per startup concept
    add-controllers.md
    add-problem-details.md
    add-db-context.md
    add-authentication.md
    add-cors.md
    add-health-checks.md
    add-swagger-gen.md
    add-http-client.md
    add-logging.md
    service-lifetimes.md
    environments.md
    ordering-rules.md
    the-gap.md
    map-controllers.md
    istartupfilter.md
  per-request/               ← one .md file per request lifecycle layer
    http-context.md
    exception-handler.md
    status-code-pages.md
    https-redirection.md
    static-files.md
    cors.md
    authentication.md
    routing.md
    rate-limiter.md
    authorization.md
    health-check.md
    controller.md
    filters.md
    binding.md
    your-action.md
    result.md
    response-caching.md
    serialisation.md
```

**Adding a new topic:** create a `.md` file in the correct folder, add an entry to `build.py`'s file dict, add a tree node to the HTML in `build.py`. Run `python3 build.py`.

---

## Content ownership — where specific source material belongs

The `UseRouting.md` deep dive maps to the following files:

| Content | File |
|---|---|
| What `MapControllers()` builds at startup — routing table, `RouteEndpoint`, `EndpointMetadataCollection`, attributes as metadata, link generation, DFA | `startup/map-controllers.md` |
| The two internal middlewares, why `UseRouting()` alone is insufficient, `WebApplication` auto-insertion mechanics, `Startup.Configure` trap, runtime guard | `startup/the-gap.md` |
| `UseAuthorization` misplacement consequence, runtime guard fooled by misplacement, `[AllowAnonymous]` overriding `[Authorize]` via metadata | `startup/ordering-rules.md` |
| Per-request: candidate matching, constraint evaluation, `SetEndpoint()`, `RouteValues`, `IEndpointSelectorPolicy`, `MapShortCircuit()` edge case | `per-request/routing.md` |

---

## The startup / per-request rule

Startup and per-request are different moments. Never describe them in the same breath without making the relationship explicit.

**Startup files** say: what you register, what that makes available, and why the registration exists.

**Per-request files** say: given that registration, what happens when a request arrives.

When a file spans both, the connection must be stated explicitly:

> "Because `UseAuthentication()` was registered in startup, when a request arrives the JWT in the `Authorization: Bearer ...` header is verified and `HttpContext.User` is populated with the caller's identity."

Never describe runtime behaviour as if it belongs to startup configuration. Never describe startup configuration as if it runs per-request.

---

## Depth rule

**Maximum depth.** Cover the subject completely. No artificial length limit — if the subject requires ten paragraphs, write ten. The split layout gives the detail panel as much room as it needs.

Every content file must cover:
- What it is — plain English, junior-accessible
- Why it exists — what problem it solves
- How to configure it (startup) or what it does at request time (per-request)
- What breaks if you get it wrong, and why — with the specific failure mode named
- Edge cases a senior would expect to see
- At least one concrete code example

**No padding.** Every sentence must earn its place. If removing it leaves a junior unable to do or understand something real, keep it. If not, cut it.

---

## Ambiguity — seventeen types to check before marking a file done

**1. Undefined terms**
A word or concept used before it has been explained.
> ❌ "The container resolves the service."
> ✓ "The DI container — the object that creates and manages your services — builds the instance."

**2. Jargon without context**
A technical word whose meaning is not obvious from the word itself.
> ❌ "Must be thread-safe."
> ✓ "Multiple requests share this instance simultaneously — it must not store per-request state."

**3. Implicit causation**
Stating what happens without what causes it, or a rule without the consequence of breaking it.
> ❌ "`UseAuthorization` must come after `UseRouting`."
> ✓ "If `UseAuthorization` runs before `UseRouting`, it finds no endpoint metadata and silently skips — every `[Authorize]` route becomes publicly accessible, no error."

**4. Vague pronouns and qualifiers**
"It", "this", "they", "that" with an unclear referent — or adverbs and qualifiers that appear specific but support two contradictory readings.
> ❌ "It reads the metadata and evaluates it."
> ✓ "`UseAuthorization` reads the `[Authorize]` attribute on the matched action and evaluates it against `HttpContext.User`."

Vague qualifiers are a subtler version of the same problem. A word like "internally" looks precise but leaves the reader to decide what it modifies:
> ❌ "Catches the exception, logs it internally using the app's logging infrastructure."
> — Does "internally" mean the middleware itself logs automatically? Or that logging happens inside your own code using the infrastructure? Both readings are grammatically valid.
> ✓ "`ExceptionHandlerMiddlewareImpl` injects `ILoggerFactory`, creates its own `ILogger`, and fires a pre-compiled `LoggerMessage` at `LogLevel.Error` — the exception is logged automatically by the middleware, not by your code."

The test: read the sentence and ask whether a reader who misunderstands it would have done so unreasonably. If the wrong reading is grammatically valid and plausible, the sentence is ambiguous regardless of your intent.

**5. Unstated assumptions**
Assuming the reader knows something that has not been established in this document.
> ❌ "JWT bearer authentication is configured in `AddAuthentication()`."
> ✓ "JWT bearer authentication — verifying the token in `Authorization: Bearer ...` — is configured in `AddAuthentication().AddJwtBearer()`."

**6. Missing consequences**
A rule stated without what breaks if you don't follow it.
> ❌ "`DbContext` is always Scoped."
> ✓ "`DbContext` is always Scoped — it holds a database connection that must not be shared between requests. Registering it as Singleton corrupts data under concurrent load."

**7. Mixed timelines**
Startup behaviour described as runtime, or runtime behaviour described as startup.
> ❌ (in a startup file) "Authentication populates `HttpContext.User` with the caller's identity."
> ✓ (in a startup file) "`UseAuthentication()` registers the JWT verification middleware — at request time it verifies the token and populates `HttpContext.User`."

**8. Vague quantifiers**
"Slightly", "often", "usually", "some", "many", "a bit" without specifics.
> ❌ "The first request is slightly slower."
> ✓ "The first request after deployment is slower because the URL map compiles on first use — subsequent requests are not affected."

**9. Abstract without concrete**
A claim or description with no example to anchor it.
> ❌ "Binding sources are inferred automatically."
> ✓ "Binding sources are inferred automatically — a class like `CreateUserRequest` comes from the JSON body; a primitive like `int id` comes from the route or query string."

**10. Incomplete causation**
Something described as required or forbidden without the mechanism that enforces it.
> ❌ "You cannot register services after `Build()`."
> ✓ "You cannot register services after `Build()` — the container is frozen and any registration after that point is silently ignored."

**11. Incomplete causal chain**
An outcome stated without every actor in the chain that produces it. Ask: what actually causes this result, step by step? If any step is skipped and that step has a different actor, rule, or condition, name it.
> ❌ "Authorization returns 401 if the user is not authenticated."
> ✓ "Authorization calls `ChallengeAsync()` on the JWT bearer scheme, which returns `401 Unauthorized`. A different scheme — such as cookies — responds to the same challenge with a redirect."

This type catches statements that are true at a surface level but skip intermediate steps. The test: trace the outcome back through every actor. If an intermediate actor has its own rules or conditions that affect the result — name it.

**12. Vague mutation verbs**
Using imprecise verbs — "picks up", "attaches", "writes onto", "reads from", "stores", "puts" — where a specific method call, property name, or storage location exists and should be named.
> ❌ "Routing attaches the matched endpoint to `HttpContext`."
> ✓ "Routing calls `HttpContext.SetEndpoint(endpoint)`, which stores the `Endpoint` object on `HttpContext.Features` under `IEndpointFeature`."

> ❌ "`UseAuthorization` reads the policy from the endpoint."
> ✓ "`UseAuthorization` calls `endpoint.Metadata.GetOrderedMetadata<IAuthorizeData>()` to retrieve the `[Authorize]` attribute instances stamped onto the endpoint at startup."

The test: if a specific method, property, or interface name exists for the operation being described, use it. Vague verbs are acceptable only when no specific API exists — e.g. "the browser attaches an `Origin` header" is correct because there is no method name to cite.

**13. Incomplete step sequence for per-request middleware**
Per-request middleware files that describe what a middleware does without breaking it into the sequential steps it actually performs. Middleware that reads credentials, evaluates conditions, and makes decisions has a clear internal order — describe it as steps.
> ❌ "Authentication verifies the JWT and populates `HttpContext.User`."
> ✓ "Step 1 — Read the token from the `Authorization: Bearer …` header. Step 2 — Decode the header and payload. Step 3 — Fetch the signing keys from the JWKS endpoint…"

This applies to any per-request file where the middleware has a sequential evaluation process: authentication, authorization, routing, model binding. Not required for pass-through middleware (HTTPS redirection, static files) where the logic is a single condition rather than a sequence.

**14. False universals**
"Every", "always", "all", "never" applied to behaviour that is actually conditional on configuration, version, or provider.
> ❌ "Every log line is tagged with the same ID."
> ✓ "Logging providers can include the traceId in log entries — when configured, every log line carries the same ID."

The test: ask whether the claim holds if a specific provider, version, or configuration is absent. If not, the universal is false. This is the opposite failure mode from type 8 (vague quantifiers) — instead of understating with "typically", it overstates with "every" or "always."

**15. Referent displacement**
A pronoun that appears to follow its referent but another noun has entered the sentence since, making the reference ambiguous. Distinct from type 4 because the referent *was* named — it was displaced, not absent.
> ❌ "`AddProblemDetails()` must be called before `builder.Build()` — it registers the formatter."
> ✓ "`AddProblemDetails()` must be called before `builder.Build()` — `AddProblemDetails()` registers the formatter."

The test: identify every noun introduced between the last naming of the intended referent and the pronoun. If any of those nouns could plausibly be "it", the referent has been displaced. The fix is always to repeat the name rather than use the pronoun.

**16. Overconstrained rules**
A rule stated more strictly than it actually is — implying a hard requirement where a softer one exists, or implying the only valid approach when alternatives exist.
> ❌ "Declared first so it wraps every other middleware."
> ✓ "Placed early in the pipeline so it wraps the middleware that follows."
> ❌ "`DbContext` is always Scoped."
> ✓ "`DbContext` must be Scoped — registering it as Singleton causes connection leaks and change tracker corruption under concurrent load."

The test: ask whether there is any valid configuration under which the stated constraint does not apply. If yes, the rule is overconstrained. "Declared first" fails this test because `UseForwardedHeaders` legitimately precedes it. The fix is not to weaken the rule but to state it accurately — often replacing a position claim with a relationship claim ("must precede X" rather than "must be first").

**17. Actor erasure**
Passive construction that removes the actor performing an operation, leaving the reader unable to determine what causes the behaviour. Distinct from type 12 (vague mutation verbs) because the verb may be precise — "cleared", "reset", "populated" are specific — but the actor is absent entirely.
> ❌ "The response is cleared and route data is reset before re-invocation."
> ✓ "`UseExceptionHandler` clears the response body and resets route data on `HttpContext` before re-invoking the pipeline."

> ❌ "`HttpContext.User` is populated after authentication runs."
> ✓ "`UseAuthentication` populates `HttpContext.User` by building a `ClaimsPrincipal` from the verified token's claims."

The test: for any passive verb, ask who performs the action. If the answer is not in the sentence and matters for understanding, name the actor. Passive voice is acceptable when the actor genuinely doesn't matter — "the response body is written to the network" is fine because the underlying Kestrel mechanism is not relevant at this level of description.

---

## Concrete examples rule

Abstract terms get an inline example, not a definition. The example does the explaining.

> ❌ "URL + HTTP method"
> ✓ "e.g. `GET /api/users/5`"

> ❌ "complex type"
> ✓ "a class like `CreateUserRequest`"

---

## Code examples rule

- Wrong and right shown in the same annotated block where the concept involves a common mistake
- Code spanning multiple real files is labelled with the filename — `// Program.cs`, `// UserService.cs`
- Related examples combined into one annotated block rather than separate fragments
- Every example must be real — no pseudocode, no placeholder logic that would fail to compile

---

## Writing process

1. Decide which file the content belongs in before writing
2. Check the startup/per-request rule — is this a configuration fact or a runtime fact?
3. Write to maximum depth
4. Check all seventeen ambiguity types — pay particular attention to type 11 (incomplete causal chain) for any statement describing an outcome: trace it back through every actor and intermediate step; type 12 (vague mutation verbs) for any sentence describing what a middleware reads, writes, or stores; type 13 (incomplete step sequence) for any per-request middleware with a sequential evaluation process; type 14 (false universals) for any sentence containing "every", "always", "all", or "never"; type 15 (referent displacement) whenever a pronoun follows a sentence containing more than one noun; type 16 (overconstrained rules) for any rule stated as an absolute position or requirement; and type 17 (actor erasure) for any passive construction where the actor matters
5. Check code examples are real and annotated correctly
6. Run `python3 build.py` and verify in the browser

---

## Out of scope

- Testing
- Configuration and secrets (`appsettings.json`, environment variables, secrets manager)
- Deployment
- Minimal APIs
