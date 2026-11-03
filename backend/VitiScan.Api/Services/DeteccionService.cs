using Microsoft.EntityFrameworkCore;
using VitiScan.Api.Data;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public class DeteccionService : IDeteccionService
{
    private readonly AppDbContext _context;

    public DeteccionService(AppDbContext context)
    {
        _context = context;
    }

    public async Task<IEnumerable<Deteccion>> ObtenerPorMisionAsync(int misionVueloId)
    {
        return await _context.Detecciones
            .Where(d => d.MisionVueloId == misionVueloId)
            .AsNoTracking()
            .ToListAsync();
    }

    public async Task<IEnumerable<Deteccion>> ObtenerTodasAsync()
    {
        return await _context.Detecciones
            .AsNoTracking()
            .ToListAsync();
    }

    public async Task<Deteccion?> ObtenerPorIdAsync(int id)
    {
        return await _context.Detecciones.FindAsync(id);
    }

    public async Task<Deteccion> RegistrarDeteccionAsync(Deteccion deteccion)
    {
        _context.Detecciones.Add(deteccion);
        await _context.SaveChangesAsync();
        return deteccion;
    }
}
