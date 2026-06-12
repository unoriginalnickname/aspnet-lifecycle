## Middleware

Middleware is a function that sits in the pipeline and receives every request. Each piece of middleware receives `HttpContext` and a `next` delegate — a handle to the rest of the chain. Code before calling `next` runs on the way in. Code after runs on the way back out. Not calling `next` at all short-circuits the request — the response travels back immediately without reaching any layer below.

```csharp
app.Use(async (ctx, next) =>
{
    // ON THE WAY IN — runs before calling next
    await next(ctx);
    // ON THE WAY BACK OUT — runs after everything below has completed
});
```

---

## When to use an inline lambda vs a class

**Inline lambdas** — `app.Use(async (ctx, next) => { … })` — are fine for simple, stateless logic: adding a header, rewriting a path, short-circuiting on a condition. They cannot receive per-request (Scoped) services from DI — they have no constructor and no per-invocation parameter injection.

**Class-based middleware** is the right choice when:

- You need a **Scoped service** injected per-request (e.g. `ICurrentUserService`, `DbContext`)
- You need a **Singleton service** injected once (e.g. `IOptions<T>`, `ILogger<T>`)
- The middleware has enough logic that a class with a name is clearer than a lambda
- You want to unit-test the middleware independently

---

## Class-based middleware — the pattern

A middleware class has one required constructor parameter and one required method:

```csharp
public class RequestLoggingMiddleware
{
    private readonly RequestDelegate              _next;
    private readonly ILogger<RequestLoggingMiddleware> _log;

    // Constructor — receives RequestDelegate and any SINGLETON services.
    // Called once when the pipeline is built — not per request.
    public RequestLoggingMiddleware(
        RequestDelegate next,
        ILogger<RequestLoggingMiddleware> log)
    {
        _next = next;
        _log  = log;
    }

    // InvokeAsync — called once per request.
    // Scoped services go here as extra parameters — resolved fresh each request.
    public async Task InvokeAsync(HttpContext ctx, ITraceService trace)
    {
        var sw = Stopwatch.StartNew();
        _log.LogInformation("→ {Method} {Path} trace={Trace}",
            ctx.Request.Method, ctx.Request.Path, trace.CurrentId);

        await _next(ctx);

        _log.LogInformation("← {Status} in {Ms}ms",
            ctx.Response.StatusCode, sw.ElapsedMilliseconds);
    }
}
```

Register it in the pipeline with `UseMiddleware<T>()`:

```csharp
app.UseMiddleware<RequestLoggingMiddleware>();
```

**Why the split between constructor and `InvokeAsync`?**

The middleware class is constructed once when `app.UseMiddleware<T>()` is called — before any request arrives. At that point, no request scope exists, so Scoped services cannot be resolved. The framework injects Singleton and transient services in the constructor. Per-request Scoped services are injected as extra parameters on `InvokeAsync` — the framework resolves them from the request's DI scope each time `InvokeAsync` is called.

```csharp
// Correct — Singleton in constructor, Scoped in InvokeAsync:
public RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> log)
{ … }

public async Task InvokeAsync(HttpContext ctx, ICurrentUserService user)  // Scoped — per request
{ … }

// WRONG — injecting a Scoped service into the constructor:
public RequestLoggingMiddleware(RequestDelegate next, AppDbContext db)
// AppDbContext is Scoped — the container will throw at startup because no
// request scope exists when the middleware class is constructed.
```

---

## IMiddleware — the explicit interface

The pattern above (constructor + `InvokeAsync` with extra parameters) is the conventional approach and works by reflection. ASP.NET Core also provides an explicit `IMiddleware` interface:

```csharp
public interface IMiddleware
{
    Task InvokeAsync(HttpContext context, RequestDelegate next);
}
```

`IMiddleware` is different from the convention-based approach in one important way: the class is resolved from the DI container on **every request**, not constructed once at startup. This means:

- The class can be registered as **Scoped** — a new instance per request
- All constructor parameters are resolved per-request, including Scoped services
- No need for the `InvokeAsync` extra-parameter trick

```csharp
public class TenantResolutionMiddleware : IMiddleware
{
    private readonly ITenantRepository _tenants;

    // Constructor injection works normally — resolved per request from the Scoped DI container:
    public TenantResolutionMiddleware(ITenantRepository tenants)
        => _tenants = tenants;

    public async Task InvokeAsync(HttpContext context, RequestDelegate next)
    {
        var host     = context.Request.Host.Host;
        var tenantId = await _tenants.ResolveAsync(host);

        context.Items["tenantId"] = tenantId;

        await next(context);
    }
}
```

Register the class in DI **and** in the pipeline:

```csharp
// Program.cs — must be registered in DI for IMiddleware resolution to work:
builder.Services.AddScoped<TenantResolutionMiddleware>();

// Pipeline:
app.UseMiddleware<TenantResolutionMiddleware>();
```

If you use `IMiddleware` but forget to register the class in DI, `UseMiddleware<T>()` throws `InvalidOperationException` at the first request: `No service for type 'TenantResolutionMiddleware' has been registered.`

---

## app.Use, app.Run, app.Map, app.UseWhen

Four registration methods with different behaviours:

**`app.Use`** — the standard pass-through. Calls `next` and continues. Used for middleware that runs on the way in and/or back out.

**`app.Run`** — terminal. Never calls `next`. Useful as the last handler in the pipeline or as a catch-all. Every request that reaches it stops here.

```csharp
app.Run(async ctx =>
{
    ctx.Response.StatusCode = 404;
    await ctx.Response.WriteAsJsonAsync(new { error = "Not found" });
});
```

**`app.Map`** — branches the pipeline on a URL prefix. The branch does **not** rejoin the main pipeline — a request that enters the branch does not continue to the middleware registered after the `Map` call.

```csharp
app.Map("/admin", adminApp =>
{
    adminApp.UseAuthentication();
    adminApp.UseAuthorization();
    adminApp.Run(async ctx => await ctx.Response.WriteAsync("admin area"));
});

// Requests to /admin enter the branch above.
// Requests to anything else continue here:
app.UseRouting();
app.MapControllers();
```

**`app.UseWhen`** — branches on a predicate but **rejoins** the main pipeline after the branch completes. Use when you want to conditionally add middleware for a subset of requests without forking the pipeline permanently.

```csharp
app.UseWhen(
    ctx => ctx.Request.Path.StartsWithSegments("/api"),
    apiApp =>
    {
        // runs only for /api/* requests, then rejoins the main pipeline:
        apiApp.UseMiddleware<ApiKeyMiddleware>();
    });

// All requests — including /api/* — continue here after the branch:
app.UseRouting();
app.MapControllers();
```

---

## Short-circuiting

Not calling `next` stops the request from going further. The response travels back up through the layers that already ran — every middleware that called `await next(ctx)` gets to run its post-`next` code.

```csharp
app.Use(async (ctx, next) =>
{
    if (ctx.Request.Headers["X-Maintenance-Bypass"] != _bypassKey)
    {
        // short-circuit — nothing below runs:
        ctx.Response.StatusCode = 503;
        await ctx.Response.WriteAsJsonAsync(new { message = "Maintenance mode." });
        return;  // do not call next
    }

    await next(ctx);  // bypass key present — let the request through
});
```

Short-circuiting is also how static files, CORS preflight, and HTTPS redirection work — each checks a condition and either handles the request completely (returning without calling `next`) or passes through.

---

## What breaks and why

**Injecting a Scoped service into the middleware constructor (convention-based)**
The constructor is called at startup — no request scope exists. In Development, the DI container's scope validation detects this and throws `InvalidOperationException` at startup. In Production, scope validation is off by default — the Scoped service is silently captured in the constructor and shared across all requests for the app's lifetime, leaking state between requests. The same captive dependency trap as Scoped-in-Singleton. Move the Scoped service to an extra `InvokeAsync` parameter, or use the `IMiddleware` interface.

**Using `IMiddleware` but forgetting to register the class in DI**
`UseMiddleware<T>()` detects the `IMiddleware` interface and calls `serviceProvider.GetRequiredService<T>()` per request. If the class is not registered, this throws at the first request — not at startup. Register the class with `AddScoped<T>()`, `AddTransient<T>()`, or `AddSingleton<T>()` depending on its lifetime needs.

**Modifying response headers after `await next(ctx)` when the body has already started**
Once `HttpContext.Response.HasStarted` is `true`, headers are committed to the network. Attempting to set `StatusCode` or append headers throws `InvalidOperationException`. Check `HasStarted` before touching the response on the way back out:

```csharp
await next(ctx);
if (!ctx.Response.HasStarted)
    ctx.Response.Headers.Append("X-Timing-Ms", sw.ElapsedMilliseconds.ToString());
```

**`app.Map` branch not reaching downstream middleware**
Requests that enter a `Map` branch never reach middleware registered after the `Map` call. If you need the branch to also run `UseRouting` and `MapControllers`, register them inside the branch. Use `UseWhen` instead if you want conditional middleware that rejoins.
