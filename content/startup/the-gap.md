## The gap

The gap is the deliberate space between `UseRouting()` and `MapControllers()` in the pipeline. Middleware registered in this space has a specific property: routing has already matched the request to an endpoint, but that endpoint has not yet executed. The middleware knows the destination and can act on that knowledge before the action runs.

### Why the gap exists — two middlewares, one system

Before ASP.NET Core 3.0, the MVC middleware combined route matching and action execution in a single step. You could place middleware before or after MVC entirely, but not between matching and execution.

In ASP.NET Core 3.0 the team split this into two separate internal middleware classes:

- `EndpointRoutingMiddleware` — matches the URL, writes the result onto `HttpContext`, calls `next()`
- `EndpointMiddleware` — reads that result from `HttpContext`, executes the matched endpoint

You never reference either class directly. They are internal. The public API that registers them is:

- `UseRouting()` — registers `EndpointRoutingMiddleware` at that position
- Any `Map…()` call — `MapControllers()`, `MapGet()`, `MapHealthChecks()`, etc. — each registers `EndpointMiddleware`

The gap is the space between the two. Any middleware placed there can call `HttpContext.GetEndpoint()` and read:

- `DisplayName` — e.g. `"UsersController.GetUser (MyApi)"`
- `Metadata` — the `EndpointMetadataCollection` built at startup, containing all `[Authorize]`, `[EnableCors]`, `[EnableRateLimiting]` objects
- `HttpContext.Request.RouteValues` — e.g. `{ id: "5" }` extracted from `GET /api/users/5`

```csharp
app.UseRouting();

// ── gap ──────────────────────────────────────────────────────────────
// routing has run — GetEndpoint() returns the matched action

app.UseAuthorization();   // reads [Authorize] from endpoint metadata

app.UseRateLimiter();     // can key the rate limit on a route value:
                          // e.g. limit by {tenantId} from the URL

app.Use(async (ctx, next) =>
{
    // enrich logs with the matched action name — only possible after routing
    var action = ctx.GetEndpoint()?.DisplayName ?? "unknown";
    using var _ = logger.BeginScope("action={Action}", action);
    await next(ctx);
});
// ─────────────────────────────────────────────────────────────────────

app.MapControllers();
```

Placing middleware before `UseRouting()` means `GetEndpoint()` returns null — the match has not happened yet.

### WebApplication auto-insertion (.NET 6+)

In .NET 6+, `WebApplication` (the default hosting model) automatically inserts middleware into the pipeline for you. You do not have to call `UseRouting()`, `UseAuthentication()`, or `UseAuthorization()` yourself — the framework detects whether they are needed and injects them in the correct positions.

The precise conditions under which each is injected:

- **`UseRouting`** — injected if any endpoints are configured (e.g. `MapControllers()` has been called) and you have not already called `UseRouting()` yourself.
- **`UseAuthentication`** — injected immediately after `UseRouting` if `IAuthenticationSchemeProvider` is detectable in the DI container (which `AddAuthentication()` registers), and you have not already called `UseAuthentication()` yourself.
- **`UseAuthorization`** — injected next if `IAuthorizationHandlerProvider` is detectable in the DI container (which `AddAuthorization()` registers), and you have not already called `UseAuthorization()` yourself.
- **`UseEndpoints`** — injected at the end of the pipeline if any endpoints are configured.

The detection uses `IServiceProviderIsService` — the framework calls `IsService<IAuthenticationSchemeProvider>()` to check whether `AddAuthentication()` was called, and `IsService<IAuthorizationHandlerProvider>()` to check whether `AddAuthorization()` was called. No service registration means no auto-insertion.

The effective pipeline that results:

```
UseRouting          ← injected before your code
UseAuthentication   ← injected after UseRouting (if AddAuthentication() was called)
UseAuthorization    ← injected after UseAuthentication (if AddAuthorization() was called)
--- your middleware and Map…() calls ---
UseEndpoints        ← injected at the end
```

**The suppression rule:** if you call any of these explicitly yourself, auto-injection for that specific middleware is suppressed — your explicit call takes the position you chose. The framework does not insert it a second time. This is what makes explicit calls safe — you are not duplicating middleware, you are overriding the injected position with your own.

**Minimal example — writing nothing:**

```csharp
// What you write in Program.cs:
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddAuthentication(...);  // registers IAuthenticationSchemeProvider
builder.Services.AddAuthorization();      // registers IAuthorizationHandlerProvider
builder.Services.AddControllers();

var app = builder.Build();
app.MapControllers();  // registers endpoints — triggers UseRouting and UseEndpoints injection
app.Run();
```

Effective pipeline at runtime — none of these were written explicitly:

```csharp
app.UseRouting();        // injected — endpoints are configured
app.UseAuthentication(); // injected — IAuthenticationSchemeProvider found in DI
app.UseAuthorization();  // injected — IAuthorizationHandlerProvider found in DI
app.MapControllers();    // your call
app.UseEndpoints(...);   // injected at the end
```

**Explicit calls — suppression in action:**

```csharp
// What you write:
app.UseAuthentication();   // explicit — suppresses auto-injection of UseAuthentication
app.UseAuthorization();    // explicit — suppresses auto-injection of UseAuthorization
app.MapControllers();
```

Effective pipeline at runtime:

```csharp
app.UseRouting();          // still injected — you didn't call it, endpoints are configured
app.UseAuthentication();   // your explicit call, in the position you chose
app.UseAuthorization();    // your explicit call
app.MapControllers();
app.UseEndpoints(...);     // still injected at the end
```

`UseAuthorization` ends up after `UseRouting` in both cases — whether you write it explicitly or let it be injected. This is why most .NET 6+ apps work correctly without an explicit `UseRouting()` call.

**The CORS exception — when auto-insertion breaks down:**

`UseCors()` must run before `UseAuthentication` and `UseAuthorization` — a preflight `OPTIONS` request carries no credentials, and if auth runs first it may challenge the preflight before CORS headers are added. When you call `UseCors()` explicitly, you are placing it at a specific position in your user code. But your user code sits *after* the auto-injected `UseAuthentication` and `UseAuthorization`, which means CORS would run after auth — the wrong order.

The fix is to also call `UseAuthentication` and `UseAuthorization` explicitly, placing all three in the correct order yourself:

```csharp
// WRONG — UseCors() is in user code, which runs AFTER auto-injected auth:
// Effective pipeline: UseRouting → UseAuthentication (injected) → UseAuthorization (injected)
//                     → UseCors() (your code) → MapControllers
app.UseCors("MyPolicy");   // too late — auth already ran
app.MapControllers();

// Correct — call all three explicitly to control the order:
app.UseCors("MyPolicy");       // before auth
app.UseAuthentication();       // explicit — suppresses auto-injection
app.UseAuthorization();        // explicit — suppresses auto-injection
app.MapControllers();
// Effective pipeline: UseRouting (injected) → UseCors → UseAuthentication → UseAuthorization
//                     → MapControllers → UseEndpoints (injected)
```

Any time you need to control the position of a middleware relative to the auto-injected auth pair, call `UseAuthentication()` and `UseAuthorization()` explicitly. The suppression rule means you are not duplicating them — you are taking ownership of their positions.

### When to call UseRouting() explicitly in a WebApplication app

Calling `UseRouting()` explicitly suppresses auto-insertion and fixes routing at exactly that position. In a `WebApplication` app, this moves routing **later** in the pipeline — not earlier — because auto-insertion would have placed it at position 2, before everything.

The only reason to call it explicitly is when you need middleware to run before routing sees the URL — for example, rewriting the path:

```csharp
// path rewriting before routing:
app.Use(async (ctx, next) =>
{
    // rewrite /api/v1/users → /api/users before routing matches
    if (ctx.Request.Path.StartsWithSegments("/api/v1"))
        ctx.Request.Path = "/api" + ctx.Request.Path.Value![7..];
    await next(ctx);
});

app.UseRouting();       // explicit — suppresses auto-insert, routing happens here
app.UseAuthorization();
app.MapControllers();
```

```csharp
// MISTAKE — developer expects this to run before routing
// but auto-insertion already placed UseRouting before all user middleware:
app.Use(async (ctx, next) =>
{
    ctx.Request.Path = "/api" + ctx.Request.Path;  // too late — routing already ran
    await next(ctx);
});
app.MapControllers();
```

### Terminal middleware

Terminal middleware handles requests that no endpoint matched — it runs when `GetEndpoint()` returns `null` after routing has completed. The canonical use is returning a custom 404 response instead of the framework default.

Placing terminal middleware correctly requires understanding where `UseEndpoints` sits. In a `WebApplication` app, `UseEndpoints` is auto-injected at the end of the pipeline. Terminal middleware must go *after* `UseEndpoints` — and to place something after an auto-injected middleware, you must call `UseRouting()` and `UseEndpoints()` explicitly, which gives you a fixed anchor to place your terminal middleware after:

```csharp
app.UseRouting();           // explicit — fixes routing position

app.MapControllers();       // register endpoints

app.UseEndpoints(e => {});  // explicit — fixes UseEndpoints position

// terminal middleware — only runs if no endpoint matched
app.Run(async ctx =>
{
    ctx.Response.StatusCode = 404;
    await ctx.Response.WriteAsJsonAsync(new ProblemDetails
    {
        Status = 404,
        Title  = "The requested resource was not found."
    });
});
```

Without the explicit `UseEndpoints()` call, `UseEndpoints` is auto-injected at the very end of the pipeline — *after* your terminal middleware — so the terminal middleware would run before any endpoint has had a chance to handle the request, returning 404 for everything. The explicit call pins `UseEndpoints` at the position you choose and lets your terminal middleware sit after it.

### The Startup.Configure trap (pre-.NET 6 or explicit host builder)

In the older `Startup.Configure` pattern — and in any .NET 6+ app that uses an explicit host builder instead of `WebApplication` — there is no auto-insertion. The pipeline is exactly what you write, with one dangerous exception.

If you call a `Map…()` method without having called `UseRouting()` first, `EndpointRoutingMiddleware` is silently inserted **at the `Map…()` position** — not at the start of the pipeline. This creates a security hole:

```csharp
// WRONG — Startup.Configure. No error, no warning:
app.UseAuthorization();  // GetEndpoint() returns null — routing hasn't run yet
app.MapControllers();    // EndpointRoutingMiddleware silently inserted here

// Effective pipeline at runtime:
// UseAuthorization          → GetEndpoint() null → no metadata → auth silently skipped
// EndpointRoutingMiddleware → inserted at MapControllers() position
// EndpointMiddleware        → executes the action
//
// Result: every [Authorize] route is publicly accessible
```

```csharp
// Correct — Startup.Configure:
app.UseAuthentication();
app.UseRouting();        // explicit — EndpointRoutingMiddleware here
app.UseAuthorization();  // after routing
app.MapControllers();
```

### The runtime guard — what it catches and what it misses

`EndpointMiddleware` has a runtime check: before executing an endpoint whose metadata contains `[Authorize]`, it looks for a key on `HttpContext.Items` that `AuthorizationMiddleware` sets whenever it runs — regardless of whether it found a policy. If the key is absent, it throws:

> Endpoint UsersController.GetUser contains authorization metadata, but a middleware was not found that supports authorization. Configure your application startup by adding app.UseAuthorization() in the application startup code.

This catches **omission** — `UseAuthorization()` not called at all.

It does **not** catch **misplacement** — `UseAuthorization` placed before `UseRouting` in a `Startup.Configure` host. `AuthorizationMiddleware` ran (it was just in the wrong position), set its key on `HttpContext.Items`, and the guard sees the key and is satisfied. The fact that `GetEndpoint()` returned `null` and no policy was evaluated is invisible to the guard. Every `[Authorize]` route is publicly accessible and nothing throws.

In a `WebApplication` app this trap is much harder to trigger accidentally — auto-insertion puts `UseRouting` before your code. You would have to explicitly call `UseAuthorization()` before an explicit `UseRouting()` to recreate it.
