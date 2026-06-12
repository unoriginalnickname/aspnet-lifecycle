## AddHttpClient — IHttpClientFactory

Registers `IHttpClientFactory`, the correct way to create `HttpClient` instances in ASP.NET Core. You never instantiate `HttpClient` directly with `new HttpClient()` in application code — the factory manages pooling, DNS refresh, and logging for you.

```csharp
builder.Services.AddHttpClient();
```

### Why not new HttpClient()

Two problems with instantiating `HttpClient` directly:

**Socket exhaustion** — `HttpClient` implements `IDisposable`, so developers typically wrap it in `using` blocks. But disposing `HttpClient` does not release the underlying socket immediately — the socket stays in `TIME_WAIT` for up to 240 seconds. Under load, sockets are exhausted and new connections fail. The factory pools the underlying `HttpMessageHandler` instances, keeping sockets alive and reusing them across requests.

**DNS staleness** — long-lived `HttpClient` instances cache DNS lookups. If a service's IP address changes, the cached client keeps sending to the old IP. The factory enforces a handler lifetime (default: 2 minutes), rotating handlers on a schedule so DNS is re-resolved regularly.

### Three registration patterns

**Basic — resolve via IHttpClientFactory directly:**

```csharp
// Startup:
builder.Services.AddHttpClient();

// In a controller or service:
public class MyService
{
    private readonly IHttpClientFactory _factory;
    public MyService(IHttpClientFactory factory) => _factory = factory;

    public async Task<string> GetDataAsync()
    {
        var client = _factory.CreateClient();  // gets a fresh client backed by a pooled handler
        var response = await client.GetAsync("https://api.example.com/data");
        return await response.Content.ReadAsStringAsync();
    }
}
```

**Named — pre-configured client retrieved by name:**

```csharp
// Startup:
builder.Services.AddHttpClient("payments", client =>
{
    client.BaseAddress = new Uri("https://api.payments.com/");
    client.DefaultRequestHeaders.Add("X-Api-Version", "2");
    client.Timeout = TimeSpan.FromSeconds(10);
});

// Usage:
var client = _factory.CreateClient("payments");
var response = await client.GetAsync("charges");  // resolves to https://api.payments.com/charges
```

**Typed — a wrapper class that owns the HttpClient:**

```csharp
// The typed client:
public class PaymentsClient
{
    private readonly HttpClient _http;
    public PaymentsClient(HttpClient http) => _http = http;

    public async Task<ChargeResult> ChargeAsync(decimal amount)
    {
        var response = await _http.PostAsJsonAsync("charges", new { amount });
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<ChargeResult>();
    }
}

// Startup:
builder.Services.AddHttpClient<PaymentsClient>(client =>
{
    client.BaseAddress = new Uri("https://api.payments.com/");
});

// Usage — injected directly:
public class OrdersController : ControllerBase
{
    private readonly PaymentsClient _payments;
    public OrdersController(PaymentsClient payments) => _payments = payments;
}
```

Typed clients are registered as Transient by the factory. A new instance is created each time one is resolved, but the underlying `HttpMessageHandler` is pooled and reused.

### Lifetime trap — typed clients in Singletons

Typed clients are Transient — a new instance per resolution. But `HttpClient` itself captures the `HttpMessageHandler` at creation time. If a typed client is injected into a Singleton, it is captured for the app's lifetime, defeating handler rotation and causing DNS staleness. This is the same captive dependency problem as Scoped-in-Singleton.

```csharp
// WRONG — typed client captured in Singleton, handler never rotates:
builder.Services.AddSingleton<MySingletonService>();  // injects PaymentsClient → captured forever

// Correct — inject IHttpClientFactory into the Singleton and create clients on demand:
public class MySingletonService
{
    private readonly IHttpClientFactory _factory;
    public MySingletonService(IHttpClientFactory factory) => _factory = factory;

    public async Task DoWorkAsync()
    {
        var client = _factory.CreateClient("payments");  // new client per call — handler pooled
        // ...
    }
}
```

### Delegating handlers — outgoing middleware

`HttpClient` supports delegating handlers — a pipeline for outgoing requests, analogous to the inbound middleware pipeline. Use them for cross-cutting concerns on outbound HTTP calls: logging, retry, adding auth headers.

```csharp
public class AuthHeaderHandler : DelegatingHandler
{
    private readonly ITokenService _tokens;
    public AuthHeaderHandler(ITokenService tokens) => _tokens = tokens;

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var token = await _tokens.GetTokenAsync();
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return await base.SendAsync(request, cancellationToken);  // call next handler
    }
}

// Register:
builder.Services.AddTransient<AuthHeaderHandler>();
builder.Services.AddHttpClient("internal")
    .AddHttpMessageHandler<AuthHeaderHandler>();
```

Handlers are chained in registration order. Each handler calls `base.SendAsync` to pass the request to the next handler; the final handler sends the actual network request.
