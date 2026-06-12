## Environments

The environment name tells ASP.NET Core which context the app is running in — development, staging, or production. It controls which configuration files are loaded, which middleware is active, and how errors are presented. Several files in this reference mention `ASPNETCORE_ENVIRONMENT` — this file explains what it is and how it works.

### Setting the environment

The environment is read from the `ASPNETCORE_ENVIRONMENT` environment variable. ASP.NET Core treats it as a string — any value is valid — but three names have built-in meaning:

| Value | Meaning |
|---|---|
| `Development` | Developer machine. Verbose error pages, debug logging. |
| `Staging` | Pre-production testing environment. Mirrors production behaviour. |
| `Production` | Live. Safe error responses, minimal logging. |

If `ASPNETCORE_ENVIRONMENT` is not set, the app defaults to `Production`.

**Setting in `launchSettings.json` (local development only — never deployed):**

```json
{
  "profiles": {
    "MyApp": {
      "environmentVariables": {
        "ASPNETCORE_ENVIRONMENT": "Development"
      }
    }
  }
}
```

**Setting in a Docker container:**

```dockerfile
ENV ASPNETCORE_ENVIRONMENT=Production
```

**Setting in Azure App Service:** configure as an application setting named `ASPNETCORE_ENVIRONMENT`.

### Reading the environment in code

Two interfaces expose the current environment. Choose based on what else you need:

**`IHostEnvironment`** — available in the generic host and in ASP.NET Core. Provides:
- `EnvironmentName` — the raw string, e.g. `"Development"`
- `IsDevelopment()`, `IsStaging()`, `IsProduction()`, `IsEnvironment("Custom")` — extension methods
- `ContentRootPath` — the base directory of the application (where `appsettings.json` lives)
- `ContentRootFileProvider` — an `IFileProvider` rooted at `ContentRootPath`

**`IWebHostEnvironment`** — ASP.NET Core only, inherits from `IHostEnvironment`. Adds:
- `WebRootPath` — the web root directory served by `UseStaticFiles` (defaults to `wwwroot/`)
- `WebRootFileProvider` — an `IFileProvider` rooted at `WebRootPath`

```
IHostEnvironment
├── EnvironmentName
├── ContentRootPath      ← application base — appsettings, assemblies, private files
└── ContentRootFileProvider

IWebHostEnvironment : IHostEnvironment
├── (all of the above)
├── WebRootPath          ← publicly served files — wwwroot/ by default
└── WebRootFileProvider
```

Inject `IHostEnvironment` when you only need the environment name or content root. Inject `IWebHostEnvironment` when you also need the web root — for example, to read files from `wwwroot/` in a service.

```csharp
// Only need environment checks — IHostEnvironment is sufficient:
public class FeatureFlagService
{
    private readonly IHostEnvironment _env;
    public FeatureFlagService(IHostEnvironment env) => _env = env;

    public bool IsExperimentEnabled()
        => _env.IsDevelopment() || _env.IsStaging();
}

// Need to read files from wwwroot/ — IWebHostEnvironment needed:
public class AssetService
{
    private readonly IWebHostEnvironment _env;
    public AssetService(IWebHostEnvironment env) => _env = env;

    public string GetAssetPath(string filename)
        => Path.Combine(_env.WebRootPath, "assets", filename);
        // e.g. /app/wwwroot/assets/logo.png
}
```

Or directly in `Program.cs` via `app.Environment` — which is an `IWebHostEnvironment`:

```csharp
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler();
    app.UseHsts();
}
```

`IsDevelopment()`, `IsStaging()`, `IsProduction()` are case-insensitive extension methods. `IsEnvironment("Custom")` handles non-standard names.

### What the environment controls — the practical consequences

**Error pages:** `DeveloperExceptionPageMiddleware` is auto-inserted only when `IsDevelopment()` is true. In any other environment, it is not inserted and `UseExceptionHandler` returns only the safe `ProblemDetails` shape. A junior mistake is running production with `ASPNETCORE_ENVIRONMENT=Development` — stack traces are returned to every caller.

**Configuration files:** `WebApplication.CreateBuilder` loads `appsettings.json` first, then `appsettings.{Environment}.json` on top of it. Values in the environment-specific file override the base file. A `appsettings.Development.json` with verbose logging settings is never loaded in production.

```
appsettings.json               ← loaded always
appsettings.Development.json   ← loaded only when ASPNETCORE_ENVIRONMENT=Development
appsettings.Production.json    ← loaded only when ASPNETCORE_ENVIRONMENT=Production
```

**Swagger:** conventionally registered only in Development so the API schema is not publicly exposed in production:

```csharp
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}
```

**Scope validation:** the DI container validates that Scoped services are not injected into Singletons (captive dependency) only in Development. In production the check is off by default. Enable it explicitly if you want the protection in all environments:

```csharp
builder.Host.UseDefaultServiceProvider(o =>
{
    o.ValidateScopes      = true;  // catches captive dependencies
    o.ValidateOnBuild     = true;  // validates registrations at startup rather than first resolution
});
```

### The `DOTNET_ENVIRONMENT` variable

`DOTNET_ENVIRONMENT` is an alternative to `ASPNETCORE_ENVIRONMENT` used by the generic host. If both are set, `ASPNETCORE_ENVIRONMENT` takes precedence for ASP.NET Core apps. In practice, use `ASPNETCORE_ENVIRONMENT` for web apps.
