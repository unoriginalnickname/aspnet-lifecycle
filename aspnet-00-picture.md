# ASP.NET Core — The Picture
**Last reviewed:** 11 Jun 2026

Everything in ASP.NET Core splits into two completely separate moments: **startup**, which runs once when the process starts and builds the DI container and middleware pipeline, and **per-request**, which runs every time an HTTP request arrives. Nothing from startup runs again per-request. Nothing per-request exists yet during startup.

---

## Startup

Startup configures the system. Nothing runs here except configuration code. No requests exist yet.

### Phase 1 — Register services

The DI container is the object that creates and manages your services — you never call `new UserService()` directly, the container does it. In phase 1 you tell it what your app needs and how to build each thing. Nothing is constructed yet — the container stores recipes, not instances.

```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();    // registers the entire MVC stack — routing, binding, filters, JSON
builder.Services.AddProblemDetails(); // registers the { type, title, status, traceId } error formatter
builder.Services.AddSwaggerGen();     // registers API documentation generation — reads your controllers
                                      // and produces a machine-readable description of every endpoint
builder.Services.AddHealthChecks();   // registers health check services — reports whether the app
                                      // and its dependencies (database, external APIs) are reachable
builder.Services.AddScoped<IUserService, UserService>();
builder.Services.AddDbContext<AppDbContext>(...);
```

**Service lifetimes** — you must declare how long each object lives:

- **Singleton 🟢** — one instance for the whole app, shared across all requests simultaneously. Must not store per-request state.
- **Scoped 🔵** — one instance per request, created when the request arrives and disposed when it ends. `DbContext` is always Scoped because it holds a database connection that must not be shared between requests.
- **Transient 🟣** — new instance every time something asks for it.

Passing a Scoped service as a constructor parameter of a Singleton captures it for the app lifetime instead of the request lifetime — it leaks state between requests. → [Startup deep dive: captive dependency]

### Phase 2 — Declare the pipeline

```csharp
var app = builder.Build();  // container frozen — no more registrations after this line
```

Each `Use…()` call registers one middleware — a function that will receive each incoming request — at a fixed position in a chain. Nothing runs here. The chain fires only when a request arrives.

```csharp
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();        // serves /swagger/v1/swagger.json — the machine-readable API description
    app.UseSwaggerUI();      // serves the interactive docs UI at /swagger
}

app.UseExceptionHandler();   // registers error-catching middleware — declared first so it
                             // wraps every other middleware at request time
app.UseHttpsRedirection();   // registers HTTP → HTTPS redirect middleware
app.UseStaticFiles();        // serves files from wwwroot/ — e.g. GET /images/logo.png
                             // declared before routing so files are served without going through auth
app.UseCors("MyPolicy");     // registers cross-domain header middleware
app.UseAuthentication();     // registers JWT (JSON Web Token) verification middleware
app.UseRouting();            // registers URL matching middleware

// ── GAP ─────────────────────────────────────────────────────────────────
// Register middleware here that needs to know which action was matched
// before that action executes — e.g. authorization, rate limiting.
app.UseAuthorization();      // registers [Authorize] enforcement middleware
app.UseRateLimiter();        // registers rate limiting middleware
                             // position depends on what you key on:
                             // key on a route value — e.g. {tenantId} — register here, after UseRouting
                             // key on IP address or user identity — can register before UseRouting
// app.Use(...)              // register any middleware that needs to know the destination
// ────────────────────────────────────────────────────────────────────────

app.MapControllers();        // scans every controller and action, builds a map of every
                             // URL pattern to its controller action — ready before first request
app.MapHealthChecks("/health"); // registers GET /health — returns 200 if healthy, 503 if not
                                // runs outside the MVC layer — no filters, no model binding

app.Run();  // opens the TCP socket — the process stays alive here, accepting requests until shutdown
```

**Three ordering rules** — these are registration order rules. Wrong order produces silent failures at request time, not exceptions at startup:

- **`UseCors` before `UseAuthentication`** — registers CORS before auth so that at request time, the browser's automatic cross-domain check request (OPTIONS, no credentials, no body) is handled before authentication can challenge it and prevent CORS headers from being added.
- **`UseAuthentication` before `UseAuthorization`** — registers identity verification before access control so that at request time, `HttpContext.User` is populated before it is evaluated.
- **`UseRouting` before `UseAuthorization`** — registers URL matching before access control so that at request time, the matched action and its `[Authorize]` attribute are available when authorization runs. If this order is wrong, authorization finds nothing at request time and silently skips — every protected route becomes public, no error thrown.

→ [Startup deep dive: pipeline ordering and the gap]

---

## Per-request

When a request arrives, it travels through the middleware chain registered in startup, in the order it was declared. Each layer runs, passes the request inward, and runs again as the response travels back out.

Every request travels through the same layers in order. Layers above wrap layers below — each one runs on the way in and again as the response travels back out.

```
incoming request →

· ExceptionHandler    wraps everything below in a try/catch
                      any unhandled exception → { type, title, status, traceId }
                      stack trace stays in your logs, never sent to the caller

· HttpsRedirection    plain HTTP request → 301 redirect to HTTPS, nothing else runs

· StaticFiles         URL matches a file in wwwroot/ — e.g. GET /images/logo.png
                      serves the file immediately, nothing below runs
                      no match → passes through to the next layer

· Cors                adds Access-Control-Allow-Origin header if origin is in the
                      allowed list — e.g. myapp.com calling api.myapp.com
                      OPTIONS preflight (no credentials, no body) → 204 + headers, done

· Authentication      reads Authorization: Bearer <token> — the JWT (JSON Web Token,
                      an encoded credential signed by your auth server)
                      verifies the signature and expiry; extracts the claims —
                      the user's information encoded in the token, e.g. user ID, roles, email
                      populates HttpContext.User — readable by every downstream layer
                      never blocks — missing or invalid token leaves User as anonymous

· Routing             matches the request to an endpoint — e.g. GET /api/users/5 to
                      UsersController.GetUser, or GET /health to the health check handler
                      writes the match onto HttpContext so downstream layers can read it
                      no match → 404, controller never instantiated, your code never runs
                      constraint failure — {id:int} receiving "abc" → 404, not 400

  [gap]               middleware registered here can read the matched endpoint
                      before it executes — UseAuthorization, UseRateLimiter

· Authorization       reads the [Authorize] attribute on the matched action
                      anonymous when auth required → 401
                      authenticated but wrong role → 403

· Health check        GET /health — handler runs directly, no MVC layer involved
                      no filters, no model binding, no serialisation pipeline
                      returns 200 { status: "Healthy" } or 503 { status: "Unhealthy" }

· MVC layer           only reached by requests matched to a controller action

    · Controller      created per-request by the DI container; constructor parameters
                      — e.g. IUserService, ILogger — looked up and built automatically

    · Filters         functions that run before and after the action
                      can stop the request early — set a result without calling the action

    · Binding         maps route / query / body → action parameters
                      [ApiController]: source inferred from parameter type automatically
                      [Required] missing or invalid → 400 before your code runs

    · Your action     async method; thread released on every await to serve other requests

    · Result          Ok(data), NotFound(), CreatedAtAction(...) — status + body decided

    · Serialisation   C# object → JSON bytes
                      Content-Type: application/json set automatically
                      [JsonIgnore] fields excluded

← response travels back out through every layer in reverse
  Scoped services disposed. DbContext connections returned to the pool.
```

**Middleware** — each registered function receives `HttpContext` (the object holding everything about this request and response) and a handle to the rest of the chain. Code before calling the next function runs on the way in. Code after runs on the way back. Not calling the next function stops the request from going further — the response travels back immediately without passing through anything below. → [Per-request deep dive: middleware]

**Error handling** — `UseExceptionHandler` is the outer net, catching anything from any layer. The MVC exception filter catches only exceptions thrown inside a controller action. `traceId` in the error response maps to your logs — search it to find the full stack trace without exposing it to the caller. → [Per-request deep dive: error handling]

---

*Startup detail → `aspnet-startup.md` · Per-request detail → `aspnet-per-request.md`*
