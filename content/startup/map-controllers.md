## MapControllers

Does two distinct things at two different times — startup work and request-time work. Understanding the split is important because the startup work is what makes the per-request matching fast.

### At startup — building the routing table

When `app.MapControllers()` is called during startup, before any request arrives, it scans every controller and action in the assembly via reflection. For each action it reads the route template, HTTP method attributes, and every other attribute on that action and its controller, then builds a `RouteEndpoint` object.

Each `RouteEndpoint` carries an `EndpointMetadataCollection` — a flat list of objects built from the attributes. Every `[Authorize]`, `[AllowAnonymous]`, `[EnableCors]`, `[EnableRateLimiting]`, `[HttpGet]`, `[Produces]`, and `[Consumes]` attribute becomes an object in that list. By the time the first request arrives, all metadata is already in memory and no reflection runs again.

This is why `UseAuthorization` can read `[Authorize]` at request time — the attribute was already converted to an object in the endpoint's metadata at startup. Authorization never inspects the C# attribute directly; it reads the pre-built metadata object.

```csharp
// These attributes become objects in EndpointMetadataCollection at startup:
[ApiController]
[Route("api/[controller]")]
[Authorize]                     // → IAuthorizeData object in metadata
public class UsersController : ControllerBase
{
    [HttpGet("{id:int}")]       // → RouteEndpoint with template "api/users/{id:int}"
    [AllowAnonymous]            // → IAllowAnonymous object in metadata
    public Task<ActionResult<UserDto>> GetUser(int id) { … }

    [HttpPost]                  // → RouteEndpoint with template "api/users"
    [Authorize(Roles = "Admin")]// → IAuthorizeData object with Role = "Admin"
    public Task<ActionResult<UserDto>> CreateUser([FromBody] CreateUserRequest req) { … }
}
```

### Adding metadata via the fluent API

Instead of putting `[Authorize]` on every controller, you can stamp it onto every registered endpoint in one call:

```csharp
app.MapControllers().RequireAuthorization();
```

From `AuthorizationMiddleware`'s perspective this is identical to `[Authorize]` on every action — `RequireAuthorization()` stamps an `AuthorizeAttribute` instance into each endpoint's `EndpointMetadataCollection` at startup.

### The Deterministic Finite Automaton

All registered `RouteEndpoint` objects are compiled into a tree structure called a Deterministic Finite Automaton (DFA). Each node in the tree represents a path segment decision — does the next segment match a literal like `"users"`, or a parameter like `{id}`, or a constrained parameter like `{id:int}`?

Matching a request at runtime is tree traversal — the matcher walks down the DFA following the path segments of the URL. This is significantly faster than scanning a list of route templates one by one, which is how routing worked before the DFA was introduced.

The DFA is compiled lazily — `EndpointRoutingMiddleware` does not compile it when `MapControllers()` is called, but on the first request after deployment. This is why the first request is slower than subsequent ones. If this matters in production, send a warmup request before exposing the app to real traffic.

### Link generation

The same routing table that powers incoming URL matching also powers outgoing URL generation. `Url.Action()`, `Url.RouteUrl()`, `CreatedAtAction()`, and `LinkGenerator` all run the table in reverse: given a controller name, action name, and route values, they find the matching `RouteEndpoint` and produce a URL.

```csharp
// After creating a user, return 201 with a Location header pointing to GET /api/users/5:
return CreatedAtAction(nameof(GetUser), new { id = created.Id }, created);
// → Location: https://api.myapp.com/api/users/5
```

This works because `MapControllers()` built the routing table at startup and both the matcher and the link generator read from the same `EndpointDataSource`.

### Attribute routing vs convention-based routing

Both produce `RouteEndpoint` objects — the same system underneath.

**Attribute routing** — route template declared directly on the action. Used by almost all API projects.

```csharp
[HttpGet("api/users/{id:int}")]
public Task<ActionResult<UserDto>> GetUser(int id) { … }
```

**Convention-based routing** — one route template declared once, controllers and actions matched by name.

```csharp
app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}");
```

Both can coexist. Attribute routing takes precedence when both would match the same URL. API projects use attribute routing exclusively. MVC projects serving HTML pages use convention-based routing as the default and add attribute routing on specific actions that need non-conventional URLs.

### At request time — executing the action

At request time `MapControllers()` also registered `EndpointMiddleware` in the pipeline. When `UseRouting` has matched a request to an endpoint, `EndpointMiddleware` reads that match from `HttpContext` and executes the action. This is covered in detail in the per-request routing section.

### UseRouting() alone is not sufficient

`UseRouting()` registers the matching middleware (`EndpointRoutingMiddleware`) — but without a `Map…()` call, `EndpointMiddleware` is never registered and no endpoints exist to match against. Every request returns 404. The two are two halves of one system.
