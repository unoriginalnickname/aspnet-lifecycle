## Logging — ILogger

Logging is registered automatically by `WebApplication.CreateBuilder(args)` — you do not call `AddLogging()` yourself. The framework configures console, debug, and event source providers by default. What you do is inject `ILogger<T>` and call it.

```csharp
// ILogger<T> is resolved from DI — T is the category name (typically the class):
public class UsersController : ControllerBase
{
    private readonly ILogger<UsersController> _log;

    public UsersController(ILogger<UsersController> log) => _log = log;

    [HttpGet("{id}")]
    public async Task<ActionResult<UserDto>> GetUser(int id)
    {
        _log.LogInformation("Fetching user {UserId}", id);
        var user = await _users.GetByIdAsync(id);
        if (user is null)
        {
            _log.LogWarning("User {UserId} not found", id);
            return NotFound();
        }
        return Ok(user);
    }
}
```

### Log levels

Six levels in order of severity — from noisiest to most critical:

| Level | Method | When to use |
|---|---|---|
| `Trace` | `LogTrace` | Very detailed — individual steps inside a method. Off by default in production. |
| `Debug` | `LogDebug` | Debugging information — variable values, branch decisions. Off by default in production. |
| `Information` | `LogInformation` | Normal operational events — request received, user logged in, job completed. |
| `Warning` | `LogWarning` | Something unexpected but handled — slow query, retry attempted, fallback used. |
| `Error` | `LogError` | A failure that needs attention — unhandled exception, external service down. |
| `Critical` | `LogCritical` | The app cannot continue — database unavailable, out of memory, startup failure. |

Minimum log level is configured per category in `appsettings.json`:

```json
{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning",
      "Microsoft.EntityFrameworkCore": "Warning",
      "MyApp.Services": "Debug"
    }
  }
}
```

`Microsoft.AspNetCore` set to `Warning` suppresses the high-volume request/response logs that ASP.NET writes at `Information` level. `Microsoft.EntityFrameworkCore` set to `Warning` suppresses EF Core's query logging — by default EF Core logs every SQL query it executes at `Information` level, which floods the output in development. Set it to `Debug` or `Information` temporarily when you need to inspect the generated SQL, then return it to `Warning`. Your own namespaces can be configured independently.

### Structured logging — use message templates, not string interpolation

The `{param}` syntax in log messages is not string interpolation — it is a named property that logging frameworks can index, query, and search:

```csharp
// Structured — UserId is a searchable property:
_log.LogInformation("User {UserId} logged in from {IpAddress}", userId, ipAddress);

// AVOID — string interpolation — loses structure, UserId is just text in a string:
_log.LogInformation($"User {userId} logged in from {ipAddress}");
```

With structured logging (e.g. Serilog, Application Insights, OpenTelemetry), you can query `WHERE UserId = 123` across millions of log entries. With string interpolation you can only do text search.

The property names in `{param}` are captured into the log entry's structured data. The rendered message is still human-readable, but the underlying data is structured and queryable.

### Logging exceptions

Pass the exception as the first argument — the logging infrastructure captures the full stack trace from it:

```csharp
try
{
    await _users.UpdateAsync(id, body);
}
catch (Exception ex)
{
    _log.LogError(ex, "Failed to update user {UserId}", id);
    throw;  // or return Problem(...)
}
```

Do not include the exception message in the message template — the exception object already carries it and the logging infrastructure records it automatically. `LogError(ex, "Failed: {Message}", ex.Message)` logs the message twice.

### Scopes — correlating log entries

A log scope adds a set of properties to every log entry written within the scope:

```csharp
using (_log.BeginScope("UserId={UserId} RequestPath={Path}", userId, path))
{
    // every log entry written here carries UserId and RequestPath
    _log.LogInformation("Starting processing");
    await _service.ProcessAsync();
    _log.LogInformation("Processing complete");
}
```

Useful for adding request context (user ID, tenant ID, correlation ID) to all log entries in a block without passing it through every method call.

### LoggerMessage — high-performance logging

For hot paths, define log actions with `LoggerMessage.Define` or the `[LoggerMessage]` source generator — they avoid boxing, string formatting, and delegate allocation on every call:

```csharp
// Source generator approach (.NET 6+) — preferred:
public partial class UsersController : ControllerBase
{
    [LoggerMessage(Level = LogLevel.Information, Message = "Fetching user {UserId}")]
    partial void LogFetchingUser(int userId);

    [LoggerMessage(Level = LogLevel.Warning, Message = "User {UserId} not found")]
    partial void LogUserNotFound(int userId);
}
```

The generator emits a strongly-typed method that only allocates when the log level is enabled. `LogInformation("Fetching user {UserId}", id)` evaluates and allocates the format string on every call regardless of log level — the source generator avoids this.
