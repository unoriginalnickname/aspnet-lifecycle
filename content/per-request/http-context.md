## HttpContext

`HttpContext` is a single object created by Kestrel when a request arrives and passed through every middleware and every MVC layer for the lifetime of that request. Every middleware in the pipeline receives the same instance. It is the shared mutable state of the request — middleware communicates with downstream middleware by writing onto it before calling `next()`, and reads what upstream middleware has written.

```csharp
public abstract class HttpContext
{
    public abstract HttpRequest         Request         { get; }
    public abstract HttpResponse        Response        { get; }
    public abstract ClaimsPrincipal     User            { get; set; }
    public abstract IServiceProvider    RequestServices { get; set; }
    public abstract ConnectionInfo      Connection      { get; }
    public abstract WebSocketManager    WebSockets      { get; }
    public abstract CancellationToken   RequestAborted  { get; set; }
    public abstract ISession            Session         { get; }
    public abstract IFeatureCollection  Features        { get; }
    public abstract IDictionary<object, object?> Items  { get; set; }
    public abstract string              TraceIdentifier { get; set; }
}
```

---

## HttpContext.Request

Everything about the incoming request. Populated by Kestrel when it parses the raw TCP bytes — available from the first middleware.

```csharp
HttpContext.Request.Method          // "GET", "POST", "PUT", "DELETE", etc.
HttpContext.Request.Path            // "/api/users/5" — the path after the PathBase prefix
HttpContext.Request.PathBase        // app path prefix — see UsePathBase below
HttpContext.Request.QueryString     // "?include=roles&page=2" — raw string
HttpContext.Request.Query           // IQueryCollection — parsed: Query["include"] == "roles"
HttpContext.Request.Headers         // IHeaderDictionary — Headers["Authorization"] == "Bearer eyJ…"
HttpContext.Request.ContentType     // "application/json; charset=utf-8"
HttpContext.Request.ContentLength   // body length in bytes, or null if not specified
HttpContext.Request.Body            // Stream — the raw request body; can only be read once
HttpContext.Request.HasFormContentType  // true if Content-Type is form or multipart
HttpContext.Request.Form            // IFormCollection — populated when HasFormContentType is true
HttpContext.Request.RouteValues     // populated by UseRouting — e.g. { "id": "5" }
HttpContext.Request.IsHttps         // true if the connection is HTTPS
HttpContext.Request.Host            // "api.myapp.com" from the Host header
HttpContext.Request.Scheme          // "https"
```

### PathBase and UsePathBase

`Request.PathBase` and `Request.Path` together make up the full URL path. Normally `PathBase` is empty and `Path` is the entire path — `/api/users/5`. When the app is mounted at a sub-path, `PathBase` holds the prefix and `Path` holds the remainder.

The scenario is a reverse proxy hosting multiple apps under different path prefixes on the same domain:

```
https://mycompany.com/api/   → proxied to this ASP.NET Core app
https://mycompany.com/admin/ → proxied to a different app
```

Without any configuration, the app sees the full path including the `/api` prefix. Route templates defined without the prefix — `api/users/{id}` on a controller — will not match `/api/api/users/5`, but they will appear to match `/api/users/5` only if the template happens to include the prefix segment literally. More seriously, link generation (`CreatedAtAction`, `Url.Action`) produces URLs without the proxy prefix — it returns `Location: /users/5` instead of `Location: /api/users/5`, which is broken for the client who must go through the proxy.

`app.UsePathBase("/api")` solves this by stripping the prefix from `Request.Path` and storing it in `Request.PathBase` before routing runs. The app then sees `/users/5` in `Path` and `/api` in `PathBase`. Routing matches against the shorter path. Link generation prepends `PathBase` automatically, so `Location: /api/users/5` is produced correctly.

```csharp
// Program.cs — call before UseRouting so the prefix is stripped before matching:
app.UsePathBase("/api");

app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
```

**`UsePathBase` must come before `UseRouting`.** If it runs after, routing has already matched against the full path including the prefix — the match either fails (404) or produces wrong route values. Placing it before routing ensures `Path` is already stripped when the DFA runs.

**The prefix must also be configured at the reverse proxy.** `UsePathBase` strips the prefix from the request ASP.NET Core receives, but it does not tell the proxy how to route. The proxy must be configured to forward `/api/*` to this app and to forward the original path in the `X-Forwarded-Prefix` header or to strip the prefix before forwarding. If the proxy strips `/api` before forwarding, `UsePathBase` is not needed — the app receives `/users/5` directly.

**`UsePathBase` is case-sensitive.** A request for `/Api/users/5` will not have `/api` stripped. Match the prefix exactly as the proxy sends it.

```csharp
// After UsePathBase("/api"):
// Request URL: https://mycompany.com/api/users/5
// Request.PathBase == "/api"
// Request.Path     == "/users/5"    ← what routing sees
// Request.Path + Request.PathBase  == "/api/users/5"  ← the full original path
```

`Request.Body` is a stream that can only be read once. If you need to read it multiple times — in middleware and then in model binding — enable request body buffering first:

```csharp
app.Use(async (ctx, next) =>
{
    ctx.Request.EnableBuffering();  // wraps Body in a buffered stream
    await next(ctx);
});
```

`Request.RouteValues` is empty until `UseRouting` runs. Middleware placed before `UseRouting` cannot read route values.

---

## HttpContext.Response

The outgoing response being built. Writable from any middleware, but headers and status code are committed once the body starts writing — check `Response.HasStarted` before modifying them in post-response code.

```csharp
HttpContext.Response.StatusCode     // int — set before writing the body; default 200
HttpContext.Response.Headers        // IHeaderDictionary — append before body starts
HttpContext.Response.ContentType    // shortcut for Headers["Content-Type"]
HttpContext.Response.ContentLength  // shortcut for Headers["Content-Length"]
HttpContext.Response.Body           // Stream — write response bytes here
HttpContext.Response.HasStarted     // true once the body has begun writing — headers now committed
```

Once `HasStarted` is `true`, attempting to set `StatusCode` or modify headers throws `InvalidOperationException`. Check `HasStarted` in any middleware that touches the response after calling `await next(ctx)`:

```csharp
await next(ctx);
if (!ctx.Response.HasStarted)
    ctx.Response.Headers.Append("X-Timing", elapsed.ToString());
```

---

## HttpContext.User

A `ClaimsPrincipal` representing the caller's identity. Set to an anonymous principal (no claims, `IsAuthenticated == false`) until `UseAuthentication` verifies the request's credentials and builds the identity from the token's claims.

Empty until `UseAuthentication` runs. Every middleware placed before `UseAuthentication` in the pipeline reads an anonymous principal regardless of what credentials the request carries.

Covered in full in [per-request/authentication.md].

---

## HttpContext.RequestServices

The DI scope for this request — an `IServiceProvider` scoped to the current request's lifetime. All `Scoped` services resolved from it are the same instances for the duration of this request and are disposed when the request ends.

```csharp
// Inside middleware or a filter — resolve a service from the request scope:
var userService = ctx.RequestServices.GetRequiredService<IUserService>();
```

This is service locator pattern — use it sparingly. Prefer constructor injection wherever the framework supports it (controllers, middleware classes, filters). Use `RequestServices` only in places where constructor injection is not available, such as inside attribute constructors.

---

## HttpContext.Features

A collection of feature interfaces — the extensibility mechanism that ASP.NET Core components use to attach and read structured data on `HttpContext`. Each feature is stored under its interface type as the key.

You rarely access `Features` directly in application code, but it is what the framework itself uses:

```csharp
// UseRouting calls this to store the matched endpoint:
httpContext.SetEndpoint(endpoint);
// which internally does:
httpContext.Features.Set<IEndpointFeature>(new EndpointFeature { Endpoint = endpoint });

// Anything downstream reads it via:
var endpoint = httpContext.GetEndpoint();
// which internally does:
httpContext.Features.Get<IEndpointFeature>()?.Endpoint;
```

Other features stored here include `IHttpConnectionFeature` (remote IP, local port), `ITlsConnectionFeature` (TLS certificate), `IHttpRequestBodyDetectionFeature`, and `ISessionFeature`. Server implementations (Kestrel, IIS) populate different subsets of these at request start.

---

## HttpContext.Items

A `Dictionary<object, object?>` for passing arbitrary data between middleware within a single request. Scoped to the request — cleared when the request ends. Neither typed nor validated.

```csharp
// Middleware A — write:
ctx.Items["tenantId"] = resolvedTenantId;

// Middleware B downstream — read:
var tenantId = ctx.Items["tenantId"] as string;
```

Use string or static object keys to avoid collisions between unrelated middleware. For anything that needs to be shared across multiple middleware or accessed in filters and controllers, a typed Scoped service registered in DI is preferable — it is type-safe, injectable, and disposable.

---

## HttpContext.TraceIdentifier

A unique string identifier assigned to this request. Logging providers can include `TraceIdentifier` in log entries — when configured, every log line written during the request carries the same ID, allowing the full request context to be reconstructed from logs. When a client reports an error using the `traceId` from a `ProblemDetails` response, this is the value you search for.

```csharp
var traceId = ctx.TraceIdentifier;  // e.g. "00-abc123def456-789abc-00" (W3C TraceContext format)
```

Set automatically by the framework. Do not set it manually.

---

## HttpContext.Connection

Information about the underlying TCP connection.

```csharp
HttpContext.Connection.RemoteIpAddress   // IPAddress — the client's IP
HttpContext.Connection.RemotePort        // int — the client's port
HttpContext.Connection.LocalIpAddress    // IPAddress — the server's IP on this connection
HttpContext.Connection.LocalPort         // int — the server's listening port (e.g. 443)
HttpContext.Connection.Id                // string — unique connection identifier
```

`RemoteIpAddress` is the direct TCP peer — if your app is behind a reverse proxy (nginx, an Azure load balancer), this is the proxy's IP, not the client's. Use `X-Forwarded-For` header processing (`UseForwardedHeaders`) to recover the original client IP.

---

## HttpContext.RequestAborted

A `CancellationToken` that is cancelled when the client disconnects before the response is complete — dropped connection, browser tab closed, client timeout. Pass it to async operations so work stops immediately if the client is gone:

```csharp
[HttpGet("{id}")]
public async Task<ActionResult<UserDto>> GetUser(int id, CancellationToken cancellationToken)
{
    // cancellationToken is HttpContext.RequestAborted, injected by the framework
    var user = await _users.GetByIdAsync(id, cancellationToken);
    // if the client disconnected, the DB query is cancelled and an OperationCanceledException is thrown
    return Ok(user);
}
```

The framework injects `HttpContext.RequestAborted` automatically when an action parameter is of type `CancellationToken` — you do not need to read it from `HttpContext` directly.

---

## HttpContext.Session

Access to the server-side session store. Only available if session middleware is configured (`AddSession()` + `UseSession()`). Disabled by default — APIs typically use JWTs for state rather than server-side sessions.

```csharp
// Read:
var value = ctx.Session.GetString("key");

// Write:
ctx.Session.SetString("key", "value");
```

Not covered in this reference — session-based state belongs to server-rendered web app patterns, not JSON APIs.
