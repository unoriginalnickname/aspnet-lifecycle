## Controller

A new controller instance is created for every request by the DI container. You never call `new UsersController()` — the framework asks the container to resolve it, which resolves each constructor parameter in turn, building the full dependency graph. By the time your action method starts, every injected service is already constructed and available.

```csharp
public class UsersController : ControllerBase
{
    private readonly IUserService            _users;
    private readonly ILogger<UsersController> _log;

    public UsersController(IUserService users, ILogger<UsersController> log)
    {
        _users = users;
        _log   = log;
    }
}
```

The constructor takes `IUserService`, not `UserService` — an interface, not the concrete class. This means the controller depends on a contract that defines what operations are available, not on the specific class that implements them. The concrete class — which might talk to a database, call an API, or read from a cache — is wired up in startup via `builder.Services.AddScoped<IUserService, UserService>()`. The controller never knows or cares which implementation it gets. This separation keeps the controller thin, testable, and independent of infrastructure details.

Constructor parameters must be registered in the DI container in startup. An unregistered type throws `InvalidOperationException` at request time with a clear message naming the missing registration — not at startup.

The controller is disposed at the end of the request if it implements `IDisposable` or `IAsyncDisposable`.

### ControllerBase vs Controller

There are two base classes:

**`ControllerBase`** — for APIs. Provides `Ok()`, `NotFound()`, `BadRequest()`, `Problem()`, `User`, `HttpContext`, `Request`, `Response`, `RouteData`, `ModelState`, and `CreatedAtAction()`. No view support.

**`Controller`** — for MVC apps with Razor views. Inherits from `ControllerBase` and adds `View()`, `PartialView()`, `Json()`, `File()`, `Redirect()`, and `TempData`. For JSON APIs, use `ControllerBase` — `Controller` brings in the view engine overhead unnecessarily.

```csharp
// API controller — inherits ControllerBase:
[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase { … }

// AVOID for APIs — Controller adds view engine overhead:
public class UsersController : Controller { … }
```

### [ApiController]

The `[ApiController]` attribute on a controller class enables two automatic behaviours:

**Auto-400 on validation failure** — if model binding produces a `ModelState` error (a required field is missing, a value is out of range, a type conversion failed), the framework returns a `400 Bad Request` with a `ValidationProblemDetails` body before your action method runs. You do not need `if (!ModelState.IsValid)` checks.

**Binding source inference** — complex types on POST/PUT actions are automatically treated as `[FromBody]`; simple types matching a route segment are treated as `[FromRoute]`; remaining simple types are treated as `[FromQuery]`. Explicit `[From…]` attributes override inference. Covered in full in `per-request/binding.md`.

```csharp
[ApiController]           // enables both behaviours
[Route("api/[controller]")]
public class UsersController : ControllerBase { … }
```

### Accessing HttpContext, User, and request data from inside a controller

`ControllerBase` exposes these directly — no need to inject `IHttpContextAccessor`:

```csharp
public class UsersController : ControllerBase
{
    [HttpGet("me")]
    public ActionResult<UserProfileDto> GetMyProfile()
    {
        // HttpContext — the full request/response context:
        var requestId = HttpContext.TraceIdentifier;
        var clientIp  = HttpContext.Connection.RemoteIpAddress;

        // User — the ClaimsPrincipal populated by UseAuthentication:
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var email  = User.FindFirstValue(ClaimTypes.Email);
        bool isAdmin = User.IsInRole("Admin");

        // Request — shortcut to HttpContext.Request:
        var userAgent = Request.Headers["User-Agent"].ToString();
        var query     = Request.Query["filter"].ToString();

        // Response — shortcut to HttpContext.Response:
        Response.Headers.Append("X-Custom-Header", "value");

        // RouteData — the matched route values:
        var controller = RouteData.Values["controller"]?.ToString();

        // ModelState — binding and validation results:
        if (!ModelState.IsValid) return BadRequest(ModelState);

        return Ok(new UserProfileDto { Id = userId, Email = email });
    }
}
```

`User` is `null` before `UseAuthentication` has run — but since the controller runs after the entire middleware pipeline, `User` is populated by the time your action runs (either with an authenticated identity or an anonymous one).

### Controller lifetime and scope

The controller is Scoped — one instance per request, created by the DI container when the action is about to run, disposed when the request ends. This means:

- Injected Scoped services (e.g. `DbContext`) share the same scope as the controller — one instance for the life of the request
- Injected Transient services get a new instance each time they are resolved from the container
- Injected Singleton services are the same instance across all requests

Do not store per-request state in a Singleton service injected into a controller — Singleton instances are shared across all concurrent requests.
