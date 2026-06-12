## Binding

Model binding is the process of reading values from an incoming HTTP request and mapping them onto the parameters of the matched action method. It runs after `IResourceFilter` and before `IActionFilter.OnActionExecuting` — by the time your action filter fires, binding has already completed and `context.ActionArguments` holds the typed values.

The model binder is registered by `AddControllers()` at startup. At request time it examines each action parameter, determines where its value should come from, reads that value, converts it to the parameter's type, and validates it against any data annotations. If validation fails and `[ApiController]` is present, the pipeline short-circuits with a `400 Bad Request` before your action method runs.

---

## Where binding reads from — sources

Each action parameter has a binding source — the part of the HTTP request the binder reads its value from. The source is determined either by an explicit attribute or by `[ApiController]` inference rules.

### Step 1 — Check for an explicit binding source attribute

If the parameter has a `[From…]` attribute, that attribute determines the source unconditionally. Explicit attributes always override inference.

| Attribute | Reads from | Notes |
|---|---|---|
| `[FromRoute]` | `HttpContext.Request.RouteValues` | Values extracted from URL segments by routing — e.g. `{id}` in `/api/users/{id}`. Already stored as strings; binder converts to target type. |
| `[FromQuery]` | `HttpContext.Request.Query` | Query string — e.g. `?page=2&sort=name`. Each key maps to a parameter by name. |
| `[FromBody]` | `HttpContext.Request.Body` | The raw request body, read once and deserialised by `System.Text.Json`. Only one `[FromBody]` parameter is allowed per action — the body stream can only be read once. |
| `[FromHeader]` | `HttpContext.Request.Headers` | A named HTTP header — e.g. `[FromHeader(Name = "X-Api-Version")] string version` reads the `X-Api-Version` header. |
| `[FromForm]` | `HttpContext.Request.Form` | Form fields submitted as `application/x-www-form-urlencoded` or `multipart/form-data`. Use for file uploads via `IFormFile`. Mutually exclusive with `[FromBody]` — both read from the request body. |
| `[FromServices]` | The DI container | Resolves the parameter type from the request's DI scope. In .NET 7+ with `[ApiController]`, this can be omitted — the binder infers it if the type is registered in DI. |

### Step 2 — Apply [ApiController] inference rules (if no explicit attribute)

With `[ApiController]` on the controller, the binder applies these inference rules in order when no explicit attribute is present:

1. **The type is registered in the DI container (.NET 7+)** → `[FromServices]`. The binder checks whether the parameter's type has a registration in the DI container. If so, it injects the service. This is what allows action parameters like `CancellationToken` and registered services to work without any attribute.

2. **The parameter name matches a route segment** → `[FromRoute]`. The binder checks whether the parameter name appears as a key in `HttpContext.Request.RouteValues`. If `{id}` is in the route template and the parameter is named `id`, it binds from route.

3. **The parameter is a simple type** → `[FromQuery]`. Simple types are primitives (`int`, `string`, `bool`, `Guid`, `DateTime`) and types with a `TypeConverter` from string. These are read from the query string by parameter name.

4. **The parameter is a complex type** → `[FromBody]`. A complex type is a class or struct that is not a simple type and not `IFormFile`. The binder reads the request body as JSON and deserialises it into the parameter type. Only one complex type parameter per action is allowed — multiple `[FromBody]` parameters would require reading the body stream multiple times, which is not possible.

```csharp
// [ApiController] inference in action:

[HttpGet("{id}")]                          // route template has {id}
public async Task<ActionResult<UserDto>> GetUser(
    int id,                                // name matches route segment → [FromRoute]
    [FromQuery] bool includeDeleted        // explicit → [FromQuery]
) { … }

[HttpPost]
public async Task<ActionResult<UserDto>> CreateUser(
    CreateUserRequest body,                // complex type, no explicit attribute → [FromBody]
    ILogger<UsersController> log           // registered in DI (.NET 7+) → [FromServices]
) { … }

[HttpPut("{id}")]
public async Task<ActionResult<UserDto>> UpdateUser(
    int id,                                // matches route segment → [FromRoute]
    UpdateUserRequest body,                // complex type → [FromBody]
    [FromQuery] bool notify                // explicit → [FromQuery]
) { … }
```

Without `[ApiController]`, none of these inferences apply — every parameter requires an explicit attribute or the binder falls back to a composite search across route values, query string, and form data.

---

## Type conversion

After the binder reads the raw string value from its source, it converts it to the parameter's declared type. This conversion is not JSON deserialisation — it uses `TypeConverter` for simple types:

- `"5"` from `RouteValues["id"]` → `int 5`
- `"true"` from `Query["notify"]` → `bool true`
- `"2026-06-11"` from a query parameter → `DateTime`
- `"d3b07384-d113-4b8b-a3e6-5e62f47d26e5"` from a route segment → `Guid`

If conversion fails — `"abc"` for an `int` parameter — the binder adds an error to `ModelState` and the parameter receives its type's default value (`0` for `int`). With `[ApiController]`, this triggers an automatic `400 Bad Request` before the action runs.

Collection types bind from multiple values with the same key:

```csharp
// GET /api/users?role=Admin&role=Editor
public ActionResult<List<UserDto>> GetByRoles([FromQuery] List<string> role) { … }
// role == ["Admin", "Editor"]
```

---

## Validation

After binding completes, the binder validates each bound model against its data annotation attributes. Validation runs on the bound object — not on the raw string — so the value has already been converted to the target type before annotations are checked.

### Data annotation attributes

| Attribute | Validates |
|---|---|
| `[Required]` | Property must be present and non-null. For strings, also non-empty. |
| `[MaxLength(n)]` | String or array length must be ≤ n characters/elements. |
| `[MinLength(n)]` | String or array length must be ≥ n characters/elements. |
| `[StringLength(max)]` | String length between an optional minimum and max. |
| `[Range(min, max)]` | Numeric value must fall within the inclusive bounds. |
| `[RegularExpression(pattern)]` | String must match the regex pattern. |
| `[EmailAddress]` | String must match a basic email format — local@domain. Does not verify the address exists. |
| `[Url]` | String must be a valid absolute URL with a scheme (`http://` or `https://`). |
| `[Compare("OtherProperty")]` | Two properties must have equal values — classic use: password and confirm password fields. |
| `[EnumDataType(typeof(E))]` | Value must be a defined member of the given enum type. |

Any failed annotation adds an error to `ModelState` under the property name. With `[ApiController]`, once all parameters have been bound and validated, the framework checks `ModelState.IsValid`. If false, it calls the `InvalidModelStateResponseFactory` — by default producing a `400 Bad Request` with a `ValidationProblemDetails` body listing every failed property and its error messages:

```json
{
  "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
  "title": "One or more validation errors occurred.",
  "status": 400,
  "errors": {
    "Name": ["The Name field is required.", "The field Name must be a string with a maximum length of 100."],
    "Email": ["The Email field is not a valid e-mail address."]
  }
}
```

This fires before your action method runs. You do not need `if (!ModelState.IsValid)` checks.

### IValidatableObject — cross-property validation

Data annotations validate individual properties in isolation. `IValidatableObject` lets you write validation logic that spans multiple properties — conditions that involve comparing or combining values.

```csharp
public class DateRangeRequest : IValidatableObject
{
    [Required]
    public DateTime StartDate { get; set; }

    [Required]
    public DateTime EndDate { get; set; }

    public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
    {
        // Validate() is called only after all individual annotations have passed.
        // If StartDate or EndDate failed [Required], Validate() is not called.

        if (EndDate <= StartDate)
            yield return new ValidationResult(
                "EndDate must be after StartDate.",
                new[] { nameof(EndDate) }  // names the property the error belongs to
            );

        if ((EndDate - StartDate).TotalDays > 365)
            yield return new ValidationResult(
                "Date range cannot exceed one year.",
                new[] { nameof(StartDate), nameof(EndDate) }
            );
    }
}
```

`Validate()` is called after all individual property annotations pass. If any `[Required]` or `[Range]` annotation fails first, `Validate()` is not called — there is no point cross-validating properties that are already individually invalid.

Errors returned from `Validate()` are added to `ModelState` like any other validation error. With `[ApiController]`, they produce the same `400 Bad Request` response.

---

## Custom model binders

When the built-in binding logic cannot handle a type — a value object, a type that serialises in a non-standard way, a parameter that needs to be read from multiple sources — implement `IModelBinder`.

```csharp
// A Point type that comes from the query string as "?point=3,7" rather than "?x=3&y=7":
public class PointModelBinder : IModelBinder
{
    public Task BindModelAsync(ModelBindingContext bindingContext)
    {
        // bindingContext.ModelName is the parameter name — e.g. "point"
        var valueProviderResult = bindingContext.ValueProvider.GetValue(bindingContext.ModelName);

        if (valueProviderResult == ValueProviderResult.None)
        {
            // no value found for this parameter name — leave the result empty
            return Task.CompletedTask;
        }

        var value = valueProviderResult.FirstValue;  // raw string from the value provider

        var parts = value?.Split(',');
        if (parts?.Length != 2 || !int.TryParse(parts[0], out var x) || !int.TryParse(parts[1], out var y))
        {
            // parsing failed — add a model error so ModelState captures it
            bindingContext.ModelState.TryAddModelError(
                bindingContext.ModelName,
                "Point must be in the format 'x,y' — e.g. '3,7'.");
            return Task.CompletedTask;
        }

        bindingContext.Result = ModelBindingResult.Success(new Point(x, y));
        return Task.CompletedTask;
    }
}
```

Tell the framework to use this binder for the `Point` type via `IModelBinderProvider`, or apply it directly to a parameter with `[ModelBinder]`:

```csharp
[HttpGet("nearest")]
public ActionResult<LocationDto> GetNearest(
    [ModelBinder(typeof(PointModelBinder))] Point origin
) { … }
// GET /api/locations/nearest?origin=3,7
```

Or register globally so all `Point` parameters use it without needing the attribute:

```csharp
// Program.cs — before builder.Build():
builder.Services.AddControllers(o =>
    o.ModelBinderProviders.Insert(0, new PointModelBinderProvider())
);
```

`ModelBinderProviders.Insert(0, …)` inserts at position 0 — before the built-in providers. The framework tries providers in order and uses the first one that returns a non-null binder for the target type.

---

## IFormFile — file uploads

File uploads use `[FromForm]` with `IFormFile` as the parameter type. The binder reads the file from the multipart body and exposes it as a stream:

```csharp
[HttpPost("avatar")]
public async Task<IActionResult> UploadAvatar([FromForm] IFormFile file)
{
    if (file.Length == 0) return BadRequest("File is empty.");

    // file.FileName — original filename from the client (do not trust this for storage)
    // file.ContentType — MIME type declared by the client (do not trust this either)
    // file.Length — size in bytes

    var extension = Path.GetExtension(file.FileName).ToLowerInvariant();
    if (extension is not ".jpg" and not ".png")
        return BadRequest("Only .jpg and .png are allowed.");

    var storedName = $"{Guid.NewGuid()}{extension}";  // generate your own safe filename
    var path = Path.Combine("uploads", storedName);

    await using var stream = System.IO.File.Create(path);
    await file.CopyToAsync(stream);

    return Ok(new { path = storedName });
}
```

Multiple files use `IFormFileCollection` or `List<IFormFile>`:

```csharp
[HttpPost("attachments")]
public async Task<IActionResult> UploadAttachments([FromForm] IFormFileCollection files) { … }
```

Do not use `file.FileName` as the storage path. The client controls this value and can send paths like `../../appsettings.json`. Always generate your own filename for storage.

---

## What breaks and why

**Two `[FromBody]` parameters on one action**
The request body is a stream that can only be read once. Attempting to bind two `[FromBody]` parameters throws `InvalidOperationException: Action … has more than one parameter that is bound from the request body.` at startup when the action is being registered — not at request time.

**`[FromBody]` and `[FromForm]` on the same action**
Both read from `HttpContext.Request.Body`. The binder throws the same error as above. Use `[FromForm]` for all parameters when handling form data, including file uploads.

**Complex type inferred as `[FromBody]` on a GET action**
`[ApiController]` inference applies `[FromBody]` to complex types regardless of HTTP method. A `GET` action with a complex parameter is inferred as `[FromBody]`, but `GET` requests conventionally have no body. The binder attempts to deserialise `null` or an empty body and produces a `400`. Add explicit `[FromQuery]` to complex types on GET actions, or restructure them as separate simple parameters.

**`[Required]` on a non-nullable value type**
`int`, `bool`, `DateTime`, and other value types cannot be null — `[Required]` has no effect on them because they always have a value (their default). Use `[Range]` or `[MinLength]` to enforce meaningful constraints, or use a nullable type (`int?`) if absence is semantically different from zero.

**Validation passes but the value is semantically wrong**
Data annotations validate format and range, not business rules. A `[Range(1, 150)]` age passes for `149`, but your system may not support ages over 120. Business rule validation belongs in your service layer, not in binding attributes. Binding and annotation validation are the first line of defence against malformed input — not a substitute for domain validation.

**Custom `IModelBinder` does not call `bindingContext.Result = ModelBindingResult.Success(…)`**
If the binder returns `Task.CompletedTask` without setting `bindingContext.Result`, the framework treats the parameter as unbound — it receives its default value (`null` for reference types, `0` for value types) with no error added to `ModelState`. This can silently produce wrong behaviour. Always set `bindingContext.Result` or add a `ModelState` error.
