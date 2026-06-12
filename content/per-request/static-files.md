## StaticFiles

Checks whether the URL matches a file in `wwwroot/`. A request to `GET /images/logo.png` is served directly from disk — nothing below runs, no auth, no routing.

If the URL does not match any file, the request passes through unchanged.

**Position matters:** declared before `UseAuthentication` so static files are served without going through auth. Moving it after auth means every file request requires a valid token.

### Content root vs web root

Two directories matter for file serving:

**Content root** (`builder.Environment.ContentRootPath`) — the base directory of the application itself. This is where the project lives: `appsettings.json`, compiled assemblies, and any other app files. Defaults to the directory containing the app's executable. Used when you need to read files that belong to the app but are not publicly served.

**Web root** (`builder.Environment.WebRootPath`) — the subdirectory that `UseStaticFiles` serves publicly. Defaults to `wwwroot/` inside the content root. Only files inside the web root are accessible to clients. Files in the content root but outside the web root — configuration files, source files, private assets — are never served.

```
MyApp/
  appsettings.json          ← content root — not served
  MyApp.dll                 ← content root — not served
  wwwroot/                  ← web root — served by UseStaticFiles
    css/
      site.css              ← GET /css/site.css
    images/
      logo.png              ← GET /images/logo.png
```

```csharp
// Program.cs:
app.UseStaticFiles();  // serves files from wwwroot/ — default web root

// Custom root — serve from a different directory:
app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(
        Path.Combine(builder.Environment.ContentRootPath, "assets")),
    RequestPath = "/assets"  // GET /assets/logo.png → reads from ./assets/logo.png
});
```

The default root is `wwwroot/` relative to the content root. Files outside `wwwroot/` are not served unless explicitly configured — a request for a path that resolves outside the file provider root returns 404, not the file.
