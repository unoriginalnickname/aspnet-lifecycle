## AddProblemDetails

Registers the RFC 7807 error formatter. `UseExceptionHandler()` in the pipeline needs this to produce a consistent, machine-readable error shape. Without it, unhandled exceptions return a blank 500 with no body.

```csharp
builder.Services.AddProblemDetails();
```

`AddProblemDetails()` must be called before `builder.Build()` — `AddProblemDetails()` registers the formatter in the DI container, and the container is frozen at `Build()`. Calling it after has no effect.

**The shape it produces:**

```json
{
  "type": "https://tools.ietf.org/html/rfc7231#section-6.6.1",
  "title": "An error occurred while processing your request.",
  "status": 500,
  "traceId": "00-abc123def456-00"
}
```

- `type` — a URI identifying the error category. Points to the relevant HTTP spec section by default.
- `title` — human-readable summary. Never contains internal detail.
- `status` — the HTTP status code.
- `traceId` — the distributed trace ID for this request. Logging providers can include the same traceId in log entries, allowing a request to be correlated with its logs. When a client reports an error, give them the `traceId` and search your logs — full stack trace, no exposure to the caller.

**Customising the shape:**

You can add extra fields or change the title without exposing internals:

```csharp
builder.Services.AddProblemDetails(o => {
    o.CustomizeProblemDetails = ctx => {
        ctx.ProblemDetails.Extensions["instance"] =
            $"{ctx.HttpContext.Request.Method} {ctx.HttpContext.Request.Path}";
    };
});
```

**Using `Problem()` in your action:**

```csharp
return Problem(
    title:      "User not found",
    detail:     $"No user with id {id} exists.",
    statusCode: 404,
    type:       "https://myapi.com/errors/not-found"
);
```

**Validation errors use a different shape:**

When `[ApiController]` auto-returns a 400 for model validation failures, the shape is `ValidationProblemDetails` — an extension of ProblemDetails with an `errors` field:

```json
{
  "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
  "title": "One or more validation errors occurred.",
  "status": 400,
  "traceId": "00-abc123-00",
  "errors": {
    "Name": ["The Name field is required.", "Name cannot exceed 100 characters."],
    "Email": ["The Email field is not a valid email address."]
  }
}
```

**Development vs production:**

Set `ASPNETCORE_ENVIRONMENT=Development` and ASP.NET shows a full developer exception page in the browser with the stack trace. In production that variable is absent and only the safe ProblemDetails shape is returned. Never set `Development` in production.
