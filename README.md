# ASP.NET Core — Full Request Lifecycle

> A comprehensive, single-page reference covering everything that happens from TCP connection to JSON bytes on the wire in an ASP.NET Core application.

🔗 **Live site:** [aspnet-lifecycle.vercel.app](https://aspnet-lifecycle.vercel.app/)

---

## What This Is

A deep-dive reference guide through the complete lifecycle of an ASP.NET Core HTTP request — from startup and boot, through middleware, routing, dependency injection, filters, model binding, async execution, result handling, serialization, error handling, and back out as a response.

It's aimed at developers who already know the basics and want to understand *why* things work the way they do, not just *how* to use them.

---

## What's Covered

The guide walks through **12 numbered stages**:

| # | Stage | What it covers |
|---|-------|----------------|
| ① | **Boot** | `WebApplication.CreateBuilder`, the two-phase startup, middleware registration, Kestrel |
| ② | **Request** | TCP → `HttpContext`, JWT structure, CORS `Origin` header, DI scope creation |
| ③ | **Middleware** | Pipeline execution model, `next()` delegation, short-circuiting, `HasStarted`, `UseWhen` / `Map`, class-based middleware |
| ④ | **Routing** | URL matching, `[ApiController]`, route templates, 404 before controller instantiation |
| ⑤ | **DI** | Singleton / Scoped / Transient lifetimes, captive dependency bug, constructor injection |
| ⑥ | **Filters** | `IActionFilter`, `IExceptionFilter`, `IAuthorizationFilter`, `IResourceFilter`, filter ordering |
| ⑦ | **Binding** | All six `[From*]` attributes, data annotations, inference rules, `ModelState` validation |
| ⑧ | **Async** | `async`/`await` on the thread pool, `ActionResult<T>`, why `.Result`/`.Wait()` kills scalability |
| ⑨ | **Results** | Every `IActionResult` helper — 200/201/204/301/400/401/403/404/500, `ProblemDetails` |
| ⑩ | **Serialization** | `System.Text.Json`, `Accept` header negotiation, all `[Json*]` attributes, `JsonSerializerOptions` |
| ⑪ | **Errors** | `UseExceptionHandler` vs `IExceptionFilter`, RFC 7807 `ProblemDetails`, W3C `traceId` |
| ⑫ | **Response** | Middleware unwind, Kestrel TCP write, Scoped service disposal |

---

## Key Concepts Explained

**Why middleware order matters** — `UseAuthentication` must precede `UseAuthorization`; `UseCors` must precede both. The guide explains the causal chain behind each ordering constraint.

**Filters vs Middleware** — Filters run inside the MVC layer and see controller/action metadata; middleware runs before MVC and only sees raw HTTP. The guide shows exactly where each layer's visibility begins and ends.

**The captive dependency bug** — What happens when a Scoped service is injected into a Singleton, and why it only shows up under load.

**JWT anatomy** — Three base64-encoded parts, what each contains, and exactly when/where in the pipeline the signature is verified and claims extracted.

**CORS preflight** — Why the browser sends an `OPTIONS` request before a cross-domain `POST`, why it carries no credentials, and what goes wrong if authentication middleware runs first.

**`traceId` and `ProblemDetails`** — How W3C TraceContext IDs flow automatically from logs to error responses, so clients can report errors without you ever exposing a stack trace.

---

## Who It's For

- ASP.NET Core developers who want a mental model of the full request pipeline
- Developers debugging ordering issues in middleware or filters
- Engineers onboarding to a .NET codebase who want the "why" behind common patterns
- Anyone preparing for a .NET technical interview

---

## Tech

- Static HTML/CSS — no build step, no framework
- Hosted on [Vercel](https://vercel.com)

---

## Contributing

Found something incorrect or missing? Open an issue or PR. The goal is accuracy — every stage should reflect current ASP.NET Core behaviour.

---

*Last updated: June 2026*
