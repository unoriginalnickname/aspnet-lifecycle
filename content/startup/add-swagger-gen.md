## AddSwaggerGen

Registers API documentation generation. At startup, `AddSwaggerGen` reads every controller and action — their routes, parameters, return types, and attributes — and produces a machine-readable description of your API (OpenAPI spec).

```csharp
builder.Services.AddSwaggerGen();
```

At request time (development only), `UseSwagger()` serves the spec at `/swagger/v1/swagger.json` and `UseSwaggerUI()` serves the interactive docs UI at `/swagger`.

```csharp
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}
```

**Never expose in production.** The spec describes every endpoint, parameter, and response shape of your API — useful for developers, useful for attackers.

Use `[ProducesResponseType]` on actions to document response shapes accurately:

```csharp
[HttpGet("{id}")]
[ProducesResponseType(typeof(UserDto), 200)]
[ProducesResponseType(404)]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }
```

---

## XML doc comments — populating Swagger descriptions

By default Swagger shows endpoint routes and parameter types but no descriptions. Adding C# XML doc comments (`<summary>`, `<param>`, `<remarks>`) to your controllers and actions populates the Swagger UI with human-readable text — without any changes to the API surface.

**Step 1 — enable XML doc generation in the project file:**

```xml
<!-- MyApp.csproj -->
<PropertyGroup>
  <GenerateDocumentationFile>true</GenerateDocumentationFile>
  <NoWarn>$(NoWarn);1591</NoWarn>  <!-- suppress CS1591: missing XML comment warnings -->
</PropertyGroup>
```

`GenerateDocumentationFile` tells the compiler to emit an XML file alongside the assembly. `NoWarn 1591` suppresses the warning that fires for every public member that lacks a comment — useful while you add comments incrementally.

**Step 2 — tell Swagger to read the XML file:**

```csharp
builder.Services.AddSwaggerGen(o =>
{
    var xmlFile = $"{Assembly.GetExecutingAssembly().GetName().Name}.xml";
    var xmlPath = Path.Combine(AppContext.BaseDirectory, xmlFile);
    o.IncludeXmlComments(xmlPath);
});
```

**Step 3 — add comments to your controllers and actions:**

```csharp
/// <summary>
/// Retrieves a user by their unique identifier.
/// </summary>
/// <param name="id">The user's numeric ID.</param>
/// <returns>The user if found, or 404 if no user with that ID exists.</returns>
[HttpGet("{id}")]
[ProducesResponseType(typeof(UserDto), 200)]
[ProducesResponseType(404)]
public async Task<ActionResult<UserDto>> GetUser(int id) { … }

/// <summary>
/// Creates a new user account.
/// </summary>
/// <remarks>
/// The email address must be unique across all users.
/// Returns 409 Conflict if the email is already registered.
/// </remarks>
[HttpPost]
[ProducesResponseType(typeof(UserDto), 201)]
[ProducesResponseType(400)]
[ProducesResponseType(409)]
public async Task<ActionResult<UserDto>> CreateUser([FromBody] CreateUserRequest req) { … }
```

XML comments on DTO classes also populate the Swagger schema — property descriptions appear in the model documentation panel:

```csharp
public class CreateUserRequest
{
    /// <summary>The user's display name. Must be 2–100 characters.</summary>
    [Required, StringLength(100, MinimumLength = 2)]
    public string Name { get; set; }

    /// <summary>A valid email address. Must be unique across all users.</summary>
    [Required, EmailAddress]
    public string Email { get; set; }
}
```

---

## Documenting JWT authentication in Swagger UI

By default the Swagger UI has no way to send an `Authorization: Bearer` header — every "Try it out" request goes unauthenticated. To add an "Authorize" button that lets you paste a token:

```csharp
builder.Services.AddSwaggerGen(o =>
{
    // Define the security scheme:
    o.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Name         = "Authorization",
        Type         = SecuritySchemeType.Http,
        Scheme       = "bearer",
        BearerFormat = "JWT",
        In           = ParameterLocation.Header,
        Description  = "Paste your JWT token. The 'Bearer ' prefix is added automatically."
    });

    // Apply it to all operations — or use [Authorize] filtering for selective application:
    o.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme
            {
                Reference = new OpenApiReference
                {
                    Type = ReferenceType.SecurityScheme,
                    Id   = "Bearer"
                }
            },
            Array.Empty<string>()
        }
    });

    // XML comments:
    var xmlFile = $"{Assembly.GetExecutingAssembly().GetName().Name}.xml";
    o.IncludeXmlComments(Path.Combine(AppContext.BaseDirectory, xmlFile));
});
```

After this, the Swagger UI shows an "Authorize" button. Clicking it opens a dialog where you paste the JWT. All subsequent "Try it out" requests include `Authorization: Bearer <token>`.

---

## What breaks

**Swagger exposed in production**
The spec describes every endpoint, every parameter name and type, every response shape, every security requirement. An attacker with the spec can enumerate every route and understand exactly what inputs each accepts. Always gate on `IsDevelopment()`.

**`[ProducesResponseType]` omitted**
Swagger documents every action as returning `200` with an unknown body. The spec is technically valid but useless for clients generating API consumers or for testing. Add `[ProducesResponseType]` to every action that has a documented contract.

**XML doc file not found at runtime**
`IncludeXmlComments` throws `FileNotFoundException` if the XML file path is wrong. Use `AppContext.BaseDirectory` (the output directory) rather than a project-relative path — the XML file is copied to the output directory alongside the assembly. In Docker images, verify the XML file is present in the published output: `dotnet publish` copies it by default when `GenerateDocumentationFile` is set.

**Newtonsoft.Json naming strategies not reflected in Swagger**
If the serialiser produces different property names than the C# class names (e.g. via `NamingPolicy` or `[JsonProperty]`), Swagger reads the C# class and shows the wrong names unless the Swagger configuration mirrors the serialiser settings. Use `builder.Services.AddSwaggerGen(o => o.UseAllOfToExtendReferenceSchemas())` and ensure your Swagger setup matches your serialiser setup.
