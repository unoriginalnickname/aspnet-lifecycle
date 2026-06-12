## Health check

Registered via `MapHealthChecks("/health")` in startup. A `GET /health` request is handled directly by `EndpointMiddleware` — it never enters the MVC layer. No filters, no model binding, no serialisation pipeline. The endpoint executor runs the registered checks and writes the result directly to the response.

Returns `200 OK` with `{ "status": "Healthy" }` if all checks pass. Returns `503 Service Unavailable` with `{ "status": "Unhealthy" }` if any check fails or throws.

```csharp
builder.Services.AddHealthChecks()
    .AddSqlServer(connectionString)
    .AddUrlGroup(new Uri("https://api.external.com"), "external-api");

app.MapHealthChecks("/health");
```

### Liveness vs readiness

Container orchestrators (Kubernetes, Azure Container Apps) distinguish two probe types:

**Liveness** — is the process alive and not deadlocked? If this fails, the orchestrator restarts the container. Should only check that the process itself is running — not external dependencies. A liveness check that fails because a database is down causes unnecessary restarts.

**Readiness** — is this instance ready to receive traffic? If this fails, the orchestrator removes the instance from the load balancer but does not restart it. Check external dependencies here — database connectivity, downstream services.

The pattern is two separate endpoints, each backed by a tagged subset of checks:

```csharp
builder.Services.AddHealthChecks()
    .AddCheck("self", () => HealthCheckResult.Healthy(), tags: new[] { "live" })
    .AddSqlServer(connectionString, tags: new[] { "ready" })
    .AddUrlGroup(new Uri("https://api.external.com"), tags: new[] { "ready" });

// liveness — only checks tagged "live":
app.MapHealthChecks("/health/live", new HealthCheckOptions
{
    Predicate = check => check.Tags.Contains("live")
});

// readiness — only checks tagged "ready":
app.MapHealthChecks("/health/ready", new HealthCheckOptions
{
    Predicate = check => check.Tags.Contains("ready")
});
```

Kubernetes probe configuration:

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
```

### Customising the response

By default the response body is a plain text status string. To return JSON with full check details:

```csharp
app.MapHealthChecks("/health", new HealthCheckOptions
{
    ResponseWriter = UIResponseWriter.WriteHealthCheckUIResponse
});
```

`UIResponseWriter` comes from `AspNetCore.HealthChecks.UI.Client`. Without it you can write your own:

```csharp
app.MapHealthChecks("/health", new HealthCheckOptions
{
    ResponseWriter = async (ctx, report) =>
    {
        ctx.Response.ContentType = "application/json";
        var result = new
        {
            status   = report.Status.ToString(),
            checks   = report.Entries.Select(e => new
            {
                name     = e.Key,
                status   = e.Value.Status.ToString(),
                duration = e.Value.Duration.TotalMilliseconds
            })
        };
        await ctx.Response.WriteAsJsonAsync(result);
    }
});
```

### Securing the health endpoint

By default health endpoints bypass authorization — they have no `[Authorize]` metadata. To require authentication on the readiness check but keep liveness public:

```csharp
app.MapHealthChecks("/health/live").AllowAnonymous();
app.MapHealthChecks("/health/ready").RequireAuthorization("HealthCheckPolicy");
```

For Kubernetes probes, keeping liveness public is typical — the orchestrator has no credentials to send. Readiness checks that expose sensitive dependency status may warrant protection in security-sensitive environments.

### Writing a custom check

Implement `IHealthCheck` to check anything not covered by a built-in package:

```csharp
public class ExternalCacheHealthCheck : IHealthCheck
{
    private readonly ICacheClient _cache;
    public ExternalCacheHealthCheck(ICacheClient cache) => _cache = cache;

    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await _cache.PingAsync(cancellationToken);
            return HealthCheckResult.Healthy("Cache is reachable.");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy("Cache unreachable.", ex);
        }
    }
}

// Register:
builder.Services.AddHealthChecks()
    .AddCheck<ExternalCacheHealthCheck>("cache", tags: new[] { "ready" });
```

`IHealthCheck` is resolved from the request DI scope — constructor injection works, including Scoped services.
