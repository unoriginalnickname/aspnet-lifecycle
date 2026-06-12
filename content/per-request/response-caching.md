## Response Caching and Compression

Three middlewares control what happens to responses on the way out — after your action has run and serialisation has produced bytes, but before those bytes reach the client. They sit late in the pipeline, after `UseAuthorization` and before or at `MapControllers`.

---

## UseResponseCompression

Compresses the response body before writing it to the network. Smaller payloads mean faster transfers, particularly for large JSON responses or APIs serving clients on slow connections.

```csharp
// Startup — before builder.Build():
builder.Services.AddResponseCompression(o =>
{
    o.EnableForHttps = true;   // compression over HTTPS — read the warning below
    o.Providers.Add<BrotliCompressionProvider>();
    o.Providers.Add<GzipCompressionProvider>();
    o.MimeTypes = ResponseCompressionDefaults.MimeTypes.Concat(
        new[] { "application/json" });  // ensure JSON is compressed
});

// Pipeline — before UseRouting so it wraps the entire response:
app.UseResponseCompression();
app.UseRouting();
```

**How it works:** reads the request's `Accept-Encoding` header (`gzip`, `br`, `identity`). If a supported encoding is listed and the response `Content-Type` is in the MIME type list, the middleware wraps `HttpContext.Response.Body` in a compression stream before the response is written. The framework sets `Content-Encoding: gzip` or `Content-Encoding: br` and removes `Content-Length` (since the compressed size is not known in advance).

**The HTTPS warning (`EnableForHttps`):** compression over HTTPS can enable the [BREACH attack](https://breachattack.com/) — an attacker who can observe encrypted traffic and inject content can infer secrets from compression ratios. The attack requires a specific set of conditions (attacker-controlled input in the response alongside secrets, many requests). For APIs serving only machine clients where secrets are not reflected in responses, the risk is low. For APIs that reflect user-supplied input alongside session tokens, do not enable compression over HTTPS without understanding the attack. By default `EnableForHttps = false`.

---

## UseResponseCaching

Adds HTTP caching headers (`Cache-Control`, `Vary`) to responses and caches responses server-side, serving subsequent identical requests from the cache without hitting the action.

```csharp
// Startup:
builder.Services.AddResponseCaching();

// Pipeline — after UseRouting, before MapControllers:
app.UseRouting();
app.UseResponseCaching();
app.MapControllers();
```

**How it works:** caches responses based on the URL and the `Vary` header. A request that matches a cached URL and headers is served directly from the in-memory cache — your action does not run. A cache miss passes through to the action normally. The response is cached only if it carries appropriate `Cache-Control` headers.

Control caching per action with `[ResponseCache]`:

```csharp
[HttpGet("{id}")]
[ResponseCache(Duration = 60, VaryByHeader = "Accept-Language")]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }
// → Cache-Control: public,max-age=60
// → Vary: Accept-Language
```

**Limitations:** `UseResponseCaching` only caches GET and HEAD responses with a 200 status code. It does not cache authenticated responses by default — responses with `Cache-Control: private` or `Authorization` headers in the request are not cached. It uses in-memory storage; the cache is lost on restart and is not shared across multiple app instances.

**`UseResponseCaching` vs `UseOutputCaching`:** `UseResponseCaching` is driven by HTTP cache semantics — it respects and sets `Cache-Control` headers, so clients and proxies can also cache. `UseOutputCaching` is a server-side-only cache that gives you full programmatic control independent of HTTP headers. For new apps targeting .NET 7+, prefer `UseOutputCaching`.

---

## UseOutputCaching (.NET 7+)

A server-side cache with full programmatic control — not driven by HTTP headers. Introduced in .NET 7 as a more flexible replacement for `UseResponseCaching` for server-controlled caching scenarios.

```csharp
// Startup:
builder.Services.AddOutputCache(o =>
{
    o.AddBasePolicy(b => b.Expire(TimeSpan.FromSeconds(60)));  // default for all endpoints
    o.AddPolicy("short", b => b.Expire(TimeSpan.FromSeconds(10)));
    o.AddPolicy("by-user", b => b.SetVaryByRouteValue("userId").Expire(TimeSpan.FromMinutes(5)));
});

// Pipeline:
app.UseOutputCache();
app.MapControllers();
```

Apply per endpoint:

```csharp
[HttpGet("{id}")]
[OutputCache(PolicyName = "by-user")]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }

// Or inline on the action:
[HttpGet("list")]
[OutputCache(Duration = 30)]
public async Task<ActionResult<List<UserDto>>> GetUsers() { … }
```

**Cache invalidation:** programmatically invalidate cached entries using tags:

```csharp
// Tag responses at cache time:
[OutputCache(Tags = new[] { "users" })]
public async Task<ActionResult<List<UserDto>>> GetUsers() { … }

// Invalidate all "users"-tagged entries — e.g. after a write operation:
public class UsersController : ControllerBase
{
    private readonly IOutputCacheStore _cache;
    public UsersController(IOutputCacheStore cache) => _cache = cache;

    [HttpPost]
    public async Task<ActionResult<UserDto>> CreateUser([FromBody] CreateUserRequest req)
    {
        var user = await _users.CreateAsync(req);
        await _cache.EvictByTagAsync("users", HttpContext.RequestAborted);
        return CreatedAtAction(nameof(GetUser), new { id = user.Id }, user);
    }
}
```

**Key differences from `UseResponseCaching`:**

| | `UseResponseCaching` | `UseOutputCaching` |
|---|---|---|
| Available since | .NET Core 1.0 | .NET 7 |
| Cache location | Server in-memory | Server in-memory (pluggable) |
| Driven by | HTTP `Cache-Control` headers | Server-side policy |
| Client/proxy caching | Yes — sets headers clients respect | No — server-side only |
| Authenticated responses | Not cached by default | Cached if policy allows |
| Cache invalidation | HTTP headers only | Programmatic via tags |
| New apps | Prefer OutputCaching | Yes |

---

## Pipeline position summary

```csharp
app.UseResponseCompression();  // before routing — wraps the entire response
app.UseRouting();
app.UseResponseCaching();      // after routing — can vary by route values
app.UseOutputCaching();        // after routing — can vary by route values
app.UseAuthorization();
app.MapControllers();
```

`UseResponseCompression` goes before routing because it needs to wrap the response body stream before anything writes to it. `UseResponseCaching` and `UseOutputCaching` go after routing because they can use route values as cache keys and need to know which endpoint is being targeted.

---

## What breaks and why

**`UseResponseCompression` placed after routing**
The middleware wraps `HttpContext.Response.Body` in a compression stream. If placed after routing, responses from `UseStatusCodePages` and any short-circuiting middleware between `UseResponseCompression` and routing are not compressed — only the endpoint response is. Place it before `UseRouting` to compress all responses.

**`UseResponseCaching` caches a response that shouldn't be cached**
`UseResponseCaching` caches any response with `Cache-Control: public` — including responses that contain user-specific data. If an action returns data scoped to the authenticated user but returns `Cache-Control: public`, the first user's response is cached and served to all subsequent users for that URL. Use `Cache-Control: private` or `[ResponseCache(NoStore = true)]` on actions that return user-specific data.

**`UseOutputCaching` serves stale data after a write**
`UseOutputCaching` does not automatically invalidate cache entries when the underlying data changes. If `GET /users` is cached and a `POST /users` creates a new user, the cached list is served until the cache expires. Use tag-based eviction (`EvictByTagAsync`) in write operations to invalidate related cache entries explicitly — see the tag invalidation example in the `UseOutputCaching` section above.

**`EnableForHttps = true` on a public API reflecting user input**
Enabling compression over HTTPS on an API that echoes user-supplied data in the same response as session tokens or API keys enables the BREACH attack. An attacker who can inject chosen content into requests can infer secret values from the change in compressed response size. Disable `EnableForHttps` (the default) on such APIs, or ensure user-controlled input and secrets never appear in the same response body.
