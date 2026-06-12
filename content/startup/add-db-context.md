## AddDbContext

Registers the Entity Framework Core database context. Always Scoped — one instance per request, holding a single database connection and tracking changes for that request's unit of work.

```csharp
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("Default")));
```

**Never register as Singleton.** A Singleton `DbContext`:
- Holds one connection shared across all concurrent requests — database connections are not thread-safe
- Accumulates tracked entities across requests — the change tracker grows unboundedly and corrupts state
- Will throw `InvalidOperationException` under concurrent access

**Connection string from configuration:**

```json
// appsettings.json
{
  "ConnectionStrings": {
    "Default": "Server=.;Database=MyApp;Trusted_Connection=true;TrustServerCertificate=true;"
  }
}
```

```csharp
// appsettings.Development.json — overrides for local development
{
  "ConnectionStrings": {
    "Default": "Server=localhost,1433;Database=MyApp;User=sa;Password=YourPassword;"
  }
}
```

**The DbContext class:**

```csharp
public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User>    Users    { get; set; }
    public DbSet<Product> Products { get; set; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<User>()
            .HasIndex(u => u.Email)
            .IsUnique();
    }
}
```

**Using in a controller:**

```csharp
public class UsersController : ControllerBase
{
    private readonly AppDbContext _db;

    public UsersController(AppDbContext db)
    {
        _db = db;
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<UserDto>> GetUser(int id)
    {
        var user = await _db.Users
            .AsNoTracking()          // read-only query — skips change tracking overhead
            .FirstOrDefaultAsync(u => u.Id == id);

        if (user is null) return NotFound();
        return Ok(new UserDto { Id = user.Id, Name = user.Name });
    }
}
```

This example accesses `DbContext` directly from the controller to show the EF Core API clearly. In a real application, database access belongs in a repository or service class, not the controller. The controller should depend on an interface (`IUserRepository`, `IUserService`) and know nothing about how data is stored:

```csharp
// In production code — controller depends on an interface, not the DbContext:
public class UsersController : ControllerBase
{
    private readonly IUserRepository _users;
    public UsersController(IUserRepository users) => _users = users;

    [HttpGet("{id}")]
    public async Task<ActionResult<UserDto>> GetUser(int id)
    {
        var user = await _users.GetByIdAsync(id);
        if (user is null) return NotFound();
        return Ok(new UserDto { Id = user.Id, Name = user.Name });
    }
}

// The repository implementation owns the DbContext:
public class SqlUserRepository : IUserRepository
{
    private readonly AppDbContext _db;
    public SqlUserRepository(AppDbContext db) => _db = db;

    public Task<User?> GetByIdAsync(int id) =>
        _db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == id);
}
```

Keeping the controller ignorant of EF Core means the database access can be changed, tested with a fake implementation, or replaced entirely without touching the controller.

**Connection resiliency — retry on transient failure:**

```csharp
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlServer(
        builder.Configuration.GetConnectionString("Default"),
        sql => sql.EnableRetryOnFailure(
            maxRetryCount: 3,
            maxRetryDelay: TimeSpan.FromSeconds(5),
            errorNumbersToAdd: null)));
```

**Multiple DbContexts:**

Register each separately. Each gets its own connection and change tracker:

```csharp
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("App")));

builder.Services.AddDbContext<LoggingDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("Logging")));
```

**Pooling — for high-throughput APIs:**

Instead of creating a new `DbContext` per request, pooling resets and reuses instances:

```csharp
builder.Services.AddDbContextPool<AppDbContext>(o =>
    o.UseSqlServer(builder.Configuration.GetConnectionString("Default")));
```

Pooled contexts cannot have constructor parameters beyond `DbContextOptions`. Do not use pooling if your `DbContext` stores any per-request state.
