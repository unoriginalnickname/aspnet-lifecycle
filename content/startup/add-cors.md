## AddCors

Registers the CORS policy. At request time, `UseCors()` in the pipeline uses this policy to decide which cross-domain requests to allow and which headers to add to the response.

```csharp
builder.Services.AddCors(o => o.AddPolicy("MyPolicy", policy =>
    policy
        .WithOrigins("https://myapp.com")
        .AllowAnyMethod()
        .AllowAnyHeader()));

app.UseCors("MyPolicy");
```

**The policy name** passed to `AddPolicy("MyPolicy", ...)` must match the name passed to `app.UseCors("MyPolicy")` exactly. A mismatch means CORS middleware runs but no policy matches — CORS headers are never added.

**Origin matching:**

```csharp
// specific origins only (production):
policy.WithOrigins("https://myapp.com", "https://admin.myapp.com")

// any origin — development only, never production:
policy.AllowAnyOrigin()

// wildcard subdomain — not natively supported; use a custom policy:
policy.SetIsOriginAllowedToAllowWildcardSubdomains()
      .WithOrigins("https://*.myapp.com")
```

**Methods and headers:**

```csharp
policy.AllowAnyMethod()                        // GET, POST, PUT, DELETE, PATCH, etc.
policy.WithMethods("GET", "POST")              // restrict to specific methods

policy.AllowAnyHeader()                        // any request header
policy.WithHeaders("Content-Type", "Accept")  // restrict to specific headers
```

**Credentials (cookies, Authorization header):**

By default, browsers do not send cookies or the `Authorization` header with cross-domain requests. To allow them:

```csharp
policy.AllowCredentials()
```

**`AllowCredentials()` cannot be combined with `AllowAnyOrigin()`** — the browser requires a specific origin when credentials are involved. This will throw at startup.

**Exposing response headers to JavaScript:**

Browsers hide most response headers from JavaScript by default. To expose custom headers:

```csharp
policy.WithExposedHeaders("X-Pagination-Total", "X-Request-Id")
```

**Per-controller or per-action CORS:**

Instead of a global policy, apply to specific endpoints:

```csharp
[EnableCors("MyPolicy")]   // apply policy
[DisableCors]              // opt out of the global policy
```

**Multiple policies:**

```csharp
builder.Services.AddCors(o => {
    o.AddPolicy("PublicApi", policy =>
        policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader());

    o.AddPolicy("AdminApi", policy =>
        policy.WithOrigins("https://admin.myapp.com").AllowCredentials());
});
```

Apply the appropriate policy per controller with `[EnableCors("PolicyName")]`.
