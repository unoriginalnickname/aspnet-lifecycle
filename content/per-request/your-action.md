## Your action

Your async method. Every `await` on an I/O call releases the thread back to the thread pool — free to serve other requests while waiting. This is how a small number of threads handles thousands of concurrent requests.

```csharp
[HttpGet("{id}")]
public async Task<ActionResult<UserDto>> GetUser(int id)
{
    var user = await _users.GetByIdAsync(id);   // thread released during DB query
    if (user is null) return NotFound();

    var perms = await _perms.GetForUserAsync(user.Id);  // released again
    return Ok(new UserDto { Id = user.Id, Permissions = perms });
}
```

### Never block with .Result or .Wait()

`.Result` and `.Wait()` hold the calling thread until the task completes. Under load all threads get blocked and the server stops responding — thread-pool starvation.

```csharp
// AVOID — blocks the thread
var user = _users.GetByIdAsync(id).Result;
var user = _users.GetByIdAsync(id).GetAwaiter().GetResult();

// releases the thread:
var user = await _users.GetByIdAsync(id);
```

In ASP.NET Core, the synchronisation context does not capture the request context on `await` — so `.Result` doesn't cause classic deadlocks the way it did in ASP.NET 4.x. But it still holds the thread, and thread-pool starvation under load is the result.

### CancellationToken — stop work when the client disconnects

`HttpContext.RequestAborted` is a `CancellationToken` that is cancelled when the client disconnects before the response is sent. Declare it as an action parameter and the framework injects it automatically — you do not need to read it from `HttpContext` yourself:

```csharp
[HttpGet("{id}")]
public async Task<ActionResult<UserDto>> GetUser(int id, CancellationToken cancellationToken)
{
    // cancellationToken is HttpContext.RequestAborted — cancelled if client disconnects
    var user = await _users.GetByIdAsync(id, cancellationToken);
    if (user is null) return NotFound();

    var perms = await _perms.GetForUserAsync(user.Id, cancellationToken);
    return Ok(new UserDto { Id = user.Id, Permissions = perms });
}
```

Pass the token to every async call that accepts one. When the client disconnects, `OperationCanceledException` is thrown from the awaiting call — the action stops executing, the response is abandoned, and no further work is done. Without it, the DB query and HTTP call continue to completion even though no one will receive the response.

### Sequential vs parallel awaits

Two sequential awaits run one after the other — the second starts only when the first completes:

```csharp
// Sequential — total time = A + B:
var user  = await _users.GetByIdAsync(id);
var perms = await _perms.GetForUserAsync(id);
```

If the two calls are independent — neither needs the result of the other — run them in parallel with `Task.WhenAll`:

```csharp
// Parallel — total time = max(A, B):
var userTask  = _users.GetByIdAsync(id);
var statsTask = _stats.GetForUserAsync(id);

await Task.WhenAll(userTask, statsTask);

var user  = userTask.Result;   // .Result is safe here — the task is already completed
var stats = statsTask.Result;
```

`.Result` is safe after `await Task.WhenAll` because both tasks are guaranteed to have completed — no thread blocking occurs.

If either task throws, `await Task.WhenAll` rethrows the first faulted task's exception directly — not an `AggregateException`. The other tasks continue to completion regardless; their exceptions are captured on the `Task` objects but not rethrown automatically. If you need to inspect all exceptions, read `task.Exception?.InnerExceptions` on each task after the `await`:

```csharp
try
{
    await Task.WhenAll(userTask, statsTask);
}
catch
{
    // Task.Exception is typed as AggregateException? — it wraps the task's faults.
    // This is distinct from what await throws: await unwraps the first inner exception,
    // but the AggregateException is still there on the Task object for manual inspection.
    if (userTask.IsFaulted)
        _log.LogError(userTask.Exception!.InnerException, "User fetch failed");
    if (statsTask.IsFaulted)
        _log.LogError(statsTask.Exception!.InnerException, "Stats fetch failed");
    throw;
}
```

`AggregateException` only surfaces directly if you block with `.Result` or `.Wait()` on the `WhenAll` task — which the earlier section already identifies as a mistake.

### ConfigureAwait

`ConfigureAwait(false)` tells the awaiter not to resume on the original synchronisation context. In ASP.NET Core there is no synchronisation context — `ConfigureAwait(false)` has no effect on behaviour in controller code and is not necessary.

It is still useful in library code that may run in contexts that do have a synchronisation context (e.g. WPF, WinForms, old ASP.NET 4.x). If you are writing a library used across multiple hosting environments, `ConfigureAwait(false)` on every awaitable call is still considered best practice to avoid deadlocks in those environments.

```csharp
// In library code — good practice:
var data = await _repository.GetAsync(id).ConfigureAwait(false);

// In ASP.NET Core controller code — no effect, optional:
var data = await _repository.GetAsync(id);  // same behaviour
```

### Returning from an action

An action method can return any of the following — the framework handles each correctly:

```csharp
// T directly — implicitly wrapped as Ok(dto):
public async Task<ActionResult<UserDto>> GetUser(int id)
    => await _users.GetByIdAsync(id) is { } user ? user : NotFound();

// Task<IActionResult> — when you need flexibility without T:
public async Task<IActionResult> GetUser(int id)
{
    var user = await _users.GetByIdAsync(id);
    return user is null ? NotFound() : Ok(user);
}

// IActionResult directly (synchronous helper methods):
public IActionResult Ping() => Ok("pong");

// Void-returning actions — valid but no response body is written:
public async Task DeleteUser(int id)
    => await _users.DeleteAsync(id);
// ↑ returns 200 with empty body — prefer returning NoContent() explicitly
```

Prefer `Task<ActionResult<T>>` over `Task<IActionResult>` — the `T` gives Swagger the response shape and enables the implicit `return dto` conversion. Use `Task<IActionResult>` only when the action can return multiple different body types that cannot be captured by a single `T`.
