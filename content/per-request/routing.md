## Routing

Routing matches the incoming request to a specific controller action. At request time, the matching middleware (`EndpointRoutingMiddleware`) runs the URL and HTTP method through the routing table built at startup and writes the result onto `HttpContext` so every downstream layer can read it.

### How matching works — the DFA

The routing table is compiled into a Deterministic Finite Automaton (DFA) — a tree where each node represents a path segment decision. Given a URL like `/api/users/5`, the matcher walks the tree:

1. Does the next segment match `"api"`? Yes → move to that node
2. Does the next segment match `"users"`? Yes → move to that node
3. Does the next segment match a parameter `{id}`? Yes → extract `"5"` as the value of `id`

This tree traversal is fast and does not scan templates one by one.

### Candidate endpoints

A single URL can initially match multiple endpoints — for example, `GET /api/users/5` and `POST /api/users/5` share the same path template but differ by HTTP method. The matcher first finds all **candidate endpoints** whose path template matches the URL, then narrows them down using `IEndpointSelectorPolicy` implementations that evaluate the full request:

- HTTP method — `GET`, `POST`, `PUT`, `DELETE`, etc.
- `[Consumes]` content type constraints — e.g. only match if `Content-Type: application/json`
- Custom policies

This is what lets two actions share a route template and differ only by HTTP method:

```csharp
[HttpGet("{id}")]    // candidate for GET /api/users/5
public Task<ActionResult<UserDto>> GetUser(int id) { … }

[HttpPut("{id}")]    // candidate for PUT /api/users/5
public Task<ActionResult<UserDto>> UpdateUser(int id, [FromBody] UpdateUserRequest req) { … }
```

### Route constraints

Constraints are conditions that must be true for a candidate to remain in contention. They run during candidate evaluation:

```csharp
[HttpGet("api/users/{id:int}")]                  // id must parse as int
[HttpGet("api/posts/{slug:regex(^[a-z-]+$)}")]   // slug must match the pattern
[HttpGet("api/items/{id:min(1)}")]               // id must be >= 1
[HttpGet("api/reports/{year:int:range(2000,2099)}")] // chained constraints
```

A request to `/api/users/abc` against `api/users/{id:int}` fails the `int` constraint — the candidate is dropped, `SetEndpoint` is never called, and a 404 is returned. The cause is a failed constraint, not a missing route. This distinction matters when debugging unexpected 404s — the route exists, the constraint rejected the request.

Common built-in constraints:

| Constraint | Matches |
|---|---|
| `{id:int}` | Any integer — e.g. `5`, `-3` |
| `{id:long}` | Any long integer |
| `{id:guid}` | A GUID — e.g. `d3b07384-d113-4b8b-a3e6-5e62f47d26e5` |
| `{id:bool}` | `true` or `false` |
| `{id:min(n)}` | Integer >= n |
| `{id:max(n)}` | Integer <= n |
| `{id:range(min,max)}` | Integer between min and max |
| `{name:alpha}` | Alphabetic characters only |
| `{name:length(n)}` | String of exactly n characters |
| `{name:minlength(n)}` | String of at least n characters |
| `{name:regex(pattern)}` | String matching the pattern |

### Custom route constraints

When the built-in constraints are not enough — for example, validating a slug format or checking that a segment matches a specific domain pattern — implement `IRouteConstraint` and register it with a name in `RouteOptions.ConstraintMap`.

```csharp
// The constraint — validates that a segment is a valid slug: lowercase letters, digits, hyphens
public class SlugConstraint : IRouteConstraint
{
    private static readonly Regex _regex = new Regex(
        @"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public bool Match(
        HttpContext?          httpContext,
        IRouter?             route,
        string               routeKey,       // the parameter name — e.g. "slug"
        RouteValueDictionary values,         // all route values for this request
        RouteDirection       routeDirection) // IncomingRequest or UrlGeneration
    {
        if (!values.TryGetValue(routeKey, out var value) || value is null)
            return false;

        return _regex.IsMatch(value.ToString()!);
    }
}
```

Register the constraint in `Program.cs` before `builder.Build()`:

```csharp
builder.Services.Configure<RouteOptions>(options =>
    options.ConstraintMap.Add("slug", typeof(SlugConstraint)));
```

Use it in a route template exactly like a built-in constraint:

```csharp
[HttpGet("api/posts/{slug:slug}")]
public Task<ActionResult<PostDto>> GetPost(string slug) { … }

// GET /api/posts/my-first-post   → matches
// GET /api/posts/My_Invalid_Slug → 404 — constraint rejected the candidate
```

`routeDirection` is `UrlGeneration` when link generation (e.g. `CreatedAtAction`, `Url.Action`) calls the constraint in reverse — building a URL from route values. Return `false` from a constraint during `UrlGeneration` to prevent link generation from producing a URL that would not match an incoming request.

### Route priority order

When multiple candidates survive constraint evaluation, the router selects the best match using a fixed priority order. Higher priority routes are preferred:

1. **Literal segments** — exact string match, no parameters. `/api/users/admin` beats `/api/users/{id}`.
2. **Constrained parameters** — `{id:int}` beats `{id}` for an integer segment.
3. **Unconstrained parameters** — `{id}` matches anything the constrained version didn't.
4. **Optional parameters** — `{id?}` — present or absent.
5. **Catch-all parameters** — `{*path}` — lowest priority, matches everything remaining.

```csharp
[HttpGet("api/users/admin")]        // priority 1 — literal; wins for GET /api/users/admin
[HttpGet("api/users/{id:int}")]     // priority 2 — constrained; wins for GET /api/users/5
[HttpGet("api/users/{username}")]   // priority 3 — unconstrained; wins for GET /api/users/alice
[HttpGet("api/users/{*path}")]      // priority 5 — catch-all; wins for GET /api/users/a/b/c
```

The priority order is determined by the routing system at startup when the DFA is compiled — it is not evaluated per-request. Ambiguous routes at the same priority level that could both match the same URL cause an `AmbiguousMatchException` at request time.

### Controlling priority explicitly with WithOrder()

For Minimal API endpoints, `.WithOrder()` sets an explicit numeric priority. Lower numbers run first — a lower `Order` value beats a higher one when templates would otherwise be ambiguous:

```csharp
app.MapGet("/products/{id}", (int id) => $"Product {id}")
   .WithOrder(2);

app.MapGet("/products/featured", () => "Featured products")
   .WithOrder(1);  // lower number → higher priority → wins for GET /products/featured
```

For controller actions, explicit ordering is not available via `.WithOrder()` — the priority rules above apply. If two attribute routes genuinely conflict, refactor the templates to remove the ambiguity.

### What gets written onto HttpContext

Once a single endpoint is selected, the routing middleware mutates `HttpContext` in two ways:

**1. SetEndpoint**

```csharp
httpContext.SetEndpoint(endpoint);
```

The `Endpoint` object contains:

- `DisplayName` — e.g. `"UsersController.GetUser (MyApi)"` — used for logging, diagnostics
- `RequestDelegate` — the function that will execute the action
- `Metadata` — the `EndpointMetadataCollection` built at startup, containing all attribute objects

Every downstream layer — `UseAuthorization`, your own gap middleware, the MVC layer itself — reads the endpoint from `HttpContext.GetEndpoint()`.

**2. RouteValues**

```csharp
// GET /api/users/5 against route template "api/users/{id}"
HttpContext.Request.RouteValues["id"] == "5"

// GET /api/orders/42/items/7 against "api/orders/{orderId}/items/{itemId}"
HttpContext.Request.RouteValues["orderId"] == "42"
HttpContext.Request.RouteValues["itemId"] == "7"
```

Model binding reads from `RouteValues`, not from the raw URL. The values are already extracted and stored as strings — model binding then converts them to the target type (e.g. `"5"` → `int 5`).

Both mutations are visible to any middleware placed after routing runs.

### No match

If no route matches, neither mutation happens:

- `GetEndpoint()` returns `null`
- `RouteValues` is empty
- A `404 Not Found` is returned immediately

The controller is never instantiated. No filter runs. No action code executes. Your `NotFound()` return values are for when the resource doesn't exist — this 404 fires before you ever have the chance to return anything.

### Edge case — MapShortCircuit

Endpoints registered via `MapShortCircuit()` carry `ShortCircuitMetadata` and are executed by `EndpointRoutingMiddleware` itself — they never reach `EndpointMiddleware`. The two-middleware model holds for the normal controller case but is not universal.

```csharp
// Request to /favicon.ico is handled by EndpointRoutingMiddleware directly:
app.MapShortCircuit(404, "favicon.ico", "robots.txt");
```

### Legacy note

`HttpContext.GetRouteData()` returns a `RouteData` object — a pre-3.0 concept preserved for compatibility. It contains the same route values as `HttpContext.Request.RouteValues` but wrapped in the older type. Use `RouteValues` directly in new code.
