## AddAuthentication

Registers the authentication system. At request time, `UseAuthentication()` in the pipeline reads the incoming credentials, verifies them using the settings registered here, and populates `HttpContext.User` with the caller's identity.

**JWT bearer — the most common setup for APIs:**

```csharp
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o => {
        o.Authority = "https://your-auth-server/";
        o.Audience  = "your-api";
    });
```

- **Authority** — the URL of the auth server that issued the token. The middleware fetches the public signing keys from `{Authority}/.well-known/openid-configuration` automatically and caches them. Tokens must have a matching `iss` (issuer) claim.
- **Audience** — a string identifying your API. The token must contain a matching `aud` claim or verification fails and the request continues with `HttpContext.User` as anonymous.

**Manual token validation (without an auth server):**

```csharp
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o => {
        o.TokenValidationParameters = new TokenValidationParameters {
            ValidateIssuer           = true,
            ValidIssuer              = "https://myapp.com",
            ValidateAudience         = true,
            ValidAudience            = "my-api",
            ValidateLifetime         = true,
            ValidateIssuerSigningKey = true,
            IssuerSigningKey         = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Secret"]))
        };
    });
```

**What `UseAuthentication` does at request time:**

1. Reads `Authorization: Bearer <token>` from the request header
2. Decodes the JWT — three base64-encoded parts: header (algorithm), payload (claims), signature
3. Verifies the signature using the signing keys fetched from the auth server
4. Checks the expiry (`exp` claim) — expired tokens are rejected
5. Extracts the claims from the payload — key/value pairs like `sub` (user ID), `email`, `role`, `name`
6. Builds a `ClaimsPrincipal` and assigns it to `HttpContext.User`

If any step fails, `HttpContext.User` is left as an anonymous principal with no claims. The request continues — blocking is `UseAuthorization`'s job.

**Reading claims in your action:**

```csharp
var userId = User.FindFirstValue(ClaimTypes.NameIdentifier); // "sub" claim
var email  = User.FindFirstValue(ClaimTypes.Email);
var roles  = User.FindAll(ClaimTypes.Role).Select(c => c.Value).ToList();

// shorthand check:
if (!User.IsInRole("Admin")) return Forbid();
```

**Multiple authentication schemes:**

If your API accepts both JWTs and API keys:

```csharp
builder.Services.AddAuthentication()
    .AddJwtBearer("Bearer", o => { o.Authority = "..."; })
    .AddScheme<ApiKeyAuthenticationOptions, ApiKeyAuthenticationHandler>("ApiKey", o => { });
```

Actions can then specify which schemes to accept:

```csharp
[Authorize(AuthenticationSchemes = "Bearer,ApiKey")]
public IActionResult SecureEndpoint() { … }
```
