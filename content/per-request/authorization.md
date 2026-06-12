## Authorization

Authorization answers one question: **is this caller allowed to do this?** It runs after authentication has already established who the caller is. It does not re-verify credentials — it reads `HttpContext.User` (populated by `UseAuthentication`) and evaluates it against requirements attached to the matched endpoint.

The separation is deliberate. Authentication always runs and always lets the request continue. Authorization decides whether to block.

---

## What AuthorizationMiddleware does at request time

When a request reaches `UseAuthorization`, the middleware does the following:

**Step 1 — Read the endpoint from HttpContext**

```csharp
var endpoint = context.GetEndpoint();
```

`GetEndpoint()` reads the `Endpoint` object stored on `HttpContext.Features` under `IEndpointFeature` — the same object written there by `UseRouting` calling `HttpContext.SetEndpoint(endpoint)` earlier in the pipeline. This is why `UseAuthorization` must come after `UseRouting`. If routing has not run, `HttpContext.Features` has no `IEndpointFeature` entry, `GetEndpoint()` returns `null`, and the metadata collections in Step 3 fall back to empty — `CombineAsync` returns `null`, the `if (policy == null)` branch fires, `_next(context)` is called, and the request continues to the action without any authorization check. Every `[Authorize]` route becomes publicly accessible. No exception is thrown. This is covered in full in [ordering-rules.md] and [the-gap.md].

**Step 2 — Check for IAllowAnonymous**

Before reading any policy, the middleware checks the endpoint metadata for `IAllowAnonymous`:

```csharp
if (endpoint?.Metadata.GetMetadata<IAllowAnonymous>() != null)
{
    await _next(context);  // skip authorization entirely — call next middleware in the chain
    return;
}
```

`[AllowAnonymous]` implements `IAllowAnonymous`. If `IAllowAnonymous` is present in the `EndpointMetadataCollection` — whether on the action itself or inherited from the controller — `AuthorizationMiddleware` calls `_next(context)` immediately and returns, passing the request to the next middleware without evaluating any policy. This happens regardless of any `[Authorize]` also present in the same metadata. Both attributes are objects in the same `EndpointMetadataCollection`; `IAllowAnonymous` is checked first and wins unconditionally.

**Step 3 — Collect policy requirements from metadata**

```csharp
var authorizeData = endpoint?.Metadata.GetOrderedMetadata<IAuthorizeData>()
                    ?? Array.Empty<IAuthorizeData>();

var policies = endpoint?.Metadata.GetOrderedMetadata<AuthorizationPolicy>()
               ?? Array.Empty<AuthorizationPolicy>();

var policy = await AuthorizationPolicy.CombineAsync(_policyProvider, authorizeData, policies);
```

`[Authorize]` implements `IAuthorizeData`. `GetOrderedMetadata<IAuthorizeData>()` returns all `[Authorize]` attribute instances stamped onto the endpoint at startup — from the action, from the controller, and from any conventions applied at registration (e.g. `.RequireAuthorization()`). `CombineAsync` merges them into a single `AuthorizationPolicy`.

If no policy is found — no `[Authorize]` on the endpoint and no `FallbackPolicy` configured — `CombineAsync` returns `null`, the middleware calls `_next`, and the request passes through unchecked.

**Step 4 — Evaluate the policy**

```csharp
var result = await _authorizationService.AuthorizeAsync(context.User, resource, policy);
```

`IAuthorizationService` evaluates `HttpContext.User` against every requirement in the combined policy. Each requirement is evaluated by a registered `IAuthorizationHandler`. All requirements must pass for the policy to succeed.

**Step 5 — Respond to the result**

- **Success** — the middleware calls `_next(context)`. The request continues to the action.
- **Failure** — the middleware calls either `ChallengeAsync` or `ForbidAsync` on the authentication scheme.

The choice between Challenge and Forbid is based on whether the caller has an authenticated identity:

- `HttpContext.User.Identity?.IsAuthenticated == false` → **Challenge** — the caller is anonymous. The scheme decides the response: JWT bearer returns `401 Unauthorized` with `WWW-Authenticate: Bearer`. Cookie auth returns `302` redirect to the login page.
- `HttpContext.User.Identity?.IsAuthenticated == true` → **Forbid** — the caller is authenticated but does not meet the requirements. Returns `403 Forbidden`.

This is the precise source of the 401 vs 403 distinction. Authorization middleware does not return these status codes directly — it delegates to the scheme via `ChallengeAsync` or `ForbidAsync`. The status code is the scheme's decision.

---

## The three ways to apply authorization

### 1. Attribute-based — per action or controller

```csharp
[Authorize]                           // any authenticated user
[Authorize(Roles = "Admin")]          // must have Admin role claim
[Authorize(Policy = "CanEditUsers")]  // must satisfy named policy
[AllowAnonymous]                      // skip authorization for this endpoint
```

Multiple `[Authorize]` attributes on the same action are combined — all must be satisfied:

```csharp
[Authorize(Roles = "Editor")]
[Authorize(Policy = "MustHaveVerifiedEmail")]
public ActionResult<PostDto> UpdatePost(int id, [FromBody] UpdatePostRequest body) { … }
// caller must be in the Editor role AND satisfy MustHaveVerifiedEmail policy
```

### 2. Convention-based — at registration

Applied to all endpoints registered by a `Map…()` call, without touching the controllers:

```csharp
app.MapControllers().RequireAuthorization();               // all endpoints require auth
app.MapControllers().RequireAuthorization("AdminOnly");    // specific named policy
```

This stamps an `AuthorizeAttribute` instance onto every endpoint's metadata — identical to placing `[Authorize]` on every action. Actions can still opt out with `[AllowAnonymous]`.

### 3. FallbackPolicy — catch-all for undecorated endpoints

A `FallbackPolicy` applies to any endpoint that has no authorization metadata at all — no `[Authorize]`, no `.RequireAuthorization()`. It does not affect endpoints that already have metadata.

```csharp
// Program.cs — before builder.Build():
builder.Services.AddAuthorizationBuilder()
    .SetFallbackPolicy(new AuthorizationPolicyBuilder()
        .RequireAuthenticatedUser()
        .Build());
```

With a `FallbackPolicy` set, every endpoint in the app requires authentication unless it explicitly opts out with `[AllowAnonymous]`. This is a "secure by default" pattern — new endpoints are protected automatically without requiring developers to remember to add `[Authorize]`.

Without a `FallbackPolicy` (the default), endpoints with no authorization metadata are publicly accessible.

---

## Policy-based authorization

Role checks (`[Authorize(Roles = "Admin")]`) are a shortcut. For anything more complex, use a named policy.

### Defining a policy

```csharp
// Program.cs — before builder.Build():
builder.Services.AddAuthorizationBuilder()
    .AddPolicy("CanEditUsers", policy =>
        policy
            .RequireAuthenticatedUser()         // must be authenticated
            .RequireRole("Admin", "Editor")     // must have Admin or Editor role
            .RequireClaim("email_verified", "true")  // must have this specific claim
    );
```

`RequireRole` passes if the user has **any** of the listed roles. Multiple `Require…` calls are AND'd — all must pass.

### Using a policy

```csharp
[Authorize(Policy = "CanEditUsers")]
public async Task<ActionResult<UserDto>> UpdateUser(int id, [FromBody] UpdateUserRequest body) { … }
```

---

## IAuthorizationHandler — custom requirements

When built-in checks are not enough, implement a custom requirement and handler.

A **requirement** is a data class — it describes what is needed:

```csharp
public class MinimumAgeRequirement : IAuthorizationRequirement
{
    public int MinimumAge { get; }
    public MinimumAgeRequirement(int minimumAge) => MinimumAge = minimumAge;
}
```

A **handler** evaluates the requirement against the current user:

```csharp
public class MinimumAgeHandler : AuthorizationHandler<MinimumAgeRequirement>
{
    protected override Task HandleRequirementAsync(
        AuthorizationHandlerContext context,
        MinimumAgeRequirement requirement)
    {
        var ageClaim = context.User.FindFirst("age");

        if (ageClaim != null && int.TryParse(ageClaim.Value, out var age) && age >= requirement.MinimumAge)
            context.Succeed(requirement);  // requirement met — does not short-circuit; other requirements still evaluated

        // if not calling Succeed, the requirement fails
        // calling context.Fail() explicitly fails the policy even if other handlers Succeed
        return Task.CompletedTask;
    }
}
```

Register both and use in a policy:

```csharp
// Program.cs:
builder.Services.AddSingleton<IAuthorizationHandler, MinimumAgeHandler>();

builder.Services.AddAuthorizationBuilder()
    .AddPolicy("Over18", policy =>
        policy
            .RequireAuthenticatedUser()
            .AddRequirements(new MinimumAgeRequirement(18))
    );
```

```csharp
[Authorize(Policy = "Over18")]
public ActionResult<RestrictedContentDto> GetRestrictedContent() { … }
```

A single requirement can have multiple handlers registered — the requirement succeeds if **any** handler calls `Succeed`. This lets you implement OR logic: "the caller satisfies this requirement if they are an Admin OR if they own the resource."

---

## Resource-based authorization

The approaches above evaluate the policy without knowing which specific resource is being accessed. Resource-based authorization passes the resource to the handler so requirements can be checked against it — for example, "this user can only edit posts they created."

Resource-based authorization is invoked manually inside the action, not automatically by the middleware:

```csharp
public class PostEditRequirement : IAuthorizationRequirement { }

public class PostAuthorizationHandler : AuthorizationHandler<PostEditRequirement, Post>
{
    protected override Task HandleRequirementAsync(
        AuthorizationHandlerContext context,
        PostEditRequirement requirement,
        Post resource)  // the specific post being accessed
    {
        var userId = context.User.FindFirstValue(ClaimTypes.NameIdentifier);

        if (resource.AuthorId == userId || context.User.IsInRole("Admin"))
            context.Succeed(requirement);

        return Task.CompletedTask;
    }
}
```

In the action, fetch the resource first, then authorize against it:

```csharp
[HttpPut("{id}")]
[Authorize]  // still require authentication at the middleware level
public async Task<ActionResult<PostDto>> UpdatePost(int id, [FromBody] UpdatePostRequest body)
{
    var post = await _posts.GetByIdAsync(id);
    if (post is null) return NotFound();

    // authorize against the specific post:
    var result = await _authorizationService.AuthorizeAsync(User, post, new PostEditRequirement());
    if (!result.Succeeded) return Forbid();  // authenticated but not the author or Admin

    var updated = await _posts.UpdateAsync(id, body);
    return Ok(updated);
}
```

Note: `return Forbid()` here calls `ForbidAsync` on the scheme directly — the same result as the middleware's Forbid path. `return Unauthorized()` would return a raw 401 without going through the scheme. Prefer `Forbid()` for authorization failures and `Unauthorized()` only when you are certain the caller has no identity.

Register the handler:

```csharp
builder.Services.AddScoped<IAuthorizationHandler, PostAuthorizationHandler>();
```

---

## What breaks and why

**`UseAuthorization` placed before `UseRouting` in a Startup.Configure app**
`GetEndpoint()` returns `null`. Both metadata collections fall back to empty. `CombineAsync` returns `null`. The middleware passes through. Every `[Authorize]` route is publicly accessible. No exception is thrown. The runtime guard does not catch this — it only detects omission of `UseAuthorization`, not misplacement. Covered in detail in [ordering-rules.md].

**`FallbackPolicy` set but endpoint has `[AllowAnonymous]`**
`IAllowAnonymous` is checked before the `FallbackPolicy` is applied. The endpoint is anonymous. This is the intended behaviour — `[AllowAnonymous]` is the explicit opt-out.

**Multiple `[Authorize]` attributes — developer expects OR, gets AND**
Each `[Authorize]` attribute is a separate `IAuthorizeData` entry in the metadata. `CombineAsync` ANDs them. There is no built-in OR across separate `[Authorize]` attributes. For OR logic, use a single named policy with an `IAuthorizationHandler` that has multiple handlers registered for one requirement.

**`context.Fail()` called in one handler overrides `Succeed()` in another**
`context.Fail()` marks the policy as failed regardless of other handlers. Use it when you want to enforce an explicit deny — for example, if a user is on a blocklist. Do not call it when merely declining to `Succeed` — just return without calling either.

**`return Unauthorized()` vs `return Forbid()` from an action**
`Unauthorized()` returns a raw `401` — it does not go through the authentication scheme and does not set `WWW-Authenticate`. `Forbid()` calls `ForbidAsync` on the scheme, which produces the scheme-appropriate response. Use `Forbid()` for authorization failures on authenticated users. Use `Unauthorized()` only when you need a raw 401 and understand why.
