## RateLimiter

Rate limiting controls how many requests a client can make within a time window. Requests that exceed the limit receive a `429 Too Many Requests` response before the action ever runs — the rate limiter sits in the gap between `UseRouting` and the endpoint, so it has access to route values and endpoint metadata but the action has not yet executed.

Added in .NET 7. Requires `AddRateLimiter()` in startup.

### Pipeline position

`UseRateLimiter` must go after `UseRouting` and before `MapControllers`. The gap position is what gives it two capabilities that wouldn't be available earlier:

- **Route values** — limit by a route segment like `{tenantId}` or `{userId}` from the URL
- **Endpoint metadata** — per-endpoint policies via `[EnableRateLimiting("policyName")]` on the action, or exempt specific endpoints with `[DisableRateLimiting]`

```csharp
app.UseRouting();
app.UseRateLimiter();       // in the gap — after routing, before execution
app.UseAuthorization();
app.MapControllers();
```

### The four built-in algorithms

**Fixed window** — counts requests in fixed time buckets. A new bucket starts every period, independent of when requests arrive:

```csharp
builder.Services.AddRateLimiter(o => o.AddFixedWindowLimiter("fixed", options =>
{
    options.PermitLimit         = 100;   // max requests per window
    options.Window              = TimeSpan.FromMinutes(1);
    options.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
    options.QueueLimit          = 10;    // requests to queue beyond PermitLimit before rejecting
}));
```

**Sliding window** — spreads the window across segments, smoothing out burst traffic at window boundaries:

```csharp
builder.Services.AddRateLimiter(o => o.AddSlidingWindowLimiter("sliding", options =>
{
    options.PermitLimit         = 100;
    options.Window              = TimeSpan.FromMinutes(1);
    options.SegmentsPerWindow   = 6;     // window divided into 6 × 10-second segments
    options.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
    options.QueueLimit          = 0;
}));
```

**Token bucket** — tokens accumulate over time up to a maximum. Each request consumes one token. Allows bursts up to the bucket capacity:

```csharp
builder.Services.AddRateLimiter(o => o.AddTokenBucketLimiter("token", options =>
{
    options.TokenLimit          = 100;   // max tokens (burst capacity)
    options.ReplenishmentPeriod = TimeSpan.FromSeconds(10);
    options.TokensPerPeriod     = 20;    // tokens added each period
    options.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
    options.QueueLimit          = 0;
}));
```

**Concurrency** — limits the number of concurrent requests, not requests per time window. Useful for limiting parallelism on expensive operations:

```csharp
builder.Services.AddRateLimiter(o => o.AddConcurrencyLimiter("concurrency", options =>
{
    options.PermitLimit = 10;   // max 10 requests in flight simultaneously
    options.QueueLimit  = 5;
}));
```

### Applying policies to endpoints

**Global** — applies to all endpoints unless opted out:

```csharp
builder.Services.AddRateLimiter(o =>
{
    o.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(ctx =>
        RateLimitPartition.GetFixedWindowLimiter(
            partitionKey: ctx.User.Identity?.Name ?? ctx.Request.Headers.Host.ToString(),
            factory: _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 100,
                Window      = TimeSpan.FromMinutes(1)
            }));
    o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
});
```

**Per endpoint** — named policy applied via attribute:

```csharp
// Startup:
builder.Services.AddRateLimiter(o => o.AddFixedWindowLimiter("api", options =>
{
    options.PermitLimit = 60;
    options.Window      = TimeSpan.FromMinutes(1);
}));

// Controller:
[HttpGet("{id}")]
[EnableRateLimiting("api")]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }

// Exempt a specific endpoint from a global limiter:
[HttpGet("health")]
[DisableRateLimiting]
public IActionResult HealthCheck() => Ok();
```

### Partitioning — per-user vs per-IP limits

A single policy can apply different limits to different callers using `PartitionedRateLimiter`. The partition key determines which bucket a request counts against:

```csharp
builder.Services.AddRateLimiter(o =>
    o.AddPolicy("per-user", ctx =>
        RateLimitPartition.GetFixedWindowLimiter(
            // authenticated users get their own bucket by user ID
            // anonymous requests share a bucket keyed on IP
            partitionKey: ctx.User.Identity?.IsAuthenticated == true
                ? ctx.User.FindFirstValue(ClaimTypes.NameIdentifier)!
                : ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            factory: _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 100,
                Window      = TimeSpan.FromMinutes(1)
            })));
```

### The 429 response and Retry-After

When a request is rejected, the middleware returns `429 Too Many Requests`. To include a `Retry-After` header telling the client when to try again:

```csharp
builder.Services.AddRateLimiter(o =>
{
    o.OnRejected = async (context, cancellationToken) =>
    {
        context.HttpContext.Response.StatusCode = StatusCodes.Status429TooManyRequests;

        if (context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter))
            context.HttpContext.Response.Headers.RetryAfter =
                ((int)retryAfter.TotalSeconds).ToString();

        await context.HttpContext.Response.WriteAsJsonAsync(new ProblemDetails
        {
            Status = 429,
            Title  = "Too many requests."
        }, cancellationToken);
    };
});
```

### What breaks

**`UseRateLimiter` placed before `UseRouting`**
`[EnableRateLimiting]` and `[DisableRateLimiting]` attributes are stored in endpoint metadata — stamped there at startup by `MapControllers()`. If `UseRateLimiter` runs before `UseRouting`, `HttpContext.GetEndpoint()` returns `null`, the middleware cannot read the metadata, and per-endpoint policies are silently ignored. Place `UseRateLimiter` after `UseRouting`.

**Queue fills and all requests start returning 429**
`QueueLimit` is the number of requests that wait beyond `PermitLimit` before being rejected. Under sustained overload, the queue fills and every new request gets a 429 immediately — including requests that would have been processed quickly. Set `QueueLimit = 0` for APIs where queuing adds latency the client cannot tolerate; use a small positive value where brief queuing is acceptable.
