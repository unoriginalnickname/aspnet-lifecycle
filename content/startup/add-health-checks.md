## AddHealthChecks

Registers health check services. At request time, `MapHealthChecks("/health")` handles `GET /health` directly — outside the MVC layer — by running all registered checks and returning the result.

```csharp
builder.Services.AddHealthChecks()
    .AddSqlServer(connectionString)                          // checks DB is reachable
    .AddUrlGroup(new Uri("https://api.external.com"), "ext") // checks external API
    .AddCheck("custom", () => HealthCheckResult.Healthy());  // your own check
```

Returns `200 { status: "Healthy" }` if all checks pass, `503 { status: "Unhealthy" }` if any fail.

Used by load balancers and container orchestrators (e.g. Kubernetes liveness and readiness probes) to decide whether to route traffic to this instance.

**What breaks:**

A slow health check blocks the response. Each registered check runs sequentially by default — if a check calls an external service that takes 10 seconds to time out, every `GET /health` request takes at least 10 seconds. Set a timeout per check:

```csharp
builder.Services.AddHealthChecks()
    .AddSqlServer(connectionString, timeout: TimeSpan.FromSeconds(3))
    .AddUrlGroup(new Uri("https://api.external.com"), timeout: TimeSpan.FromSeconds(2));
```

The overall health endpoint also has a configurable timeout via `HealthCheckOptions.Timeout`. If any check exceeds it, the endpoint returns `503` immediately.

A check that throws an unhandled exception fails with status `Unhealthy` and the exception message in the result — check `report.Entries[name].Exception` in a custom `ResponseWriter` if you need to log it. Exceptions do not propagate to the caller.
