## Result

Your return value determines the HTTP status code and response body. The framework converts it to bytes and writes it to the response after serialisation.

### ActionResult<T> — the standard return type

`ActionResult<T>` is the correct return type for controller actions that have a well-defined happy-path body. The `T` serves two purposes:

1. **Swagger documentation** — the framework reads `T` at startup and uses it to document the success response shape in the OpenAPI spec
2. **Implicit conversion** — returning `T` directly (e.g. `return user;`) implicitly wraps it in `Ok(user)`, saving a method call on the happy path

```csharp
// ActionResult<T> — preferred for documented APIs:
public async Task<ActionResult<UserDto>> GetUser(int id)
{
    var user = await _users.GetByIdAsync(id);
    if (user is null) return NotFound();
    return user;            // implicit Ok(user) — T enables this
}

// IActionResult — when no single T describes the happy path:
public async Task<IActionResult> GetUser(int id)
{
    var user = await _users.GetByIdAsync(id);
    return user is null ? NotFound() : Ok(user);
}
```

### Full result reference

| Status | Method | Class | Notes |
|---|---|---|---|
| 200 | `Ok(data)` | `OkObjectResult` | Standard success with body |
| 200 | `Ok()` | `OkResult` | Success, no body |
| 201 | `CreatedAtAction(…)` | `CreatedAtActionResult` | Created resource — adds `Location` header |
| 201 | `Created(uri, data)` | `CreatedResult` | Created at an explicit URI |
| 202 | `Accepted()` | `AcceptedResult` | Async operation started — not yet complete |
| 204 | `NoContent()` | `NoContentResult` | Success, no body — use for DELETE |
| 301/302 | `Redirect(url)` | `RedirectResult` | Permanent or temporary redirect |
| 400 | `BadRequest()` | `BadRequestResult` | Invalid request, no detail |
| 400 | `BadRequest(errors)` | `BadRequestObjectResult` | Invalid request with error detail |
| 401 | `Unauthorized()` | `UnauthorizedResult` | Missing or invalid credentials |
| 403 | `Forbid()` | `ForbidResult` | Authenticated but insufficient permissions |
| 404 | `NotFound()` | `NotFoundResult` | Resource does not exist, no detail |
| 404 | `NotFound(detail)` | `NotFoundObjectResult` | Resource does not exist with detail |
| 409 | `Conflict(detail)` | `ConflictObjectResult` | State conflict — duplicate, optimistic concurrency |
| 422 | `UnprocessableEntity(errors)` | `UnprocessableEntityObjectResult` | Semantically invalid — passes binding but fails business rules |
| 4xx/5xx | `Problem(…)` | `ObjectResult` with `ProblemDetails` | RFC 7807 error shape |
| any | `StatusCode(n, body)` | `ObjectResult` | Explicit status with body |

### Unauthorized() vs Forbid() — the precise distinction

These two are commonly confused. The choice is not about what you want to communicate — it's about which authentication scheme responds:

**`Unauthorized()`** returns a raw `401` directly from the action. It does not go through the authentication scheme and does not set a `WWW-Authenticate` header. Use it only when you need a raw 401 and understand why — for example, in a custom auth check where you want to bypass the scheme.

**`Forbid()`** calls `ForbidAsync()` on the authentication scheme. The scheme decides the response — JWT bearer returns `403 Forbidden`; cookie auth may redirect to an access-denied page. Use `Forbid()` for authorization failures on authenticated users — "you are logged in but do not have permission."

The correct distinction: use `Unauthorized()` for missing or invalid credentials; use `Forbid()` when the caller is authenticated but lacks the required permission.

```csharp
// MISTAKE — returning Unauthorized() for an auth failure on an authenticated user:
if (!User.IsInRole("Admin")) return Unauthorized();

// Correct — authenticated user, insufficient permissions:
if (!User.IsInRole("Admin")) return Forbid();

// Also correct: — raw 401 when you want to bypass the scheme entirely:
if (apiKey != _expectedKey) return Unauthorized();
```

### CreatedAtAction — why it exists

`Created(uri, body)` requires you to construct the URL string yourself. `CreatedAtAction` lets the routing system build it — you supply the action name and route values, and the framework generates the correct `Location` header:

```csharp
[HttpPost]
public async Task<ActionResult<UserDto>> CreateUser([FromBody] CreateUserRequest req)
{
    var user = await _users.CreateAsync(req);

    // CreatedAtAction(actionName, routeValues, body):
    // → 201 Created
    // → Location: https://api.myapp.com/api/users/42
    // → body: the UserDto
    return CreatedAtAction(nameof(GetUser), new { id = user.Id }, user);
}

[HttpGet("{id}")]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }
```

`nameof(GetUser)` resolves to `"GetUser"` at compile time — if the action is renamed, the compiler catches the broken reference. The route values `{ id = user.Id }` are matched against the `{id}` route segment on `GetUser`.

### Problem() — RFC 7807 error shape

`Problem()` produces a `ProblemDetails` response — the standard machine-readable error shape expected from APIs:

```csharp
return Problem(
    title:      "User not found.",
    detail:     $"No user with id {id} exists in this tenant.",
    statusCode: 404,
    type:       "https://myapi.com/errors/not-found",
    instance:   $"/api/users/{id}"
);
```

Prefer `Problem()` over `NotFound(message)` for error responses that need machine-readable structure. `NotFound("User not found")` returns a bare string body — `Problem(...)` returns the RFC 7807 shape that clients can reliably parse.

### TypedResults — Minimal API result types (.NET 7+)

`TypedResults` provides statically-typed versions of all result methods for use in Minimal APIs. The key difference from controller `Ok()`, `NotFound()` etc. is that `TypedResults` methods return concrete types rather than `IResult`, enabling Swagger to infer response shapes without `[ProducesResponseType]`:

```csharp
// Minimal API — TypedResults enables Swagger inference without attributes:
app.MapGet("/users/{id}", async (int id, IUserService users) =>
{
    var user = await users.GetByIdAsync(id);
    return user is null
        ? TypedResults.NotFound()
        : TypedResults.Ok(user);
});
```

In controller actions, use the standard helper methods (`Ok()`, `NotFound()` etc.) — `TypedResults` is for Minimal APIs.
