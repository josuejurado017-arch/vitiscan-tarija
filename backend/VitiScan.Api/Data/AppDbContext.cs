using Microsoft.EntityFrameworkCore;
using VitiScan.Api.Models;

namespace VitiScan.Api.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options)
    {
    }

    public DbSet<Parcela> Parcelas => Set<Parcela>();
    public DbSet<MisionVuelo> MisionesVuelo => Set<MisionVuelo>();
    public DbSet<Deteccion> Detecciones => Set<Deteccion>();
    public DbSet<OrdenRiego> OrdenesRiego => Set<OrdenRiego>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Conversión de Enums a string para mayor legibilidad y consistencia en BD
        modelBuilder.Entity<MisionVuelo>()
            .Property(m => m.Estado)
            .HasConversion<string>();

        modelBuilder.Entity<Deteccion>()
            .Property(d => d.TipoProblema)
            .HasConversion<string>();

        modelBuilder.Entity<OrdenRiego>()
            .Property(o => o.Estado)
            .HasConversion<string>();

        // Relaciones
        modelBuilder.Entity<MisionVuelo>()
            .HasOne(m => m.Parcela)
            .WithMany(p => p.MisionesVuelo)
            .HasForeignKey(m => m.ParcelaId)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<Deteccion>()
            .HasOne(d => d.MisionVuelo)
            .WithMany(m => m.Detecciones)
            .HasForeignKey(d => d.MisionVueloId)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<OrdenRiego>()
            .HasOne(o => o.Parcela)
            .WithMany(p => p.OrdenesRiego)
            .HasForeignKey(o => o.ParcelaId)
            .OnDelete(DeleteBehavior.Cascade);

        // Semilla de datos iniciales para el Valle de Tarija (Hackathon Seed)
        modelBuilder.Entity<Parcela>().HasData(
            new Parcela
            {
                Id = 1,
                Nombre = "Viñedo Los Parrales - Cuadro Norte",
                Subcentral = "Tolomosa",
                CoordenadasGeoJson = "{\"type\":\"Polygon\",\"coordinates\":[[[-64.750, -21.570],[-64.745, -21.570],[-64.745, -21.575],[-64.750, -21.575],[-64.750, -21.570]]]}",
                EstadoSalud = "Regular"
            },
            new Parcela
            {
                Id = 2,
                Nombre = "Finca San Roque - Syrah",
                Subcentral = "Lazaretto",
                CoordenadasGeoJson = "{\"type\":\"Polygon\",\"coordinates\":[[[-64.760, -21.580],[-64.755, -21.580],[-64.755, -21.585],[-64.760, -21.585],[-64.760, -21.580]]]}",
                EstadoSalud = "Critico"
            },
            new Parcela
            {
                Id = 3,
                Nombre = "Bodega Campos de Solana - Tannat",
                Subcentral = "Uriondo",
                CoordenadasGeoJson = "{\"type\":\"Polygon\",\"coordinates\":[[[-64.690, -21.690],[-64.685, -21.690],[-64.685, -21.695],[-64.690, -21.695],[-64.690, -21.690]]]}",
                EstadoSalud = "Optimo"
            }
        );

        modelBuilder.Entity<MisionVuelo>().HasData(
            new MisionVuelo
            {
                Id = 1,
                ParcelaId = 1,
                FechaHora = new DateTime(2026, 11, 2, 9, 30, 0, DateTimeKind.Utc),
                Estado = EstadoMision.Completada
            },
            new MisionVuelo
            {
                Id = 2,
                ParcelaId = 2,
                FechaHora = new DateTime(2026, 11, 2, 14, 0, 0, DateTimeKind.Utc),
                Estado = EstadoMision.Procesando
            }
        );

        modelBuilder.Entity<Deteccion>().HasData(
            new Deteccion
            {
                Id = 1,
                MisionVueloId = 1,
                CoordenadasPunto = "-21.5721,-64.7478",
                TipoProblema = TipoProblema.EstresHidrico,
                Severidad = 78,
                Confianza = 0.94,
                ImagenUrl = "https://images.unsplash.com/photo-1506619216599-9d16d0903dfd?auto=format&fit=crop&w=600&q=80"
            },
            new Deteccion
            {
                Id = 2,
                MisionVueloId = 1,
                CoordenadasPunto = "-21.5735,-64.7469",
                TipoProblema = TipoProblema.LobesiaBotrana,
                Severidad = 65,
                Confianza = 0.88,
                ImagenUrl = "https://images.unsplash.com/photo-1510812431401-41d2bd2722f3?auto=format&fit=crop&w=600&q=80"
            }
        );

        modelBuilder.Entity<OrdenRiego>().HasData(
            new OrdenRiego
            {
                Id = 1,
                ParcelaId = 1,
                SectorValvula = "Sector B-Sector 03",
                DuracionMinutos = 45,
                Estado = EstadoOrdenRiego.PendienteAprobacion,
                AprobadoPorHumano = false
            }
        );
    }
}
