## HttpsRedirection

Any plain HTTP request — e.g. `http://api.myapp.com/users` — receives a `301 Moved Permanently` redirect to the HTTPS equivalent. Nothing else in the pipeline runs for that request.

HTTPS requests pass through unchanged.

Registered in startup via `app.UseHttpsRedirection()`. The HTTPS port is read from `ASPNETCORE_HTTPS_PORT` or inferred from the server configuration.

### HSTS — HTTP Strict Transport Security

`UseHsts()` adds the `Strict-Transport-Security` header to responses, instructing the browser to only ever contact this domain over HTTPS — even if the user types `http://` directly. Once a browser sees the header, it enforces HTTPS locally for the duration specified by `max-age` without making a round-trip to the server first.

```csharp
// Pipeline — HSTS before HTTPS redirection:
app.UseHsts();
app.UseHttpsRedirection();
```

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

`max-age=31536000` is one year. The browser will refuse plain HTTP connections to this domain for one year from the last time it saw the header. `includeSubDomains` extends the policy to all subdomains.

**HSTS is not for development.** The default ASP.NET Core template wraps both in an environment check:

```csharp
if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
}
app.UseHttpsRedirection();
```

HSTS in development means your browser will refuse HTTP for your local dev domain for up to a year — difficult to undo and causes confusing connection errors. Never enable it outside production.

**HSTS is a browser feature, not a server feature.** The server sends a header; the browser enforces the policy. Requests from non-browser clients (curl, Postman, mobile apps, server-to-server) are not affected by HSTS — only `UseHttpsRedirection` handles those.

**The interaction between HSTS and HTTPS redirection:**
- First visit (HTTP) → `UseHttpsRedirection` redirects to HTTPS → browser follows redirect → server sends HSTS header
- All subsequent visits → browser enforces HTTPS locally, never sends HTTP request at all
- `UseHttpsRedirection` is redundant for browsers that have seen HSTS, but necessary for first visits and non-browser clients

Configured in startup before `builder.Build()`:

```csharp
builder.Services.AddHsts(o =>
{
    o.MaxAge            = TimeSpan.FromDays(365);
    o.IncludeSubDomains = true;
    o.Preload           = false;  // only set true if you submit to the HSTS preload list
});
```

`Preload = true` signals browsers to include the domain in their hardcoded HSTS preload list — meaning the browser never sends HTTP to this domain even on the very first visit, before it has ever seen the header. This is irreversible in practice; only set it if you are certain the domain will always serve HTTPS.
