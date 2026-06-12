## Ordering rules

`Use…()` calls register middleware at fixed positions in a chain. The chain fires in registration order on every request. Wrong order produces silent failures at request time — not exceptions at startup, not warnings, nothing.

Three positions are critical:

### UseCors before UseAuthentication

Before a cross-domain POST/PUT/DELETE, the browser automatically sends a preflight OPTIONS request — no body, no credentials, no auth token — that asks "is this cross-domain request allowed?" If authentication runs first and challenges that preflight, the `Access-Control-Allow-Origin` header is never added. The browser reports a CORS error that hides what actually happened.

```csharp
// Correct:
app.UseCors("MyPolicy");     // handles preflight before auth can challenge it
app.UseAuthentication();

// WRONG:
app.UseAuthentication();     // challenges the preflight OPTIONS request
app.UseCors("MyPolicy");     // CORS headers never added → browser reports CORS error
```

### UseAuthentication before UseAuthorization

Authentication populates `HttpContext.User` with the caller's identity — the object that authorization evaluates. If authentication has not run, `HttpContext.User` is anonymous regardless of what credentials the request carries.

```csharp
// Correct:
app.UseAuthentication();     // verifies JWT, populates HttpContext.User
app.UseAuthorization();      // reads HttpContext.User — it's populated

// WRONG:
app.UseAuthorization();      // HttpContext.User is anonymous — JWT not yet verified
app.UseAuthentication();
```

### UseRouting before UseAuthorization

This is the most dangerous ordering mistake because it produces no error and is not detected by any runtime check when misplaced.

Routing writes the matched controller action onto `HttpContext` via `SetEndpoint()`. `EndpointMetadataCollection` — containing the `[Authorize]` attribute as an object — is attached to that endpoint. Authorization reads that metadata to know what policy to evaluate.

From the actual `AuthorizationMiddleware` source:

```csharp
var endpoint = context.GetEndpoint();

var authorizeData = endpoint?.Metadata.GetOrderedMetadata<IAuthorizeData>()
                    ?? Array.Empty<IAuthorizeData>();

var policies = endpoint?.Metadata.GetOrderedMetadata<AuthorizationPolicy>()
               ?? Array.Empty<AuthorizationPolicy>();

policy = await AuthorizationPolicy.CombineAsync(_policyProvider, authorizeData, policies);

if (policy == null)
{
    await _next(context);  // no policy → pass straight through
    return;
}
```

If routing has not run, `GetEndpoint()` returns `null`. Both `GetOrderedMetadata` calls fall back to `Array.Empty`. `CombineAsync` returns `null`. The `if (policy == null)` branch fires and calls `_next` — the request passes through authorization unchecked. Every `[Authorize]` route becomes publicly accessible.

```csharp
// Correct:
app.UseRouting();        // writes endpoint + metadata onto HttpContext
app.UseAuthorization();  // GetEndpoint() returns the match → metadata available

// WRONG — in Startup.Configure or explicit host builder:
app.UseAuthorization();  // GetEndpoint() returns null → auth silently skipped
app.UseRouting();
```

### [AllowAnonymous] overriding [Authorize]

When `[Authorize]` is on the controller and `[AllowAnonymous]` is on a specific action, both attributes end up in the same `EndpointMetadataCollection` at startup. `AuthorizationMiddleware` checks for `IAllowAnonymous` in the metadata before evaluating any policy. If found, it short-circuits immediately — authorization is skipped for that endpoint regardless of any `[Authorize]` also present.

```csharp
[Authorize]  // applies to all actions — stamped into every endpoint's metadata
public class UsersController : ControllerBase
{
    [HttpGet("{id}")]
    public Task<ActionResult<UserDto>> GetUser(int id) { … }  // requires auth

    [HttpGet("public-profile/{id}")]
    [AllowAnonymous]  // IAllowAnonymous wins — auth skipped for this endpoint only
    public Task<ActionResult<PublicProfileDto>> GetPublicProfile(int id) { … }
}
```

This works because both `[Authorize]` and `[AllowAnonymous]` are metadata objects on the endpoint, not runtime checks. The authorization middleware reads the metadata, finds `IAllowAnonymous`, and skips — regardless of the `[Authorize]` also present.

### The runtime guard — catches omission, not misplacement

`EndpointMiddleware` sets a key on `HttpContext.Items` after running. Before executing any endpoint with `[Authorize]` in its metadata, it checks for a separate key that `AuthorizationMiddleware` sets when it runs. If that key is absent, it throws:

> Endpoint UsersController.GetUser contains authorization metadata, but a middleware was not found that supports authorization.

This catches **omission** — `UseAuthorization()` not called at all.

It does **not** catch **misplacement**. If `UseAuthorization()` ran before `UseRouting()` in a `Startup.Configure` host, it still set its key — even though it evaluated nothing. The guard sees the key and is satisfied. The security hole is invisible.
