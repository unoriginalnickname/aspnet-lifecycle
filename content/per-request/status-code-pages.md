## StatusCodePages

`UseExceptionHandler` handles exceptions — code that throws. `UseStatusCodePages` handles a different problem: responses that complete without throwing but carry an error status code (4xx or 5xx) with no response body. The canonical case is a 404 returned by the router when no endpoint matches — no exception is thrown, `UseExceptionHandler` never fires, and the client receives a bare status code with an empty body.

```csharp
// Pipeline order — before routing so it can intercept status codes set by anything below:
app.UseStatusCodePages();
app.UseRouting();
app.UseAuthorization();
app.MapControllers();
```

### What triggers it

`UseStatusCodePages` intercepts any response where:
- The status code is 400–599
- The response body has not yet been written (body is empty)
- The `Content-Type` header has not been set

If your action returns `NotFound()` with a detail message — `NotFound("User not found")` — the response body is already written by `ObjectResult` and `UseStatusCodePages` leaves it alone. It only acts on responses with an empty body, so it never overwrites your own error responses.

### Three registration styles

**Plain — writes a minimal text response:**

```csharp
app.UseStatusCodePages();
// → "Status Code: 404; Not Found"
```

Useful only for debugging. Not appropriate for APIs.

**With format string — writes a formatted text or JSON response:**

```csharp
app.UseStatusCodePages("application/json", "{{\"status\": {0}}}");
// → {"status": 404}
// {0} is replaced with the status code integer
```

**With re-execution — re-executes the pipeline to a handler path:**

```csharp
app.UseStatusCodePagesWithReExecute("/error/{0}");
// For a 404: re-executes the pipeline as GET /error/404
// {0} is replaced with the status code
```

The re-execution approach lets a controller action produce the full error response, including `ProblemDetails`:

```csharp
[ApiController]
public class ErrorController : ControllerBase
{
    [Route("/error/{statusCode:int}")]
    public IActionResult HandleStatusCode(int statusCode)
    {
        return statusCode switch
        {
            404 => Problem(title: "Not found.",          statusCode: 404),
            405 => Problem(title: "Method not allowed.", statusCode: 405),
            _   => Problem(title: "An error occurred.",  statusCode: statusCode)
        };
    }
}
```

`UseStatusCodePagesWithReExecute` re-executes in the same request scope and stores the original request details in `IStatusCodeReExecuteFeature` on `HttpContext.Features`. The error action can read it to log the original path or include it in the response:

```csharp
[ApiController]
public class ErrorController : ControllerBase
{
    private readonly ILogger<ErrorController> _log;
    public ErrorController(ILogger<ErrorController> log) => _log = log;

    [Route("/error/{statusCode:int}")]
    public IActionResult HandleStatusCode(int statusCode)
    {
        // IStatusCodeReExecuteFeature carries:
        //   OriginalPath       — e.g. "/api/users/999"
        //   OriginalPathBase   — e.g. "" or "/api" if UsePathBase is configured
        //   OriginalQueryString — e.g. "?include=roles"
        var feature = HttpContext.Features.Get<IStatusCodeReExecuteFeature>();

        _log.LogWarning("HTTP {StatusCode} on {Path}{Query}",
            statusCode,
            feature?.OriginalPath,
            feature?.OriginalQueryString);

        return Problem(
            title:      statusCode == 404 ? "Not found." : "An error occurred.",
            detail:     feature is not null
                            ? $"No resource at {feature.OriginalPath}."
                            : null,
            statusCode: statusCode,
            instance:   feature?.OriginalPath
        );
    }
}
```

The `{statusCode:int}` route parameter gives the same value as `IStatusCodeReExecuteFeature` — reading it from the route is simpler when you only need the code. Read `IStatusCodeReExecuteFeature` when you need the original path, query string, or path base to log or include in the error response.

**With redirect — redirects to a handler path:**

```csharp
app.UseStatusCodePagesWithRedirects("/error/{0}");
```

This sends a `302` redirect to the client, which then makes a second request. The original status code is lost from the client's perspective — they only see the 302 and then whatever the error page returns. Prefer `UseStatusCodePagesWithReExecute` for APIs; redirects are more appropriate for HTML-based apps where the browser address bar matters.

### Relationship to UseExceptionHandler

The two middlewares handle different failure modes and are typically both registered:

```csharp
app.UseExceptionHandler();       // handles thrown exceptions → 500
app.UseStatusCodePages(...);     // handles empty error responses → 404, 405, etc.
```

`AddProblemDetails()` in startup causes both `UseExceptionHandler` and `UseStatusCodePages` to produce RFC 7807 `ProblemDetails` responses automatically — you don't need to configure a path or format string when `AddProblemDetails` is registered and `UseStatusCodePages()` is called with no arguments.

```csharp
// Minimal setup — both produce ProblemDetails automatically:
builder.Services.AddProblemDetails();
app.UseExceptionHandler();
app.UseStatusCodePages();
```

### What breaks

**`UseStatusCodePages` placed after routing**
If placed after `UseRouting`, it won't intercept 404s produced by the routing layer — routing sets the status code and short-circuits before `UseStatusCodePages` runs. Place it before `UseRouting`.

**Action returns `NotFound()` but still triggers `UseStatusCodePages`**
`NotFound()` with no argument returns a `404` with an empty body — `UseStatusCodePages` will intercept it. Use `NotFound(detail)` or `Problem(statusCode: 404, title: "...")` to write a body and prevent interception.
