## ExceptionHandler

Placed early in the pipeline so it wraps the middleware that follows. Any unhandled exception that escapes from middleware below is intercepted here, provided a response has not already started. It does not need to be literally the first middleware — infrastructure middleware like `UseForwardedHeaders` legitimately runs before it — but it must precede everything it needs to protect.

### Why it goes before routing

`UseExceptionHandler` is placed before `UseRouting` so it can intercept exceptions from every layer that follows — routing failures, authentication exceptions, authorization exceptions, and controller execution exceptions. Placing it after any of these would leave those layers unprotected:

```csharp
app.UseExceptionHandler();  // wraps everything below
app.UseRouting();           // routing exceptions caught above
app.UseAuthentication();    // auth exceptions caught above
app.UseAuthorization();     // authz exceptions caught above
app.MapControllers();       // controller exceptions caught above
```

Any middleware placed before `UseExceptionHandler` — such as `UseForwardedHeaders` — is not protected by it. Exceptions from those middlewares propagate up to the server, which typically returns a 500 with no body.

### What it does

Catches the exception, logs it automatically, clears the response, and returns a safe RFC 7807 error response to the caller. The full exception and stack trace are in your logs. Nothing internal reaches the client.

**Why it logs automatically:** `ExceptionHandlerMiddlewareImpl` injects `ILoggerFactory` in its constructor and creates its own `ILogger` instance. When it catches an exception it calls a pre-compiled `LoggerMessage` at `LogLevel.Error` with the message "An unhandled exception has occurred while executing the request." and the full exception attached. This is built into the middleware itself — you do not configure it.

The automatic log entry covers the exception type, message, and stack trace. What it does not cover is request context — who the user was, which tenant, what the input was. If you need that in your error logs, add it in your `IExceptionHandler` implementation or error controller action where `HttpContext` is available. You are not replacing the automatic log — you are supplementing it with context it cannot infer.

```json
{
  "type": "https://tools.ietf.org/html/rfc7231#section-6.6.1",
  "title": "An error occurred while processing your request.",
  "status": 500,
  "traceId": "00-abc123def456-00"
}
```

### traceId

Every request gets a unique request identifier via `HttpContext.TraceIdentifier`. When distributed tracing is active, .NET also assigns an `Activity.TraceId` that can flow across service boundaries. The `traceId` value in the `ProblemDetails` response comes from `Activity.Current?.TraceId` with a fallback to `HttpContext.TraceIdentifier` if no `Activity` is active. Logging providers can include the same traceId in log entries, allowing a request to be correlated with its logs. When a user reports an error, they give you the `traceId` and you search your logs — finding the exact request and the full exception without having exposed either to the client.

Format: W3C TraceContext — `00-{traceId}-{spanId}-{flags}`.

### What it catches

`UseExceptionHandler` is the outer net — it catches exceptions from any layer: middleware, routing, the MVC pipeline, your action code. Compare with `IExceptionFilter` (inside the MVC layer) which only catches exceptions thrown inside a controller action or its filters.

If both are configured:
- Exception thrown inside an action → `IExceptionFilter` catches first
- If `IExceptionFilter` sets `ExceptionHandled = true` → done, `UseExceptionHandler` never sees it
- If `IExceptionFilter` leaves `ExceptionHandled = false` → bubbles up to `UseExceptionHandler`
- Exception thrown inside middleware → `IExceptionFilter` never sees it, `UseExceptionHandler` catches it

### Re-execution — how the error response is actually built

`UseExceptionHandler` does not simply return the `ProblemDetails` shape itself. It catches the exception, clears the response, and **re-invokes the pipeline internally** using the original HTTP method and a new path — `/error` by default, or a path you specify.

This is not a new HTTP request. No new network connection is made, no new DI scope is created, and no new `HttpContext` is constructed. The same `HttpContext` that carried the original request is re-used — with the response body and route data cleared, but with request headers, HTTP method, and `HttpContext.Items` preserved.

**One important caveat:** `UseExceptionHandler` can only intervene if the response has not already started writing. Once `HttpContext.Response.HasStarted` is `true` — meaning response headers have been committed to the network — the middleware cannot replace the response with a `ProblemDetails` payload. The exception is re-thrown and the connection is typically aborted by the server.

```csharp
// With a path — re-invokes the pipeline targeting /error:
app.UseExceptionHandler("/error");

// With no argument — uses the IExceptionHandler chain or default ProblemDetails formatter:
app.UseExceptionHandler();
```

When a path is specified, a controller action at that path produces the response:

```csharp
[ApiController]
public class ErrorController : ControllerBase
{
    [Route("/error")]
    public IActionResult HandleError()
    {
        // IExceptionHandlerFeature carries the original exception — read it to customise the response:
        var feature = HttpContext.Features.Get<IExceptionHandlerFeature>();
        var exception = feature?.Error;

        // UseExceptionHandler already logs the exception at LogLevel.Error automatically.
        // Add logging here only if you need additional context (user ID, tenant, etc.).

        return Problem();  // produces RFC 7807 ProblemDetails
    }
}
```

**The re-execution consequence:** if your error handler action is decorated with an HTTP method attribute — `[HttpGet]`, `[HttpPost]` — it only handles errors from requests of that method. A POST that throws will not reach a `[HttpGet]` error action. Leave the error action without an HTTP method attribute, or provide handlers for each method.

**The scoped services consequence:** re-invocation runs in the same request scope — the same `DbContext`, the same scoped services. If the original exception came from a scoped service that is now in a broken state, the error handler has access to the same broken instance. Design error handlers to be simple and avoid re-using services that may have thrown.

**What is preserved on re-invocation:** request headers, HTTP method, `HttpContext.Items`, `HttpContext.Features` (including `IExceptionHandlerFeature` which carries the original exception). The response is reset and route data is cleared before re-invocation.

When `UseExceptionHandler()` is called with no argument, no path re-invocation happens — the middleware passes the exception directly to registered `IExceptionHandler` implementations or the default `ProblemDetails` formatter.

### IExceptionHandler — .NET 8+

.NET 8 introduced `IExceptionHandler`, an interface for registering multiple named exception handlers that are tried in sequence. Each handler receives the exception and decides whether to handle it — returning `true` from `TryHandleAsync` signals "I handled this, stop trying others":

```csharp
public class NotFoundExceptionHandler : IExceptionHandler
{
    private readonly ILogger<NotFoundExceptionHandler> _log;
    public NotFoundExceptionHandler(ILogger<NotFoundExceptionHandler> log) => _log = log;

    public async ValueTask<bool> TryHandleAsync(
        HttpContext     httpContext,
        Exception       exception,
        CancellationToken cancellationToken)
    {
        if (exception is not NotFoundException notFound)
            return false;  // not my exception type — try the next handler

        _log.LogWarning(exception, "Resource not found: {Resource}", notFound.Resource);

        httpContext.Response.StatusCode = StatusCodes.Status404NotFound;
        await httpContext.Response.WriteAsJsonAsync(new ProblemDetails
        {
            Status = 404,
            Title  = "Resource not found.",
            Detail = notFound.Resource
        }, cancellationToken);

        return true;  // handled — stop trying other handlers
    }
}
```

Register all handlers and enable exception handling:

```csharp
// Program.cs — before builder.Build():
builder.Services.AddExceptionHandler<NotFoundExceptionHandler>();
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();  // fallback
builder.Services.AddProblemDetails();

// Pipeline:
app.UseExceptionHandler();  // no path — uses IExceptionHandler chain
```

Handlers are tried in registration order. If no handler returns `true`, `UseExceptionHandler` falls through to the default `ProblemDetails` response. This replaces the pattern of a single `GlobalExceptionFilter` with a `switch` on exception type — each handler has a single responsibility and is independently testable.

### Requirements

`AddProblemDetails()` is required if you want the built-in `ProblemDetails` response generation. Without it, `UseExceptionHandler` can still be used — but no automatic RFC 7807 `ProblemDetails` response is generated. If you specify a path (`UseExceptionHandler("/error")`), your error controller produces the response and `AddProblemDetails` is not strictly needed.

```csharp
// startup — required for automatic ProblemDetails formatting:
builder.Services.AddProblemDetails();
app.UseExceptionHandler();
```

### Development vs production

In development, `WebApplication` auto-inserts `DeveloperExceptionPageMiddleware` before your pipeline. It intercepts unhandled exceptions and returns detailed diagnostic information — typically as HTML for browser requests and as a text-based diagnostic response for non-browser requests. It shows the stack trace, request headers, query string, cookies, and endpoint metadata. This middleware is auto-inserted only when `ASPNETCORE_ENVIRONMENT=Development` and the app was created with `WebApplication.CreateBuilder`.

In production `ASPNETCORE_ENVIRONMENT` is absent or set to `Production`, so the developer page is never shown and `UseExceptionHandler` returns only the safe `ProblemDetails` shape. Never set `Development` in a production environment.
