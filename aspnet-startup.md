# ASP.NET Core — Startup
**Last reviewed:** 11 Jun 2026 · **Version baseline:** .NET 8

Startup runs **once**, when the process starts. It has nothing to do with requests — no request exists yet, no middleware has run, nothing has been constructed. Its only job is to build the system that will handle requests later.

It has two phases that must happen in order and cannot be mixed.

---

## Phase 1 — Register services

This is the configure phase. You are writing a recipe book, not cooking. Each `Add…()` call writes a recipe into the DI container: "when something asks for `IUserService`, here is how to make one." Nothing is constructed. No connections are opened. The container just holds descriptions.

```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();       // registers the entire MVC stack — routing, binding, filters, JSON
builder.Services.AddProblemDetails();    // registers the RFC 7807 error formatter
builder.Services.AddScoped<IUserService, UserService>();  // your own services
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("Default")));
```

**Why a recipe book and not a kitchen?** The container needs to see the *complete* set of recipes before it can safely construct anything. If objects could be built while new recipes were still being added, some objects would be constructed without knowing about later registrations — producing inconsistent, unpredictable behaviour. So phase 1 is write-only. Phase 2 is when cooking begins.

### What `AddControllers()` registers

One call puts the entire MVC stack on the menu — none of it constructed yet:

- The **routing system** — matches incoming URLs to controller actions
- The **model binder** — extracts values from the request (route segments, query string, JSON body) and maps them onto action parameters
- The **action invoker** — calls your method
- The **filter pipeline** — auth filters, action filters, exception filters, result filters
- The **JSON serialiser** (`System.Text.Json` by default) — converts your C# return values to bytes
- **`[ApiController]` behaviours** — automatic 400 responses on validation failure, binding source inference

### What `AddProblemDetails()` registers

The RFC 7807 error formatter — the recipe for turning an unhandled exception into a consistent `{ type, title, status, traceId }` JSON shape. Without this on the menu, `UseExceptionHandler()` in the pipeline has no formatter to call and cannot produce the standardised error response.

### Service lifetimes

The container manages object creation for you — you never call `new UserService()` directly. Instead you declare what you need and the container builds it. This means you can swap implementations, inject mocks in tests, and avoid manually wiring up dependency trees. The tradeoff is that you must tell the container how long each object should live.

**Singleton 🟢** — one instance for the entire app lifetime, shared across all requests and threads. Must be thread-safe. Use for stateless services: config, caches, HTTP clients.

**Scoped 🔵** — one instance per HTTP request. Created when the request scope opens, disposed when it ends. `DbContext` must always be Scoped — it holds a database connection and tracks changes for a single unit of work. Sharing it across requests corrupts data.

**Transient 🟣** — new instance every time it is resolved from the container. Use for lightweight, stateless helpers. Avoid for anything that holds connections or is expensive to construct.

### Common registration patterns

```csharp
// Interface → implementation, three lifetimes:
builder.Services.AddSingleton<ICache, MemoryCache>();      // one instance for the app
builder.Services.AddScoped<IUserService, UserService>();   // one per request
builder.Services.AddTransient<IEmailSender, SmtpSender>(); // new every time

// DbContext — always Scoped, never Singleton:
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("Default")));

// Named HTTP client:
builder.Services.AddHttpClient("PermissionsApi", c =>
    c.BaseAddress = new Uri("https://permissions.internal/"));

// JSON options — must be configured here, before Build():
builder.Services.AddControllers()
    .AddJsonOptions(o => {
        o.JsonSerializerOptions.PropertyNamingPolicy   = JsonNamingPolicy.CamelCase;
        o.JsonSerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
    });
```

**The captive dependency trap:** inject a Scoped service into a Singleton and the Scoped instance is captured — it lives for the lifetime of the app instead of the lifetime of the request, leaking state between requests. ASP.NET detects this in development and throws. In production it is silent by default. Enable it explicitly:

```csharp
// Program.cs — ❌ Wrong: IMyCache is Singleton, IUserRepository is Scoped.
// The Scoped instance gets captured inside the Singleton and lives forever —
// the same IUserRepository is shared across every request for the app's lifetime.
builder.Services.AddSingleton<IMyCache, MyCache>();
builder.Services.AddScoped<IUserRepository, UserRepository>();
```

```csharp
// MyCache.cs — the bug lives here: Scoped injected into Singleton constructor
public class MyCache
{
    public MyCache(IUserRepository users) { … }  // captured for app lifetime
}
```

```csharp
// Program.cs — ✓ Fix 1: if MyCache needs per-request data, make it Scoped too.
builder.Services.AddScoped<IMyCache, MyCache>();

// Program.cs — ✓ Fix 2: if MyCache must be Singleton, don't inject Scoped directly.
// Use IServiceScopeFactory to create a short-lived scope when needed.
builder.Services.AddSingleton<IMyCache, MyCache>();
```

```csharp
// MyCache.cs — ✓ Fix 2 implementation: create a scope manually, dispose it when done.
public class MyCache
{
    private readonly IServiceScopeFactory _scopeFactory;
    public MyCache(IServiceScopeFactory scopeFactory) { _scopeFactory = scopeFactory; }

    public async Task DoWorkAsync()
    {
        using var scope = _scopeFactory.CreateScope();
        var users = scope.ServiceProvider.GetRequiredService<IUserRepository>();
        // users is scoped to this block — disposed when the using ends
    }
}
```

Enable scope validation in production to catch this at startup rather than at runtime:

```csharp
builder.Host.UseDefaultServiceProvider(o => o.ValidateScopes = true);
```

---

## Phase 2 — Freeze the container and build the pipeline

```csharp
var app = builder.Build();
```

`Build()` locks the recipe book. No more registrations are possible. Every object the container constructs from this point on is built from the same complete, consistent set of recipes — this is what makes DI safe and predictable.

### The pipeline

`Use…()` calls do not run anything. They declare structure — each one registers a function at a fixed position in a chain. The chain does not fire until a request arrives.

The pipeline is not a sequence. It is nested. Each middleware wraps everything below it — running code before passing the request inward, then running more code as the response unwinds back out. `UseExceptionHandler` being outermost means it wraps every other layer; any exception that escapes from anywhere below is caught there. A logging middleware that measures elapsed time works because it starts a timer before calling `next()` and records the result after — by which point the entire inner pipeline has completed.

What any middleware can see depends entirely on its position. Each layer can only read what layers above it have already written to `HttpContext`. This is why order is not a convention — it is a constraint. Three positions matter most:

**`UseCors` before `UseAuthentication`** — browser preflight `OPTIONS` requests carry no credentials. If authentication runs first and challenges the preflight, the CORS headers are never added. The browser reports a CORS error that masks what actually happened.

**`UseAuthentication` before `UseAuthorization`** — authentication writes the identity into `HttpContext.User`. Authorization reads it. If authentication has not run first, `HttpContext.User` is anonymous regardless of what credentials the request carries.

**`UseRouting` before `UseAuthorization`** — routing writes the matched endpoint onto `HttpContext` via `SetEndpoint()`. Authorization reads that endpoint's metadata to find the `[Authorize]` policies it needs to evaluate. If routing has not run yet, `GetEndpoint()` returns null, there is no metadata, and authorization falls through silently — no error, no 401, every protected route becomes publicly accessible. This is the most dangerous ordering mistake because nothing indicates it has happened.

The gap between `UseRouting` and `MapControllers` is deliberate. Middleware placed there knows where the request is going but has not yet acted on it — `UseAuthorization` lives there, as would rate limiting keyed on a route parameter or logging enriched with the action name.

```csharp
app.UseExceptionHandler();
app.UseHttpsRedirection();
app.UseCors("MyPolicy");
app.UseAuthentication();
app.UseRouting();

// ── THE GAP ──────────────────────────────────────────────────────────────
// Routing has run. GetEndpoint() now returns the matched endpoint.
// Middleware here knows the destination but hasn't acted on it yet.

app.Use(async (ctx, next) =>
{
    // Reading the action name for logging — only possible after UseRouting.
    var actionName = ctx.GetEndpoint()?.DisplayName ?? "unknown";
    using var _ = logger.BeginScope("action={Action}", actionName);
    await next(ctx);
});

app.UseRateLimiter();   // rate limiting keyed on route values — also valid here
// ─────────────────────────────────────────────────────────────────────────

app.UseAuthorization();
app.MapControllers();
```

Placing any of that gap middleware *before* `UseRouting` would make `GetEndpoint()` return null — the match has not happened yet and there is nothing to read.

**`UseRouting` and `MapControllers` are two halves of one system**, each doing different work at different times.

`UseRouting()` registers the route-matching middleware at that position. At request time it matches the URL against the routing table and writes the result onto `HttpContext`.

`MapControllers()` does two things: at startup it scans every controller and action, reads their attributes, and builds the routing table — including all `[Authorize]`, `[HttpGet]`, `[Produces]` and other metadata, ready before the first request arrives. It also registers the action-execution middleware at that pipeline position, which at request time reads the matched endpoint and runs the action.

**`UseRouting()` alone is not sufficient.** Without a `Map…()` call, the execution middleware is never registered and `GetEndpoint()` returns `null` for every request.

The routing table also powers **link generation** — `Url.Action()`, `CreatedAtAction()`, and `LinkGenerator` run it in reverse: given a controller, action name, and route values, they produce a URL. The same table serves both incoming matching and outgoing URL generation.

Because the routing table is compiled at startup, the first request after deployment is slightly slower than subsequent ones — the compilation happens lazily on first use.

### Auto-insertion in .NET 6+ (`WebApplication`)

With `WebApplication`, when `app.Run()` is called the framework inspects what you have and have not registered, then inserts middleware automatically. Your code is sandwiched between auto-`UseRouting` (position 2, before everything you write) and auto-`UseEndpoints` (at the end, after everything you write).

So this:

```csharp
// What you write:
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
```

produces this at runtime:

```csharp
// What actually runs:
app.UseRouting();         // auto-inserted before your code
app.UseAuthentication();  // your call
app.UseAuthorization();   // your call — runs after UseRouting ✓
app.MapControllers();     // your call
app.UseEndpoints(...);    // auto-inserted after your code
```

`UseAuthorization` ends up after `UseRouting` without you having to think about it. This is why most .NET 6+ apps work without an explicit `UseRouting()` call.

Calling `UseRouting()` explicitly **suppresses auto-insertion and moves routing to that position**. In a `WebApplication` app this means routing moves *later* — not earlier — because auto-insert would have placed it at position 2 before everything. A common mistake is adding middleware before `MapControllers()` expecting it to run before routing, not realising routing already ran:

```csharp
// ❌ Wrong assumption — developer expects this middleware to run before routing.
// But auto-insertion already placed UseRouting before all user middleware.
// GetEndpoint() is already populated by the time this runs.
app.Use(async (ctx, next) =>
{
    // intended to rewrite the path before routing sees it — too late
    ctx.Request.Path = "/api/rewritten" + ctx.Request.Path;
    await next(ctx);
});
app.MapControllers();

// ✓ Correct — explicit UseRouting() suppresses auto-insert and fixes routing here.
// The rewriter now runs before routing sees the path.
app.Use(async (ctx, next) =>
{
    ctx.Request.Path = "/api/rewritten" + ctx.Request.Path;
    await next(ctx);
});
app.UseRouting();       // explicit — routing happens here, after the rewriter
app.UseAuthorization();
app.MapControllers();
```

Explicit placement is only needed when you want something to run before routing sees the URL. For everything else, let auto-insertion handle it.

### `Startup.Configure` — the misplacement trap (pre-.NET 6 or explicit host builder)

In the older `Startup.Configure` pattern — and in any .NET 6+ app that uses an explicit host builder instead of `WebApplication` — there is no auto-insertion. The pipeline is exactly what you write.

There is one exception: if you call a `Map…()` method without having called `UseRouting()` first, `EndpointRoutingMiddleware` is inserted automatically **at the `Map…()` position** — not at the start. This creates a silent security hole:

```csharp
// ❌ Wrong — and no error is thrown:
app.UseAuthorization();  // GetEndpoint() is null — routing hasn't run yet
app.MapControllers();    // EndpointRoutingMiddleware silently inserted here

// Effective pipeline at runtime:
// UseAuthorization          → GetEndpoint() null → no metadata → auth skipped
// EndpointRoutingMiddleware → inserted at MapControllers() position
// EndpointMiddleware        → executes the action
// Result: every [Authorize] route is publicly accessible
```

```csharp
// ✓ Correct:
app.UseAuthentication();
app.UseRouting();        // explicit — matching happens here
app.UseAuthorization();  // after routing ✓
app.MapControllers();
```

### The runtime guard — what it catches and what it misses

`EndpointMiddleware` has a runtime check: before executing an endpoint whose metadata contains `[Authorize]`, it looks for a key on `HttpContext.Items` that `AuthorizationMiddleware` sets whenever it runs. If the key is absent it throws:

> Endpoint UsersController.GetUser contains authorization metadata, but a middleware was not found that supports authorization.

This catches **omission** — `UseAuthorization()` not called at all.

It does **not** catch **misplacement** — `UseAuthorization` placed before `UseRouting` in a `Startup.Configure` host. `AuthorizationMiddleware` ran, set its key, the guard sees it and is satisfied. The fact that `GetEndpoint()` returned `null` and no policy was evaluated is invisible. The security hole is undetected.

In a `WebApplication` app this trap is much harder to trigger accidentally — auto-insertion puts `UseRouting` before your code. You would have to explicitly call `UseAuthorization()` before an explicit `UseRouting()` to recreate it.

---

## Open the server

```csharp
app.Run();  // opens TCP socket, starts Kestrel listen loop — blocks until shutdown
```

The restaurant is open. Kestrel opens a TCP socket and waits for connections. Everything built in phase 1 and phase 2 is now in place. The first request arriving is the first order coming in — and the per-request lifecycle begins.

---

*Per-request lifecycle → `aspnet-per-request.md`*
