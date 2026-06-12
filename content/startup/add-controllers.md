## AddControllers

Registers the entire MVC stack in one call. Nothing is constructed here — the container stores the recipes. At request time these are constructed and used.

```csharp
builder.Services.AddControllers();
```

**What it registers:**

- **Routing system** — matches incoming URLs to controller actions. At startup, `MapControllers()` scans every controller and builds the routing table. At request time, `UseRouting()` runs that table against each incoming URL.
- **Model binder** — extracts values from the request (route segments, query string, JSON body, headers, form fields) and maps them onto action parameters. Runs after filters, before your action method.
- **Action invoker** — calls your method with the bound parameters and captures the return value.
- **Filter pipeline** — authorization filters, resource filters, action filters, exception filters, result filters. Each type runs at a specific point around the action.
- **JSON serialiser** — `System.Text.Json` by default. Converts your C# return value to bytes on the way out, and deserialises JSON bodies on the way in.
- **`[ApiController]` behaviours** — automatic 400 response when model validation fails (before your action runs), and automatic inference of binding sources so you rarely need `[FromBody]` / `[FromRoute]` explicitly.

**Variants:**

```csharp
// API controllers only (no Razor views):
builder.Services.AddControllers();

// API controllers + Razor views:
builder.Services.AddControllersWithViews();

// Razor Pages only:
builder.Services.AddRazorPages();

// Everything:
builder.Services.AddMvc();
```

For a JSON API, `AddControllers()` is the right choice — it does not include the view engine overhead.

**JSON options — configure before `builder.Build()`:**

```csharp
builder.Services.AddControllers()
    .AddJsonOptions(o => {
        // property names as camelCase in JSON: "userId" not "UserId"
        o.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;

        // omit null properties from the response entirely
        o.JsonSerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;

        // allow trailing commas and // comments in incoming JSON
        o.JsonSerializerOptions.ReadCommentHandling = JsonCommentHandling.Skip;
        o.JsonSerializerOptions.AllowTrailingCommas = true;
    });
```

**Switching to Newtonsoft.Json:**

`System.Text.Json` is the default since .NET Core 3.0. If you need Newtonsoft (for more advanced serialisation scenarios), install `Microsoft.AspNetCore.Mvc.NewtonsoftJson` and replace:

```csharp
builder.Services.AddControllers()
    .AddNewtonsoftJson(o => {
        o.SerializerSettings.ContractResolver = new CamelCasePropertyNamesContractResolver();
        o.SerializerSettings.NullValueHandling = NullValueHandling.Ignore;
    });
```

Using both in the same project causes conflicts — pick one.

**Adding XML support:**

By default only JSON is supported. To also accept and return XML:

```csharp
builder.Services.AddControllers()
    .AddXmlSerializerFormatters();
```

Clients then send `Accept: application/xml` to request XML, or `Content-Type: application/xml` to send XML bodies.
