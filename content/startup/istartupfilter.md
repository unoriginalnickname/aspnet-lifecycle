## IStartupFilter

`IStartupFilter` is a mechanism for inserting middleware into the pipeline programmatically — without the app author calling `Use…()` directly in `Program.cs`. The framework uses it internally to add infrastructure middleware that must run before user code regardless of what the user writes. Library authors use it to ensure their middleware is always in the right position without requiring consumers to configure it manually.

### Why it exists

`Program.cs` gives you control over your middleware pipeline, but only for middleware you know about and explicitly register. Some middleware must run at a fixed position that the app author cannot be expected to know or care about. `IStartupFilter` lets a library or the framework itself insert middleware at a guaranteed position — before or after user code — as a side effect of adding a service to the DI container.

The framework uses it for:
- `HostFilteringMiddleware` — inserted at the very start of every pipeline by `ConfigureWebHostDefaults()`, before your `Program.cs` code runs
- `ForwardedHeadersMiddleware` — inserted early when `ASPNETCORE_FORWARDEDHEADERS_ENABLED=true`, so `HttpContext.Connection.RemoteIpAddress` reflects the original client IP before anything else reads it
- `AutoRequestServicesStartupFilter` — inserts `RequestServicesContainerMiddleware` at the start so the request DI scope is available to everything downstream

### How it works

`IStartupFilter` has one method:

```csharp
public interface IStartupFilter
{
    Action<IApplicationBuilder> Configure(Action<IApplicationBuilder> next);
}
```

It receives the next `Configure` action in the chain and returns a new one. By calling `next(app)` inside the returned action, you invoke everything that was already registered. Code before `next(app)` runs before user middleware; code after runs after:

```csharp
public class RequestIdStartupFilter : IStartupFilter
{
    public Action<IApplicationBuilder> Configure(Action<IApplicationBuilder> next)
    {
        return app =>
        {
            // inserted BEFORE all user middleware in Program.cs
            app.UseMiddleware<RequestIdMiddleware>();

            next(app);  // everything the user registered in Program.cs runs here

            // inserted AFTER all user middleware — rarely needed
        };
    }
}
```

Register it in the DI container before `builder.Build()`:

```csharp
// Program.cs:
builder.Services.AddTransient<IStartupFilter, RequestIdStartupFilter>();
```

The framework discovers all registered `IStartupFilter` implementations when building the pipeline and chains them in registration order. The result: `RequestIdMiddleware` runs before any middleware the app author writes, without the app author needing to know it exists.

### Execution order — multiple filters

If multiple `IStartupFilter` implementations are registered, they are chained in registration order. The first registered filter wraps all others — its before-code runs first, its after-code runs last:

```
Filter A (registered first)   → before code
  Filter B (registered second)  → before code
    User middleware (Program.cs)
  Filter B                       → after code
Filter A                       → after code
```

To insert a filter's middleware before a library's filter, register it before the library's `Add…()` call. To insert after, register after.

### IStartupFilter vs Program.cs

| | `Program.cs` | `IStartupFilter` |
|---|---|---|
| Who writes it | App author | Library or framework |
| Position control | Explicit — you choose | Before or after user code only |
| Requires app author action | Yes — must call `Use…()` | No — activated by DI registration |
| Use case | App-specific middleware | Infrastructure middleware that must always be present |

### What this means for your pipeline

The `HostFilteringMiddleware` and `ForwardedHeadersMiddleware` inserted by `IStartupFilter` run *before* any middleware you write in `Program.cs` — including `UseExceptionHandler()`. This is intentional: host filtering must happen before any application logic, and forwarded headers must be processed before `HttpContext.Connection.RemoteIpAddress` is read by anything downstream.

The effective pipeline for a typical production app is:

```
HostFilteringMiddleware        ← inserted by IStartupFilter, before your code
ForwardedHeadersMiddleware     ← inserted by IStartupFilter (if env var set)
--- your Program.cs middleware starts here ---
UseExceptionHandler
UseHttpsRedirection
UseCors
UseAuthentication              (auto-injected or explicit)
UseAuthorization               (auto-injected or explicit)
MapControllers
--- your Program.cs middleware ends here ---
UseEndpoints                   ← auto-injected at the end
```

`HttpContext.Connection.RemoteIpAddress` is the direct TCP peer by default — behind a load balancer or reverse proxy, this is the proxy's IP. `ForwardedHeadersMiddleware` rewrites `RemoteIpAddress` from the `X-Forwarded-For` header before anything else reads it. This only runs when `ASPNETCORE_FORWARDEDHEADERS_ENABLED=true` or when configured explicitly via `app.UseForwardedHeaders()`. If neither is set and you are behind a proxy, `RemoteIpAddress` will always be the proxy's IP.

### What breaks

**Wrong registration order between two IStartupFilter implementations**
Filters are chained in DI registration order — the first registered filter's before-code runs first. If filter A depends on middleware inserted by filter B (e.g. A reads a header that B's middleware sets), register B before A. Reversing the order means A runs before B's middleware has had a chance to set the header. No error is thrown — the behaviour is simply wrong.

**Registering IStartupFilter after a library that also registers one**
If a library's `Add…()` call registers an `IStartupFilter` internally and you register your own filter after that call, your filter's before-code runs after the library's. If you need your filter's middleware to run before the library's middleware, register it before the library's `Add…()` call:

```csharp
// Your filter runs before the library's filter:
builder.Services.AddTransient<IStartupFilter, MyEarlyFilter>();
builder.Services.AddLibrary();   // library registers its own IStartupFilter internally

// WRONG: Your filter runs after the library's filter:
builder.Services.AddLibrary();
builder.Services.AddTransient<IStartupFilter, MyEarlyFilter>();
```

**Using IStartupFilter with WebApplication when you need it before auto-inserted middleware**
`WebApplication` auto-inserts `UseRouting`, `UseAuthentication`, and `UseAuthorization` before your `Program.cs` code. `IStartupFilter` middleware is inserted before even that auto-inserted code — at the very start of the pipeline. This is the correct behaviour for infrastructure middleware. If you instead need your middleware in the gap (after routing, before authorization), `IStartupFilter` is the wrong tool — register it explicitly in `Program.cs` after `UseRouting()`.
