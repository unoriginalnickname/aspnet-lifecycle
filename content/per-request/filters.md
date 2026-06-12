## Filters

Filters are hooks that run at specific points around a controller action. They sit inside the MVC layer — after routing has matched the request and after the controller has been instantiated, but before and after the action method itself runs. This position gives them something middleware cannot have: knowledge of which controller and action are being called, access to the action's arguments by name, and the ability to read or replace the result before it is serialised.

Middleware runs outside MVC entirely. It sees the raw `HttpRequest` and `HttpResponse` but has no concept of controllers, actions, or model-bound arguments. A filter can log `ctx.ActionArguments["id"]` — the already-bound, typed value. Middleware can only read the raw URL segment `"5"` before binding has happened.

The filter pipeline is registered by `AddControllers()` at startup. At request time, after the controller constructor runs and DI injects its dependencies, the filter pipeline executes in a fixed nesting order.

---

## Execution order

Filters nest — each outer filter wraps every inner filter. The nesting order is fixed and cannot be changed:

```
IExceptionFilter                    ← outermost; catches exceptions from everything inside
  IAuthorizationFilter              ← runs before anything else; 401/403 short-circuits here
    IResourceFilter (before)        ← before model binding; can serve from cache
      model binding runs
      IActionFilter (before)        ← action arguments are bound and available here
        your action method runs
      IActionFilter (after)         ← ctx.Result holds the IActionResult your action returned
    IResourceFilter (after)         ← after result is written; rarely used
    IResultFilter (before)          ← before IActionResult.ExecuteResultAsync() writes the response
      IActionResult.ExecuteResultAsync() runs — response bytes written here
    IResultFilter (after)           ← response has been written
```

"Before" and "after" refer to the action method, not to the pipeline as a whole. Every filter that has a "before" phase runs on the way in; every filter that has an "after" phase runs on the way back out, in reverse registration order.

Short-circuiting at any layer skips everything inside it. An `IAuthorizationFilter` that sets `ctx.Result` prevents model binding, action execution, action filters, and result filters from running — but `IExceptionFilter` above it still completes its after-phase.

---

## IAuthorizationFilter

Runs first, before model binding. If the request should not proceed, set `context.Result` to any `IActionResult` — the pipeline short-circuits and the action never runs.

`[Authorize]` is implemented as an `IAuthorizationFilter` internally. Custom authorization filters are rare — the policy-based `IAuthorizationHandler` system (covered in [per-request/authorization.md]) is the preferred approach for custom logic. `IAuthorizationFilter` is useful when you need a simple synchronous check that does not require the full policy infrastructure.

```csharp
public class RequireApiKeyFilter : IAuthorizationFilter
{
    private readonly string _expectedKey;

    public RequireApiKeyFilter(IConfiguration config)
        => _expectedKey = config["ApiKey"] ?? throw new InvalidOperationException("ApiKey not configured");

    public void OnAuthorization(AuthorizationFilterContext context)
    {
        var key = context.HttpContext.Request.Headers["X-Api-Key"].FirstOrDefault();

        if (key != _expectedKey)
            context.Result = new UnauthorizedResult();  // short-circuits — action never runs
    }
}
```

---

## IResourceFilter

Runs after `IAuthorizationFilter` but before model binding. Its position makes it the right place to short-circuit for caching — you can return a cached response without paying the cost of binding or executing the action.

```csharp
public class CacheResourceFilter : IResourceFilter
{
    private readonly IMemoryCache _cache;
    public CacheResourceFilter(IMemoryCache cache) => _cache = cache;

    public void OnResourceExecuting(ResourceExecutingContext context)
    {
        // runs before model binding — context.RouteData is available, action arguments are not yet bound
        var cacheKey = context.HttpContext.Request.Path + context.HttpContext.Request.QueryString;

        if (_cache.TryGetValue(cacheKey, out var cached))
            context.Result = new OkObjectResult(cached);  // short-circuit — binding and action skipped
    }

    public void OnResourceExecuted(ResourceExecutedContext context)
    {
        // runs after the result has been written — rarely needed
        // context.Result holds the IActionResult that was executed
    }
}
```

`IResourceFilter` is also the right place to put filters that need to wrap the entire MVC execution — including model binding — in a `try/finally`, for example for request-level resource acquisition and release.

---

## IActionFilter

The most commonly used filter type. Runs after model binding — by the time `OnActionExecuting` fires, all action parameters are already bound and available in `context.ActionArguments`.

```csharp
public class LogActionFilter : IActionFilter
{
    private readonly ILogger<LogActionFilter> _log;
    public LogActionFilter(ILogger<LogActionFilter> log) => _log = log;

    public void OnActionExecuting(ActionExecutingContext context)
    {
        // context.ActionDescriptor.DisplayName — e.g. "UsersController.GetUser (MyApi)"
        // context.ActionArguments — Dictionary<string, object?> of bound parameter values
        //   e.g. { "id": 5, "notify": true } — already converted to their target types
        _log.LogInformation("▶ {Action} args={@Args}",
            context.ActionDescriptor.DisplayName,
            context.ActionArguments);

        // to short-circuit: set context.Result — action method will not run
        // context.Result = new BadRequestObjectResult("Custom rejection");
    }

    public void OnActionExecuted(ActionExecutedContext context)
    {
        // context.Result — the IActionResult returned by the action, before it is executed
        //   e.g. OkObjectResult, NotFoundResult, CreatedAtActionResult
        // context.Exception — non-null if the action threw; set context.ExceptionHandled = true to suppress
        _log.LogInformation("■ {Action} result={Result}",
            context.ActionDescriptor.DisplayName,
            context.Result?.GetType().Name);
    }
}
```

`context.ActionArguments` is a `Dictionary<string, object?>` keyed by parameter name. The values are already the bound, typed objects — not raw strings. For a parameter `int id`, `context.ActionArguments["id"]` is `5` (an `int`), not `"5"`.

---

## IResultFilter

Runs after the action returns an `IActionResult` but before and after `IActionResult.ExecuteResultAsync()` writes the response bytes. By the time `OnResultExecuting` fires, the response has not yet been written — you can still replace `context.Result`. By `OnResultExecuted`, the response body has been written and headers are committed.

```csharp
public class AddHeaderResultFilter : IResultFilter
{
    public void OnResultExecuting(ResultExecutingContext context)
    {
        // response not yet written — can still modify headers or replace context.Result
        context.HttpContext.Response.Headers.Append("X-Result-Type", context.Result.GetType().Name);
    }

    public void OnResultExecuted(ResultExecutedContext context)
    {
        // response body has been written — headers are committed
        // context.HttpContext.Response.HasStarted == true here
        // do not attempt to modify headers or status code
    }
}
```

---

## IExceptionFilter

Catches exceptions thrown by the action method or by any inner filter (`IActionFilter`, `IResultFilter`, `IResourceFilter`). Does not catch exceptions from middleware or from `IAuthorizationFilter` when it throws rather than sets a result.

```csharp
public class GlobalExceptionFilter : IExceptionFilter
{
    private readonly ILogger<GlobalExceptionFilter> _log;
    public GlobalExceptionFilter(ILogger<GlobalExceptionFilter> log) => _log = log;

    public void OnException(ExceptionContext context)
    {
        _log.LogError(context.Exception, "Unhandled exception in action {Action}",
            context.ActionDescriptor.DisplayName);

        context.Result = new ObjectResult(new ProblemDetails
        {
            Status = 500,
            Title  = "An unexpected error occurred."
            // never expose context.Exception.Message — it may contain internal details
        })
        { StatusCode = 500 };

        context.ExceptionHandled = true;  // prevents the exception from bubbling further
        // if ExceptionHandled remains false, the exception continues up to UseExceptionHandler
    }
}
```

`UseExceptionHandler` (middleware, outermost) is a broader safety net — it catches everything `IExceptionFilter` does not, including middleware exceptions. The two are complementary, not alternatives. Covered in [per-request/exception-handler.md].

---

## Async variants

Every filter interface has an async counterpart. Use the async variant when the filter itself needs to `await` something — a database lookup, a cache check, an external HTTP call.

| Sync | Async |
|---|---|
| `IAuthorizationFilter` | `IAsyncAuthorizationFilter` |
| `IResourceFilter` | `IAsyncResourceFilter` |
| `IActionFilter` | `IAsyncActionFilter` |
| `IResultFilter` | `IAsyncResultFilter` |
| `IExceptionFilter` | `IAsyncExceptionFilter` |

The async variants use a single method with a `next` delegate instead of separate before/after methods:

```csharp
public class TimingActionFilter : IAsyncActionFilter
{
    private readonly ILogger<TimingActionFilter> _log;
    public TimingActionFilter(ILogger<TimingActionFilter> log) => _log = log;

    public async Task OnActionExecutionAsync(
        ActionExecutingContext context,
        ActionExecutionDelegate next)  // calling next() runs the action and inner filters
    {
        var sw = Stopwatch.StartNew();

        // before — context.ActionArguments available here
        var executed = await next();   // runs the action; returns ActionExecutedContext
        // after — executed.Result holds the returned IActionResult
        //         executed.Exception is non-null if the action threw

        _log.LogInformation("{Action} completed in {Ms}ms",
            context.ActionDescriptor.DisplayName,
            sw.ElapsedMilliseconds);
    }
}
```

`next()` returns an `ActionExecutedContext` — the same object `OnActionExecuted` receives in the sync variant. Not calling `next()` short-circuits the pipeline, equivalent to setting `context.Result` in `OnActionExecuting`.

Do not implement both the sync and async variant of the same interface on one class — the framework calls only the async version if both are present.

---

## Registration

### Globally — every action in the app

```csharp
// Program.cs — before builder.Build():
builder.Services.AddControllers(o =>
{
    o.Filters.Add<LogActionFilter>();        // resolved from DI — constructor injection works
    o.Filters.Add<GlobalExceptionFilter>();
    o.Filters.Add(new RequireHttpsAttribute()); // instance — no DI
});
```

Filters registered globally run on every action in every controller, in registration order within their type.

### Per controller or per action — attribute

```csharp
[ServiceFilter(typeof(LogActionFilter))]     // resolved from DI
public class UsersController : ControllerBase { … }

[TypeFilter(typeof(LogActionFilter))]        // instantiated by the framework, not DI
public ActionResult<UserDto> GetUser(int id) { … }
```

### Attribute-based filters

A filter can also be its own attribute — implement the filter interface and inherit from `Attribute`:

```csharp
public class RequireAdminAttribute : Attribute, IAuthorizationFilter
{
    public void OnAuthorization(AuthorizationFilterContext context)
    {
        if (!context.HttpContext.User.IsInRole("Admin"))
            context.Result = new ForbidResult();
    }
}

[RequireAdmin]  // applied directly as an attribute — no ServiceFilter or TypeFilter needed
public ActionResult<AdminDashboardDto> GetDashboard() { … }
```

Attribute-based filters cannot receive constructor-injected DI services because C# attribute constructors only accept compile-time constants. Use `ServiceFilter` or `TypeFilter` when DI is needed.

---

## ServiceFilter vs TypeFilter

Both resolve a filter from outside the global registration, but they differ in how the filter instance is created.

**`ServiceFilter`** requires the filter type to be registered in the DI container. The framework calls `serviceProvider.GetRequiredService<T>()` to get the instance — the filter's full DI constructor injection works, and its lifetime is whatever you registered (Scoped, Transient, Singleton).

```csharp
// Program.cs — must be registered:
builder.Services.AddScoped<LogActionFilter>();

// Controller or action:
[ServiceFilter(typeof(LogActionFilter))]
public class UsersController : ControllerBase { … }
```

**`TypeFilter`** does not require prior DI registration. The framework instantiates the filter directly using `ObjectFactory`, resolving constructor parameters from the DI container at activation time. The lifetime is always Transient — a new instance per use.

```csharp
// No DI registration needed:
[TypeFilter(typeof(LogActionFilter))]
public ActionResult<UserDto> GetUser(int id) { … }
```

`TypeFilter` also accepts constructor arguments that cannot come from DI:

```csharp
public class MinimumAgeFilter : IAuthorizationFilter
{
    private readonly int _minimumAge;
    public MinimumAgeFilter(int minimumAge) => _minimumAge = minimumAge;

    public void OnAuthorization(AuthorizationFilterContext context)
    {
        var age = int.Parse(context.HttpContext.User.FindFirstValue("age") ?? "0");
        if (age < _minimumAge) context.Result = new ForbidResult();
    }
}

[TypeFilter(typeof(MinimumAgeFilter), Arguments = new object[] { 18 })]
public ActionResult<RestrictedDto> GetRestricted() { … }
```

Use `ServiceFilter` when the filter is a proper application service with a specific lifetime. Use `TypeFilter` when the filter needs non-DI constructor arguments or when you want to avoid registering it in the container.

---

## Filter order within a type

When multiple filters of the same type apply to an action — from global registration, controller attribute, and action attribute — they run in this order on the way in, and reverse order on the way back out:

1. Global filters (in registration order)
2. Controller-level filters (in registration order)
3. Action-level filters (in registration order)

To override this, implement `IOrderedFilter` and set the `Order` property. Lower numbers run first on the way in (and last on the way back out):

```csharp
public class EarlyFilter : IActionFilter, IOrderedFilter
{
    public int Order => -1000;  // runs before filters with Order 0 (the default)

    public void OnActionExecuting(ActionExecutingContext context) { … }
    public void OnActionExecuted(ActionExecutedContext context) { … }
}
```

---

## What breaks and why

**Filter has a constructor dependency that isn't registered in DI**
If a filter is registered globally via `o.Filters.Add<MyFilter>()` or via `[ServiceFilter]`, the DI container resolves it. If the required service is not registered, the container throws at request time — not at startup. The first request to hit that filter fails with `InvalidOperationException: Unable to resolve service for type '…'`.

**Attribute-based filter tries to inject a DI service via constructor**
C# attribute constructors only accept compile-time constants (`string`, `int`, `Type`, enums). Attempting to inject an `ILogger` or other service into an attribute constructor is a compile error. Use `[ServiceFilter]` or `[TypeFilter]` instead, or access services via `context.HttpContext.RequestServices.GetRequiredService<T>()` inside the filter method (service locator — use sparingly).

**Implementing both sync and async variants on one class**
If a class implements both `IActionFilter` and `IAsyncActionFilter`, the framework calls only `IAsyncActionFilter`. The sync methods are silently ignored. Pick one variant per class.

**Setting `context.Result` in `OnActionExecuted` does not re-execute the result**
In `OnActionExecuted`, the action has already returned. Setting `context.Result` replaces the result object, but whether the new result gets executed depends on what happens after. If you need to replace the response, do it in `OnActionExecuting` (before the action runs) or in an `IResultFilter` (before `ExecuteResultAsync` runs). Replacing the result in `OnActionExecuted` is valid but easy to misuse — test the behaviour explicitly.

**`IExceptionFilter` sets `ExceptionHandled = true` but doesn't set `context.Result`**
The exception is marked handled but no response is written. The request continues with an empty response — no status code, no body. Always set `context.Result` when handling an exception in a filter.
