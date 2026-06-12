## Service lifetimes

Every registration declares how long the container keeps the object alive. Wrong lifetime causes bugs that only appear under load.

**Singleton** — one instance for the entire app lifetime, shared across all requests simultaneously. Must not store per-request state.

```csharp
builder.Services.AddSingleton<ICache, MemoryCache>();
```

Use for: config readers, in-memory caches, `HttpClient` (via `IHttpClientFactory`).

**Scoped** — one instance per HTTP request. Created when the request arrives, disposed when it ends.

```csharp
builder.Services.AddScoped<IUserService, UserService>();
```

Use for: `DbContext`, anything that tracks state for one unit of work. `DbContext` must be Scoped — it holds a database connection that must not be shared between requests.

The registration maps an interface (`IUserService`) to a concrete implementation (`UserService`). The controller that injects `IUserService` never knows which class implements it — the container provides `UserService` at runtime, but in a test you can register a fake implementation instead. This is why you register and inject interfaces rather than concrete types: the controller depends on a contract, not an implementation, so the implementation can be swapped without touching the controller.

**Transient** — new instance every time something asks for it.

```csharp
builder.Services.AddTransient<IEmailSender, SmtpSender>();
```

Use for: lightweight, stateless helpers. Avoid for anything that holds connections or is expensive to construct.

**The captive dependency trap**

Passing a Scoped service as a constructor parameter of a Singleton captures it for the app lifetime instead of the request lifetime — it leaks state between requests.

```csharp
// WRONG — UserRepository is Scoped, captured inside Singleton forever
builder.Services.AddSingleton<IMyCache, MyCache>();
builder.Services.AddScoped<IUserRepository, UserRepository>();

public class MyCache
{
    public MyCache(IUserRepository users) { … }  // captured for app lifetime
}

// Fix — make MyCache Scoped too, or use IServiceScopeFactory
builder.Services.AddScoped<IMyCache, MyCache>();
```

ASP.NET detects this in development and throws. Enable it in production explicitly:

```csharp
builder.Host.UseDefaultServiceProvider(o => o.ValidateScopes = true);
```
