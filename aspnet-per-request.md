# ASP.NET Core — Per-Request Lifecycle
**Last reviewed:** 11 Jun 2026 · **Version baseline:** .NET 8

Every HTTP request travels through the same nested structure. It is not a flat sequence of steps — each layer wraps the layers inside it, and the layers inside only run if the outer layers let them through.

```
INCOMING REQUEST
└── Middleware pipeline (outermost wrapper)
    ├── ExceptionHandler — catches anything that throws below
    ├── HttpsRedirection
    ├── Cors
    ├── Authentication — populates HttpContext.User
    ├── Routing — matches URL, writes endpoint onto HttpContext
    ├── Authorization — reads that endpoint's [Authorize] metadata
    └── MVC layer
        ├── Filter pipeline (wraps the action)
        │   ├── ExceptionFilter
        │   ├── AuthorizationFilter
        │   ├── ResourceFilter
        │   ├── ActionFilter (OnActionExecuting)
        │   │   ├── Model binding — maps request data to parameters
        │   │   └── ⚡ Your action method
        │   ├── ActionFilter (OnActionExecuted)
        │   └── ResultFilter
        └── Serialisation — result converted to bytes on the way back out
OUTGOING RESPONSE (unwinds back through all layers in reverse)
```

---

## HttpContext — the shared object

When a request arrives, Kestrel (the built-in web server) reads the raw TCP bytes and parses them into an `HttpContext`. This is a single object that represents everything about the request and the response being built. Every layer — every middleware, every filter, your action method — reads from and writes to the same instance.

```
GET /api/users/5?include=roles HTTP/1.1
Accept: application/json
Authorization: Bearer eyJ…
Origin: https://myapp.com
```

After parsing:

- `HttpContext.Request.Method` = `"GET"`
- `HttpContext.Request.Path` = `"/api/users/5"`
- `HttpContext.Request.Query["include"]` = `"roles"`
- `HttpContext.Request.Headers["Authorization"]` = `"Bearer eyJ…"` — raw string, not verified yet
- `HttpContext.Request.Headers["Origin"]` = `"https://myapp.com"` — set by the browser, cannot be spoofed by JavaScript

A new **DI scope** is created for this request. All Scoped services are associated with this scope — created on first use, disposed when the request ends.

---

## Middleware pipeline

Middleware is a chain of functions. Each one receives `HttpContext` and a `next` delegate — a handle to the rest of the chain. Calling `next()` passes control inward. Not calling it short-circuits everything below.

```csharp
app.Use(async (ctx, next) =>
{
    // ON THE WAY IN — runs before calling next
    await next(ctx);
    // ON THE WAY BACK — runs after everything below has completed
});
```

**The rules:**

- Code before `await next(ctx)` runs on the way in. Code after runs on the way back.
- Not calling `next()` short-circuits — everything below is skipped, everything above still completes its return path.
- Once the response body starts writing, headers are locked. Check `ctx.Response.HasStarted` before touching them on the way back — modifying headers after the body has started throws `InvalidOperationException`.
- Each layer can only see what layers above it have written to `HttpContext`. Middleware before `UseAuthentication` cannot read `HttpContext.User` — it has not been populated yet.

**Registration styles:**

| Style | Behaviour |
|---|---|
| `app.Use()` | Calls `next()`. Standard pass-through. |
| `app.Run()` | Never calls `next()`. Terminal — place at the end. |
| `app.Map()` / `MapWhen()` | Branches on URL prefix or predicate. Branch does **not** rejoin. |
| `app.UseWhen()` | Branches on predicate. Branch **rejoins** the main pipeline. |

**Class-based middleware** — use when you need Scoped DI services. Inline lambdas cannot receive per-request services. Singleton-safe services go in the constructor; Scoped services go as extra `InvokeAsync` parameters.

```csharp
public class RequestLoggingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<RequestLoggingMiddleware> _log;

    public RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> log)
    { _next = next; _log = log; }

    public async Task InvokeAsync(HttpContext ctx, ITraceIdService trace)  // trace is Scoped — resolved per request
    {
        var sw = Stopwatch.StartNew();
        _log.LogInformation("→ {Method} {Path} trace={Trace}", ctx.Request.Method, ctx.Request.Path, trace.Current);
        await _next(ctx);
        _log.LogInformation("← {Status} in {Ms}ms", ctx.Response.StatusCode, sw.ElapsedMilliseconds);
    }
}
```

### ExceptionHandler

`UseExceptionHandler` is declared first in the pipeline so it wraps everything below. It is the outermost try/catch for the entire request.

When something throws and is not caught closer to the source, it bubbles up here. `UseExceptionHandler` catches it, logs it internally, and produces a safe RFC 7807 error response — no stack trace, no internal details exposed to the caller:

```json
{
  "type": "https://tools.ietf.org/html/rfc7231#section-6.6.1",
  "title": "An error occurred while processing your request.",
  "status": 500,
  "traceId": "00-abc123-def456-00"
}
```

The `traceId` is generated automatically for every request. Every log line produced during the request is tagged with the same ID. When a user reports an error, the `traceId` lets you find the full exception and stack trace in your logs without ever exposing them externally.

This requires `builder.Services.AddProblemDetails()` in startup — without that registration there is no formatter to call and no `ProblemDetails` shape is produced.

**Note:** `UseExceptionHandler` catches middleware exceptions and anything the MVC-layer `IExceptionFilter` did not handle. It does not replace `IExceptionFilter` — it is the outer net.

### CORS

CORS exists because browsers enforce a Same-Origin Policy — JavaScript on `https://myapp.com` cannot read a response from `https://api.myapp.com` unless the server explicitly says it is allowed. This is enforced by the browser, not the server. A direct HTTP client like Postman is not affected.

`UseCors` handles two cases:

**Regular cross-domain request (GET):** the browser attaches `Origin: https://myapp.com` automatically — this cannot be set or overridden by JavaScript. `UseCors` checks if that origin is in the allowed list and adds `Access-Control-Allow-Origin: https://myapp.com` to the response. Without it, the browser discards the response silently and JavaScript receives a generic network error with no useful detail.

**Preflight (before POST/PUT/DELETE):** before sending a mutating request to a different domain, the browser automatically sends an `OPTIONS` request first — no body, no auth token. `UseCors` recognises the `OPTIONS` method and short-circuits immediately with a 204 and the CORS headers. The browser inspects those headers and, if satisfied, sends the real request.

CORS must come **before** authentication. A preflight carries no credentials — if authentication challenges it first, CORS headers are never added and the browser reports a CORS error that masks what actually happened.

### Authentication

`UseAuthentication` reads credentials — typically a JWT in `Authorization: Bearer …` or an auth cookie — and builds an identity.

For a JWT: verifies the cryptographic signature, checks the expiry, and extracts the claims baked into the payload (user ID, email, roles, etc.). These become the `ClaimsPrincipal` stored in `HttpContext.User`.

`UseAuthentication` does **not** block the request on failure. Missing or invalid credentials leave `HttpContext.User` as an anonymous principal with no claims. The request continues. Blocking is `UseAuthorization`'s job.

### Routing

`UseRouting` matches the URL path and HTTP method against all registered route templates. When it finds a match it calls `HttpContext.SetEndpoint(endpoint)` — this writes the matched endpoint onto `HttpContext` where everything downstream can read it.

The `Endpoint` object carries:
- The handler (`RequestDelegate`) that will execute the action
- `EndpointMetadataCollection` — all the metadata stamped onto this endpoint at startup: `[Authorize]` attributes, policy names, `[Produces]`, route constraints, everything

Route values extracted from the URL (e.g. `id = "5"` from `/api/users/5`) are stored in `HttpContext.Request.RouteValues`.

If no route matches, `SetEndpoint` is never called — `GetEndpoint()` returns `null`, `RouteValues` is empty, and a 404 is returned. No controller is instantiated, no action code runs.

A route constraint failure (e.g. `{id:int}` receiving `"abc"`) also returns a 404, not a 400. The constraint drops the candidate as if the route did not match.

### Authorization

`UseAuthorization` reads the endpoint metadata that `UseRouting` just wrote onto `HttpContext`. It looks for `[Authorize]` attributes and policy names and evaluates them against `HttpContext.User`:

- Endpoint has no authorization requirements → passes through
- Endpoint requires authentication, `HttpContext.User` is anonymous → 401
- Identity present but missing the required role or policy → 403
- `[AllowAnonymous]` present → short-circuits immediately, skips all authorization regardless of `[Authorize]` also being present

**The critical dependency:** `UseAuthorization` must run after `UseRouting`. If placed before it, `GetEndpoint()` returns `null`, there is no metadata to read, and authorization falls through silently — no error, no 401, every `[Authorize]`-protected route is publicly accessible. The runtime guard catches the case where `UseAuthorization` was omitted entirely, but it does not catch misplacement.

---

## MVC layer

Once the middleware pipeline delivers the request to the MVC execution middleware, the MVC layer takes over. This is where the framework knows the specific controller and action — not just the HTTP method and URL, but the exact C# method being called, its parameter types, and all its attributes.

### Controller instantiation and DI

The framework creates a new controller instance for every request by asking the DI container to resolve its constructor parameters. You never call `new UsersController()`.

```csharp
public class UsersController : ControllerBase
{
    private readonly IUserService            _users;
    private readonly IPermissionsService     _permissionsApi;
    private readonly ILogger<UsersController> _log;

    public UsersController(IUserService users, IPermissionsService permissionsApi, ILogger<UsersController> log)
    {
        _users          = users;
        _permissionsApi = permissionsApi;
        _log            = log;
    }
}
```

The container looks up each parameter type in the registrations from startup, constructs the full dependency tree, and passes everything in. You declare what you need; the framework handles wiring.

### Filter pipeline

Filters are hooks that run at specific points around the action method. They nest — each outer filter wraps everything inside it.

```
IExceptionFilter              ← catches exceptions inside MVC only (not middleware)
  IAuthorizationFilter        ← [Authorize] evaluated here; 401/403 short-circuits
    IResourceFilter           ← before model binding; short-circuit here for cache hits
      IActionFilter.OnActionExecuting  ← before action; can modify arguments or cancel
          Model binding runs here
          ⚡ Your action method
      IActionFilter.OnActionExecuted   ← after action; ctx.Result is the IActionResult
    IResultFilter             ← before/after IActionResult.ExecuteResultAsync()
```

**Filters vs middleware:** filters run inside the MVC layer and have access to MVC-specific context — the action name, the actual argument values, the `IActionResult` before it is written. Middleware only sees the raw `HttpContext`. Use filters when you need that context.

```csharp
public class LogActionFilter : IActionFilter
{
    private readonly ILogger<LogActionFilter> _log;
    public LogActionFilter(ILogger<LogActionFilter> log) => _log = log;

    public void OnActionExecuting(ActionExecutingContext ctx)
        => _log.LogInformation("▶ {Action} args={Args}",
               ctx.ActionDescriptor.DisplayName, ctx.ActionArguments);

    public void OnActionExecuted(ActionExecutedContext ctx)
        => _log.LogInformation("■ {Action} result={Result}",
               ctx.ActionDescriptor.DisplayName, ctx.Result);
}

builder.Services.AddControllers(o => o.Filters.Add<LogActionFilter>());
```

### Model binding

The model binder extracts values from the request and maps them onto the action's parameters. With `[ApiController]`, sources are inferred automatically — you only need explicit attributes to override the default.

**Binding sources:**

| Attribute | Reads from | Notes |
|---|---|---|
| `[FromRoute]` | URL route segment | e.g. `{id}` → `id` |
| `[FromQuery]` | Query string | e.g. `?page=2` |
| `[FromBody]` | JSON request body | Only one per action — body stream reads once |
| `[FromHeader]` | HTTP request header | e.g. `X-Api-Version` |
| `[FromForm]` | Form fields / multipart | Use for `IFormFile`; mutually exclusive with `[FromBody]` |
| `[FromServices]` | DI container | Injects a service directly into a parameter |

**Default inference with `[ApiController]`:** complex types on POST/PUT → `[FromBody]`; simple types matching a route segment → `[FromRoute]`; remaining simple types → `[FromQuery]`.

**Validation:** data annotations on your model class are validated after binding. Any failure auto-returns a 400 before your action runs.

| Attribute | Validates |
|---|---|
| `[Required]` | Present and non-null/non-empty |
| `[MaxLength(n)]` | String or array length ≤ n |
| `[MinLength(n)]` | String or array length ≥ n |
| `[Range(min, max)]` | Numeric value within inclusive bounds |
| `[EmailAddress]` | Basic email format |
| `[RegularExpression(p)]` | Matches a regex pattern |
| `[Compare("OtherProp")]` | Two fields must match |

```csharp
[HttpPut("{id}")]
public async Task<ActionResult<UserDto>> UpdateUser(
    [FromRoute] int id,
    [FromBody] UpdateUserRequest body,
    [FromQuery] bool notify)
{
    var updated = await _users.UpdateAsync(id, body.Name, body.Email);
    if (updated is null) return NotFound();
    if (notify) await _emailService.SendProfileUpdatedAsync(updated.Email);
    return Ok(updated);
}

public class UpdateUserRequest
{
    [Required][MaxLength(100)]
    public string Name  { get; set; }

    [EmailAddress]
    public string Email { get; set; }
}
```

### Your action method — async

When your action method runs, every `await` on an I/O call releases the thread back to the pool — free to serve other requests while waiting. This is how a server with a small number of threads handles thousands of concurrent requests.

```csharp
[HttpGet("{id}")]
public async Task<ActionResult<UserDto>> GetUser(int id)
{
    var user = await _users.GetByIdAsync(id);          // thread released during DB query
    if (user is null) return NotFound();

    var perms = await _permissionsApi.GetForUserAsync(user.Id);  // released again
    return Ok(new UserDto { Id = user.Id, Name = user.Name, Permissions = perms });
}
```

Never block async code with `.Result` or `.Wait()` — these hold the thread hostage until the task completes. Under load, all threads get blocked and the server stops responding. This is thread-pool starvation.

**`ActionResult<T>`** is the standard return type. The `T` declares the happy-path shape — used by Swagger for documentation and enables `return dto;` as shorthand for `return Ok(dto)`. The `IActionResult` paths cover everything else.

| Status | Method | When |
|---|---|---|
| 200 | `Ok(data)` | Successful GET or PUT |
| 201 | `CreatedAtAction(…)` | POST that created a resource — adds a `Location` header |
| 204 | `NoContent()` | Successful DELETE or no response body |
| 400 | `BadRequest(errors)` | Invalid input (often automatic via `[ApiController]`) |
| 401 | `Unauthorized()` | Missing or invalid credentials |
| 403 | `Forbid()` | Valid identity, insufficient permissions |
| 404 | `NotFound()` | Resource does not exist |
| 500 | `Problem(…)` | Unexpected error — RFC 7807 shape |

### Serialisation

`ObjectResult` — the base class for results that carry a body — reads the `Accept` header and picks a formatter:

- `Accept: application/json` → JSON formatter
- `Accept: application/xml` → XML formatter (only if registered via `AddXmlSerializerFormatters()`)
- `Accept: */*` or missing → first registered formatter (JSON by default)
- No match → 406 Not Acceptable

`System.Text.Json` serialises your C# object to bytes. `Content-Type: application/json; charset=utf-8` and `Content-Length` are set automatically.

**Property attributes:**

| Attribute | Effect |
|---|---|
| `[JsonPropertyName("name")]` | Override serialised key — wins over global `PropertyNamingPolicy` |
| `[JsonIgnore]` | Exclude from serialisation entirely |
| `[JsonIgnore(Condition = WhenWritingNull)]` | Exclude only when value is null |
| `[JsonIgnore(Condition = WhenWritingDefault)]` | Exclude when value is the type default |
| `[JsonConverter(typeof(T))]` | Use a custom `JsonConverter<T>` for this property |
| `[JsonPropertyOrder(n)]` | Control output key order; lower numbers appear first |
| `[JsonExtensionData]` | Capture unknown JSON keys into `Dictionary<string, JsonElement>` |

```csharp
public class UserDto
{
    public int          Id          { get; set; }
    public string       Name        { get; set; }
    public List<string> Permissions { get; set; }
    [JsonIgnore]
    public string       PasswordHash { get; set; }  // never in the response
}
// → { "id": 5, "name": "Alice", "permissions": ["read", "write"] }
```

---

## Response — unwinding and cleanup

The response unwinds back through every layer in reverse. Each middleware runs its post-`await next()` code — logging elapsed time, appending headers, compressing the body.

Kestrel writes the final HTTP bytes over TCP:

```
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: 43

{"id":5,"name":"Alice","permissions":["read"]}
```

The request DI scope is then disposed. Every Scoped service created for this request has `Dispose()` called — `DbContext` connections return to the pool, `IDisposable` services are cleaned up, memory is freed. The kitchen resets, ready for the next request.

---

*Startup → `aspnet-startup.md`*
