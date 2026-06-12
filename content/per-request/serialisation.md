## Serialisation

Serialisation is the final step of the MVC pipeline — after your action returns an `IActionResult`, the result calls `ExecuteResultAsync`, which selects an output formatter, runs it against your C# object, and writes the bytes to `HttpContext.Response.Body`. The output formatter also sets `Content-Type` on the response.

`System.Text.Json` is the default output formatter, producing `application/json`. The formatter that runs is chosen through **content negotiation** — the process of matching what the client accepts against what the app can produce.

---

## Content negotiation — output formatters

When your action returns `Ok(user)`, `ObjectResult` does not write bytes directly. It runs content negotiation:

1. Reads the request's `Accept` header — e.g. `Accept: application/json, application/xml;q=0.8`
2. Compares the accepted MIME types against the registered output formatters
3. Selects the formatter with the highest `q` (quality) value that the app supports
4. If no formatter matches any accepted type, returns `406 Not Acceptable` — the action result is discarded, no body is written

The `q` value (0–1, default 1.0) expresses preference. `application/json, application/xml;q=0.8` means "I prefer JSON but will accept XML." The app picks JSON if it can produce it; XML only if JSON is not available.

**`Accept: */*`** — the browser default — matches any formatter. The app picks its first registered formatter, which is `System.Text.Json`.

```csharp
// Default — JSON only:
builder.Services.AddControllers();

// JSON + XML:
builder.Services.AddControllers()
    .AddXmlSerializerFormatters();

// JSON + XML (DataContractSerializer instead of XmlSerializer):
builder.Services.AddControllers()
    .AddXmlDataContractSerializerFormatters();
```

**`[Produces]` — restricting what an action will return**

`[Produces]` locks an action (or controller) to a specific content type, bypassing negotiation entirely. If the client's `Accept` header does not include the specified type, `406 Not Acceptable` is returned without running the action.

```csharp
[Produces("application/json")]   // this action always returns JSON — ignores Accept
public async Task<ActionResult<UserDto>> GetUser(int id) { … }
```

Use `[Produces]` on controllers or actions whose output format is fixed by contract and must not vary by client preference. It also signals to Swagger that only that content type is produced, giving more accurate documentation.

---

## Output formatter — how System.Text.Json works

`ObjectResult.ExecuteResultAsync` calls `IOutputFormatter.WriteAsync`. For `SystemTextJsonOutputFormatter`:

1. Resolves `JsonSerializerOptions` from the registered options (configured via `AddJsonOptions`)
2. Calls `JsonSerializer.SerializeAsync(responseBody, value, type, options)` — writes JSON bytes directly to `HttpContext.Response.Body`
3. `ObjectResult` sets `Content-Type: application/json; charset=utf-8` on the response before writing

The serialiser walks the object graph using the options' property naming policy, ignore conditions, converters, and reference handling. All of this is configured once at startup and applied to every response.

**Key attributes:**

| Attribute | Effect |
|---|---|
| `[JsonIgnore]` | Exclude this property from serialisation entirely |
| `[JsonPropertyName("x")]` | Override the output key — wins over the global `PropertyNamingPolicy` |
| `[JsonIgnore(Condition = WhenWritingNull)]` | Exclude only when the value is null |
| `[JsonIgnore(Condition = WhenWritingDefault)]` | Exclude when value equals the type default (0, false, null) |
| `[JsonConverter(typeof(T))]` | Use a custom `JsonConverter<T>` for this property |
| `[JsonInclude]` | Include a non-public property or field |

```csharp
public class UserDto
{
    public int    Id    { get; set; }
    public string Name  { get; set; }

    [JsonPropertyName("email_address")]  // output key is "email_address", not "emailAddress"
    public string Email { get; set; }

    [JsonIgnore]
    public string PasswordHash { get; set; }  // never in the response
}
```

**Global options — configure before `builder.Build()`:**

```csharp
builder.Services.AddControllers()
    .AddJsonOptions(o => {
        // property names as camelCase: "userId" not "UserId"
        o.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;

        // omit null properties from the response entirely
        o.JsonSerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;

        // allow trailing commas and // comments in incoming JSON
        o.JsonSerializerOptions.ReadCommentHandling = JsonCommentHandling.Skip;
        o.JsonSerializerOptions.AllowTrailingCommas = true;
    });
```

---

## Input formatters — deserialising request bodies

Content negotiation also applies to incoming request bodies. When model binding reads a `[FromBody]` parameter, it selects an **input formatter** based on the request's `Content-Type` header:

- `Content-Type: application/json` → `SystemTextJsonInputFormatter` deserialises the body
- `Content-Type: application/xml` → XML input formatter (if registered)
- Unrecognised `Content-Type` → `415 Unsupported Media Type`

The input formatter is the counterpart to the output formatter. Both read from the same `JsonSerializerOptions` registered via `AddJsonOptions`.

**`[Consumes]` — restricting what an action accepts**

`[Consumes]` locks an action to a specific request `Content-Type`. Requests with a different content type receive `415 Unsupported Media Type` before the action runs. Also used in route selection — two actions with the same route template but different `[Consumes]` can coexist, selected by the request's `Content-Type`.

```csharp
[HttpPost]
[Consumes("application/json")]
public async Task<ActionResult<UserDto>> CreateUserJson([FromBody] CreateUserRequest req) { … }

[HttpPost]
[Consumes("application/xml")]
public async Task<ActionResult<UserDto>> CreateUserXml([FromBody] CreateUserRequest req) { … }
```

---

## What breaks and why

**`Accept` header mismatch → 406 Not Acceptable**
When `[Produces]` is set on the action, the mismatch is detected before the action runs — the framework short-circuits with `406` immediately. Without `[Produces]`, the action runs and returns a result, but `ObjectResult` then finds no registered formatter that matches the client's `Accept` header and discards the result, returning `406` with no body. Either way the client sees `406` — the difference is whether the action code executed.

**`[JsonPropertyName]` and global `PropertyNamingPolicy` conflict silently**
`[JsonPropertyName("user_id")]` on a property with a `CamelCase` naming policy produces `user_id` in the output — not `userId`. The attribute always wins over the global policy. This is correct behaviour but causes bugs when developers assume the naming policy applies uniformly. Check each `[JsonPropertyName]` to confirm the output key is intentional.

**Circular reference throws `JsonException` at serialisation time**
If two objects reference each other — e.g. `User` has `List<Post>` and `Post` has `User` — `System.Text.Json` throws by default. Fix by projecting to a DTO without the cycle, adding `[JsonIgnore]` to one direction, or configuring `ReferenceHandler`:

```csharp
builder.Services.AddControllers()
    .AddJsonOptions(o =>
        o.JsonSerializerOptions.ReferenceHandler = ReferenceHandler.IgnoreCycles);
```

`ReferenceHandler.IgnoreCycles` silently drops the second reference. `ReferenceHandler.Preserve` adds `$id`/`$ref` metadata that changes the JSON shape — clients that don't expect it will fail to deserialise. Prefer projecting to a DTO without cycles.

**`Content-Type` missing on a POST with a body**
If the client sends a JSON body without `Content-Type: application/json`, the input formatter does not recognise it and model binding produces `null` for the `[FromBody]` parameter. With `[ApiController]`, this returns `400 Bad Request` — "A non-empty request body is required." The client must set `Content-Type` explicitly.

**`[Produces]` set but `AddXmlSerializerFormatters()` not called**
`[Produces("application/xml")]` tells the negotiator the action produces XML. If the XML formatter is not registered, `ObjectResult` finds no matching formatter at response time and returns an empty `200` with no body. Register the formatter and the attribute together.
