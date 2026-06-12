## Cors

Browsers block JavaScript from reading responses from a different domain — e.g. `myapp.com` calling `api.myapp.com`. CORS middleware adds the `Access-Control-Allow-Origin` header to tell the browser the cross-domain request is allowed.

**Preflight:** before a cross-domain POST/PUT/DELETE, the browser automatically sends an OPTIONS request with no body and no credentials that asks "is this cross-domain request allowed?" CORS middleware recognises it and responds with `204` + headers immediately. The real request follows.

**Must come before `UseAuthentication`**. A preflight carries no credentials — if auth runs first and challenges it, CORS headers are never added and the browser reports a CORS error that hides what actually happened.

Registered in startup:

```csharp
builder.Services.AddCors(o => o.AddPolicy("MyPolicy", policy =>
    policy.WithOrigins("https://myapp.com")
          .AllowAnyMethod()
          .AllowAnyHeader()));

app.UseCors("MyPolicy");
```
