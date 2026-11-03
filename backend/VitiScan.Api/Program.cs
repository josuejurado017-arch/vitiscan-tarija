using System.Text.Json.Serialization;
using Microsoft.EntityFrameworkCore;
using Microsoft.OpenApi.Models;
using VitiScan.Api.Data;
using VitiScan.Api.Services;

var builder = WebApplication.CreateBuilder(args);

// 1. Base de Datos PostgreSQL
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? "Host=localhost;Port=5432;Database=vitiscan_db;Username=postgres;Password=cisco";

builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(connectionString));

// 2. Inyección de Dependencias (Servicios de Negocio y Motor ONNX Runtime)
builder.Services.AddScoped<IParcelaService, ParcelaService>();
builder.Services.AddScoped<IMisionVueloService, MisionVueloService>();
builder.Services.AddScoped<IDeteccionService, DeteccionService>();
builder.Services.AddScoped<IOrdenRiegoService, OrdenRiegoService>();
builder.Services.AddScoped<IIrrigationMqttDispatcher, IrrigationMqttDispatcher>();
builder.Services.AddSingleton<IAiInferenceService, AiInferenceService>();

// 3. Controladores y Serialización JSON con Enums legibles
builder.Services.AddControllers()
    .AddJsonOptions(options =>
    {
        options.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter());
        options.JsonSerializerOptions.ReferenceHandler = ReferenceHandler.IgnoreCycles;
    });

// 4. Configuración CORS para desarrollo
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowFrontend", policy =>
    {
        policy.WithOrigins("http://localhost:4200", "http://localhost:5000", "http://localhost:5180")
              .AllowAnyHeader()
              .AllowAnyMethod();
    });
});

// 5. Swagger / OpenAPI disponible en /swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo
    {
        Title = "VitiScan Tarija API",
        Version = "v1",
        Description = "API REST monolítica de monitoreo vitivinícola, motor ONNX Runtime nativo y control de riego."
    });
});

var app = builder.Build();

// 6. Migración y Semilla Automática en Base de Datos
using (var scope = app.Services.CreateScope())
{
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    try
    {
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        db.Database.EnsureCreated();
        logger.LogInformation("Base de datos y tablas de VitiScan Tarija verificadas con éxito.");
    }
    catch (Exception ex)
    {
        logger.LogWarning("Verificación de base de datos PostgreSQL: {Message}", ex.Message);
    }
}

// 7. Middlewares de Archivos Estáticos y SPA Fallback (Monolito Consolidado)
app.UseDefaultFiles();
app.UseStaticFiles();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI(c =>
    {
        c.SwaggerEndpoint("/swagger/v1/swagger.json", "VitiScan Tarija API v1");
        c.RoutePrefix = "swagger"; // Swagger en http://localhost:5000/swagger
    });
}

app.UseCors("AllowFrontend");

app.UseAuthorization();

// 8. Enrutamiento de API y Redirección a Angular (Soporte F5 y rutas directas)
app.MapControllers();
app.MapFallbackToFile("index.html");

app.Run();
