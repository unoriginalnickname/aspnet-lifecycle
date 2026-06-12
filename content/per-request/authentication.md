## Authentication

Authentication answers one question: **who is making this request?** It does not decide whether they are allowed in — that is authorization's job. The separation is deliberate. Authentication runs first, establishes identity, and always lets the request continue. Authorization runs after and decides whether to block.

`UseAuthentication()` registers the verification middleware at startup. At request time it reads the credentials from the request, verifies them, and if valid, builds a `ClaimsPrincipal` — the object representing the caller's identity — and stores it in `HttpContext.User`. Every downstream layer reads from `HttpContext.User`.

If credentials are missing, invalid, or expired, `HttpContext.User` is left as an anonymous `ClaimsPrincipal` — `IsAuthenticated` is `false` and no identity claims are present. The request continues through the pipeline without being blocked.

When the request reaches authorization: if the matched endpoint has an `[Authorize]` requirement and the policy evaluation fails — because the user is anonymous — authorization calls `ChallengeAsync()` on the registered authentication scheme. The scheme decides what to return:

- **JWT bearer** → `401 Unauthorized` with a `WWW-Authenticate: Bearer` header
- **Cookie authentication** → `302` redirect to the login page

This distinction matters: `401` is not something authorization returns directly. It is the JWT bearer scheme's response to being challenged. A different scheme produces a different response to the same situation. Everything in this file covers JWT bearer authentication — the scheme used by APIs.

---

## What a JWT is

A JWT (JSON Web Token) is a credential your auth server gives to a client after a successful login. It is a string of three base64-encoded sections separated by dots:

```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyXzEyMyIsImVtYWlsIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiQWRtaW4iLCJpYXQiOjE3MTc5NjQ4MDAsImV4cCI6MTcxNzk2ODQwMCwiYXVkIjoieW91ci1hcGkiLCJpc3MiOiJodHRwczovL2F1dGgubXlhcHAuY29tIn0.SIGNATURE
```

Decoded, the three parts are:

**Header** — describes the token itself:
```json
{
  "alg": "RS256",   // signing algorithm — RS256 means RSA with SHA-256
  "typ": "JWT"
}
```

**Payload** — the claims, key-value pairs carrying the user's information:
```json
{
  "sub":   "user_123",                    // subject — the user's unique identifier
  "email": "alice@example.com",
  "role":  "Admin",
  "iat":   1717964800,                    // issued at — Unix timestamp
  "exp":   1717968400,                    // expires at — Unix timestamp (1 hour later)
  "aud":   "your-api",                    // audience — which API this token is for
  "iss":   "https://auth.myapp.com"       // issuer — which auth server created it
}
```

**Signature** — a cryptographic hash of the header and payload, created using the auth server's private key. The signature is what makes the token tamper-proof. If anyone changes a single character of the payload, the signature no longer matches and verification fails.

The client stores this token and sends it with every API request in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ...
```

---

## What verification does at request time

When a request arrives with a `Bearer` token, `UseAuthentication` runs the following steps:

### Step 1 — Read the token

Reads the `Authorization: Bearer <token>` header. If the header is absent, or does not start with `Bearer `, authentication stops here — `HttpContext.User` stays anonymous. The request continues to authorization.

### Step 2 — Decode the token

Base64-decodes the header and payload. No key needed for this step — base64 encoding is not encryption, just encoding. Anyone can decode a JWT and read the claims. The signature is what prevents tampering.

### Step 3 — Fetch the signing keys (JWKS)

To verify the signature, the middleware needs the auth server's public key. The auth server publishes its public keys at a standard URL called the JWKS endpoint (JSON Web Key Set).

The middleware discovers this URL automatically using OpenID Connect discovery:

```
GET https://auth.myapp.com/.well-known/openid-configuration
```

This returns a JSON document containing, among other things, the `jwks_uri`:

```json
{
  "issuer": "https://auth.myapp.com",
  "jwks_uri": "https://auth.myapp.com/.well-known/jwks.json",
  ...
}
```

The middleware then fetches the keys from `jwks_uri`:

```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "key-2024-06",   // key ID — matches the "kid" in the token header
      "n":   "...",           // RSA modulus — the public key material
      "e":   "AQAB"
    }
  ]
}
```

**Key caching** — the keys are fetched once and cached. They are not fetched on every request. The cache is automatically refreshed when a token arrives with a `kid` (key ID) that is not in the cache — this handles key rotation without downtime.

**Key rotation** — auth servers periodically replace their signing keys. The old key is kept in the JWKS endpoint for the lifetime of any tokens it signed (`exp` claim). When the cache sees an unknown `kid`, it re-fetches the JWKS and updates the cache. Tokens signed with the old key continue to work until they expire naturally.

This is configured in startup with the `Authority`:

```csharp
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o => {
        o.Authority = "https://auth.myapp.com";  // used to discover jwks_uri automatically
        o.Audience  = "your-api";
    });
```

### Step 4 — Verify the signature

Using the fetched public key, the middleware recomputes the expected signature from the header and payload, then compares it to the signature in the token. If they do not match — because the token was tampered with, or signed by a different key — verification fails. `HttpContext.User` stays anonymous.

### Step 5 — Validate the claims

Even a correctly signed token is rejected if:

- **`exp` (expiry) is in the past** — the token has expired. `HttpContext.User` stays anonymous.
- **`aud` (audience) does not match** — the token was issued for a different API. `HttpContext.User` stays anonymous. This prevents a token issued for `billing-api` from being used against `users-api`.
- **`iss` (issuer) does not match** — the token was issued by a different auth server than the one configured in `Authority`. `HttpContext.User` stays anonymous.

### Step 6 — Build ClaimsPrincipal and populate HttpContext.User

If all checks pass, the middleware extracts the claims from the payload and builds a `ClaimsPrincipal` — a collection of `Claim` objects, one per key-value pair in the payload:

```
sub   → user_123
email → alice@example.com
role  → Admin
```

This `ClaimsPrincipal` is stored in `HttpContext.User`. Every downstream layer — authorization, your controller, your services — reads the caller's identity from there.

---

## HttpContext.User — reading the identity in code

`HttpContext.User` is a `ClaimsPrincipal`. Its most commonly used members:

```csharp
// Is there an authenticated identity at all?
bool isAuthenticated = User.Identity?.IsAuthenticated ?? false;
// true if the token was valid; false if missing, invalid, or expired

// The user's unique identifier — maps to the "sub" claim:
string? userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
// or equivalently:
string? userId = User.FindFirstValue("sub");

// Email:
string? email = User.FindFirstValue(ClaimTypes.Email);

// Role check:
bool isAdmin = User.IsInRole("Admin");
// or:
bool isAdmin = User.HasClaim(ClaimTypes.Role, "Admin");

// All claims — useful for debugging:
foreach (var claim in User.Claims)
    Console.WriteLine($"{claim.Type}: {claim.Value}");
```

`User.Identity.Name` maps to the `name` claim if present, or falls back to `sub`. Prefer `FindFirstValue(ClaimTypes.NameIdentifier)` for the user ID — `ClaimTypes.NameIdentifier` maps to the `sub` claim, which is the subject identifier by JWT spec. Returns `null` if the token contains no `sub` claim.

### Reading from a controller

```csharp
[ApiController]
[Route("api/[controller]")]
[Authorize]
public class UsersController : ControllerBase
{
    [HttpGet("me")]
    public ActionResult<UserProfileDto> GetMyProfile()
    {
        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);
        var email  = User.FindFirstValue(ClaimTypes.Email);
        var role   = User.FindFirstValue(ClaimTypes.Role);

        return Ok(new UserProfileDto
        {
            Id    = userId,
            Email = email,
            Role  = role
        });
    }
}
```

### Reading from a service

Inject `IHttpContextAccessor` to read `HttpContext.User` from outside a controller:

```csharp
// Program.cs:
builder.Services.AddHttpContextAccessor();

// UserService.cs:
public class UserService
{
    private readonly IHttpContextAccessor _http;

    public UserService(IHttpContextAccessor http) => _http = http;

    public string? GetCurrentUserId()
        => _http.HttpContext?.User.FindFirstValue(ClaimTypes.NameIdentifier);
}
```

`IHttpContextAccessor` is Scoped — it gives you access to the current request's `HttpContext` from anywhere in the DI tree without passing it explicitly.

---

## Multiple authentication schemes

An app can register more than one authentication scheme — for example, JWT for the API and a second scheme for webhooks using an API key. Each scheme has a name and its own verification logic.

```csharp
builder.Services.AddAuthentication()
    .AddJwtBearer("Bearer", o => {
        o.Authority = "https://auth.myapp.com";
        o.Audience  = "your-api";
    })
    .AddJwtBearer("ApiKey", o => {
        // different issuer, different audience — e.g. machine-to-machine tokens
        o.Authority = "https://auth.myapp.com";
        o.Audience  = "your-api-internal";
    });
```

A specific endpoint can require a specific scheme:

```csharp
[Authorize(AuthenticationSchemes = "ApiKey")]
public ActionResult<WebhookResult> HandleWebhook([FromBody] WebhookPayload payload) { … }
```

Without a scheme specified on the endpoint, the default scheme is used — whichever was passed to `AddAuthentication()` as the first argument.

---

## What breaks and why

**Expired token (`exp` is in the past)**
Verification fails at step 5. `HttpContext.User` stays anonymous (`IsAuthenticated == false`). The request reaches authorization, which evaluates the `[Authorize]` policy, finds it unsatisfied, and calls `ChallengeAsync()` on the JWT bearer scheme — returning `401 Unauthorized`. The client must request a new token. This is expected behaviour — tokens are short-lived by design. The `exp` claim limits exposure if a token is stolen, since it stops working automatically after expiry regardless of whether the theft was detected. The client should use a refresh token to get a new access token without prompting the user to log in again.

**Wrong audience (`aud` does not match)**
Verification fails silently. `HttpContext.User` stays anonymous. From the client's perspective this looks identical to an expired token — `401 Unauthorized`. No information about why is returned to the caller. Check your `Audience` configuration in startup if tokens are being rejected despite being valid.

**JWKS endpoint unreachable**
If the auth server's JWKS endpoint is down and the keys are not in cache, the middleware cannot verify any token. Every authenticated request returns `401 Unauthorized`. The keys are cached — a brief outage of the auth server does not immediately break your API. A prolonged outage will eventually cause cache entries to expire and all verification to fail.

**Token sent without `Bearer` prefix**
```
Authorization: eyJhbG...   // WRONG: — not recognised
Authorization: bearer eyJhbG...  // WRONG: — case-sensitive, must be "Bearer"
Authorization: Bearer eyJhbG...  // Correct:
```
The middleware only reads the header if it starts with exactly `Bearer ` (capital B, space after). Anything else is treated as a missing token.

**`sub` claim missing from token**
The token verifies successfully but `User.FindFirstValue(ClaimTypes.NameIdentifier)` returns null. This happens when the auth server does not include a subject claim, or uses a non-standard claim name. Verify the token payload with a tool like jwt.io to see exactly what claims are present.

**Clock skew**
JWT expiry is compared against the server's clock. If the server's clock is out of sync with the auth server's clock by more than a few seconds, valid tokens may be rejected as expired before they should be. ASP.NET Core's JWT bearer middleware allows a configurable clock skew (default: 5 minutes) to accommodate this:

```csharp
.AddJwtBearer(o => {
    o.Authority    = "https://auth.myapp.com";
    o.Audience     = "your-api";
    o.TokenValidationParameters = new TokenValidationParameters
    {
        ClockSkew = TimeSpan.FromSeconds(30)  // allow 30 seconds of clock drift
    };
});
```

---

## Reading the token from a non-standard location

Step 1 of the verification process reads the token from `Authorization: Bearer <token>`. This is the correct location for REST API requests. It is not available for WebSocket connections or SignalR hubs — the browser's WebSocket API does not allow setting custom headers, so the token must be sent another way, typically as a query string parameter.

The `MessageReceived` event on `JwtBearerOptions` runs at the very start of step 1, before the middleware attempts to read the `Authorization` header. Setting `context.Token` inside the event handler tells the middleware to use that value instead of reading the header — steps 2 through 6 proceed identically from there.

```csharp
// startup — add-authentication.md shows where this goes in AddJwtBearer:
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o =>
    {
        o.Authority = "https://auth.myapp.com";
        o.Audience  = "your-api";

        o.Events = new JwtBearerEvents
        {
            OnMessageReceived = context =>
            {
                // SignalR and WebSockets send the token as ?access_token=<token>
                // because the browser WebSocket API cannot set custom headers.
                var token = context.Request.Query["access_token"];

                // Only apply this to SignalR hub paths — not to the whole API.
                // Applying it globally would allow any endpoint to accept tokens
                // via query string, which is less secure than the Authorization header
                // (query strings appear in server logs, browser history, and referrer headers).
                var path = context.HttpContext.Request.Path;
                if (!string.IsNullOrEmpty(token) && path.StartsWithSegments("/hubs"))
                {
                    context.Token = token;  // use this value — skip header read
                }

                return Task.CompletedTask;
            }
        };
    });
```

**Why query string tokens are less secure than the Authorization header:** query strings appear in web server access logs, browser history, and `Referer` headers sent to third-party resources on the page. A token in `Authorization: Bearer` is in the request headers, which are not logged by default and are not forwarded in `Referer`. Restrict query string token acceptance to the specific paths that need it — do not apply it globally.

**Other `JwtBearerEvents`:** `OnTokenValidated` fires after a token passes all verification steps — use it to add extra claims or reject tokens based on your own database. `OnAuthenticationFailed` fires when verification fails — use it to log failure details that the standard middleware log does not include (e.g. which specific claim failed). `OnChallenge` fires when the middleware is about to return `401` — use it to customise the challenge response.

```csharp
// These events are configured inside AddJwtBearer alongside OnMessageReceived:
o.Events = new JwtBearerEvents
{
    OnTokenValidated = async context =>
    {
        // token passed all checks — enrich with database claims:
        var db = context.HttpContext.RequestServices.GetRequiredService<IUserRepository>();
        var userId = context.Principal!.FindFirstValue(ClaimTypes.NameIdentifier);
        var tenantId = await db.GetTenantIdAsync(userId!);

        // Clone the identity before adding claims — never mutate the original:
        var identity = new ClaimsIdentity(context.Principal!.Identity);
        identity.AddClaim(new Claim("tenantId", tenantId));
        context.Principal = new ClaimsPrincipal(identity);
    },

    OnAuthenticationFailed = context =>
    {
        // log the specific failure reason — the standard middleware log omits it.
        // ILoggerFactory is available from the DI container:
        var logger = context.HttpContext.RequestServices
            .GetRequiredService<ILoggerFactory>()
            .CreateLogger("JwtBearer");
        logger.LogWarning("JWT authentication failed: {Error}", context.Exception.Message);
        return Task.CompletedTask;
    }
};
```

---

## IClaimsTransformation — enriching the identity after verification

`IClaimsTransformation` is an interface that runs after a token has been successfully verified and a `ClaimsPrincipal` has been built, but before that principal is stored in `HttpContext.User`. It lets you add, remove, or modify claims using information that is not in the token — typically from your own database.

```csharp
public interface IClaimsTransformation
{
    Task<ClaimsPrincipal> TransformAsync(ClaimsPrincipal principal);
}
```

The typical use case is a token that contains a user ID but not a tenant ID, role list, or other application-specific data that lives in your database. Rather than requiring the auth server to include this data in every token, you fetch it in the transformation and add it as claims — available to authorization policies and your controller code via `HttpContext.User`.

```csharp
public class TenantClaimsTransformation : IClaimsTransformation
{
    private readonly ITenantRepository _tenants;

    public TenantClaimsTransformation(ITenantRepository tenants)
        => _tenants = tenants;

    public async Task<ClaimsPrincipal> TransformAsync(ClaimsPrincipal principal)
    {
        // Only transform authenticated principals — anonymous requests pass through unchanged.
        if (principal.Identity?.IsAuthenticated != true)
            return principal;

        // Avoid adding claims that are already present — TransformAsync can be called
        // more than once per request (see below). Adding duplicates corrupts policy evaluation.
        if (principal.HasClaim(c => c.Type == "tenantId"))
            return principal;

        var userId   = principal.FindFirstValue(ClaimTypes.NameIdentifier);
        var tenantId = await _tenants.GetTenantIdForUserAsync(userId!);

        // Clone the principal before modifying — never mutate the original.
        var identity = new ClaimsIdentity(principal.Identity);
        identity.AddClaim(new Claim("tenantId", tenantId));

        return new ClaimsPrincipal(identity);
    }
}
```

Register in startup — before `builder.Build()`:

```csharp
builder.Services.AddTransient<IClaimsTransformation, TenantClaimsTransformation>();
```

**`IClaimsTransformation` vs `OnTokenValidated`**

`OnTokenValidated` (covered in the previous section) is a JWT bearer event — it fires only for JWT bearer authentication, only when a token is present and valid. `IClaimsTransformation` fires for every authentication scheme and runs whenever `AuthenticateAsync` is called, regardless of scheme.

Use `OnTokenValidated` when the transformation is specific to JWT bearer. Use `IClaimsTransformation` when the transformation should apply to all schemes — for example, in an app that accepts both JWTs and cookie authentication and needs the same tenant claims added for both.

**`TransformAsync` can be called more than once per request**

`IAuthenticationService.AuthenticateAsync` is called by `UseAuthentication` at middleware time, and can also be called again by authorization, by `[Authorize(AuthenticationSchemes = "...")]` on specific endpoints, or by explicit code that calls `HttpContext.AuthenticateAsync()`. Each call invokes `TransformAsync` again on the same principal. Without the `HasClaim` guard shown above, claims are added repeatedly — a role claim present three times causes `User.IsInRole("Admin")` to still return `true`, but policy evaluators that count claims or check uniqueness can behave unexpectedly. Always check for existing claims before adding.

**Clone before mutating**

`TransformAsync` receives the existing `ClaimsPrincipal`. Mutating it directly modifies the shared instance — if `AuthenticateAsync` is called again later in the same request, the already-modified principal arrives again. The pattern above creates a new `ClaimsIdentity` from the existing identity, adds claims to the new identity, and wraps it in a new `ClaimsPrincipal`. The original is not touched.

**Registration lifetime**

`IClaimsTransformation` is typically registered as `Transient` because it is constructed per call. If your transformer injects a Scoped service (e.g. a repository backed by `DbContext`), register it as `Scoped` instead — registering as `Singleton` would capture the Scoped dependency for the app lifetime (the captive dependency trap covered in service-lifetimes.md).

---

## Brief notes on what is not covered here

**Cookie authentication** — works the same way but reads a session cookie instead of a JWT header. Used in server-rendered web apps (Razor Pages, MVC with views) rather than APIs. Covered in full in the Razor Pages overview.
