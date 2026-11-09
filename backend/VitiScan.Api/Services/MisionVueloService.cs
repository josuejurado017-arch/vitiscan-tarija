using Microsoft.EntityFrameworkCore;
using VitiScan.Api.Data;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public class MisionVueloService : IMisionVueloService
{
    private readonly AppDbContext _context;

    public MisionVueloService(AppDbContext context)
    {
        _context = context;
    }

    public async Task<IEnumerable<MisionVuelo>> ObtenerTodasAsync()
    {
        return await _context.MisionesVuelo
            .Include(m => m.Parcela)
            .Include(m => m.Detecciones)
            .OrderByDescending(m => m.FechaHora)
            .AsNoTracking()
            .ToListAsync();
    }

    public async Task<MisionVuelo?> ObtenerPorIdAsync(int id)
    {
        return await _context.MisionesVuelo
            .Include(m => m.Parcela)
            .Include(m => m.Detecciones)
            .FirstOrDefaultAsync(m => m.Id == id);
    }

    public async Task<MisionVuelo> CrearAsync(MisionVuelo mision)
    {
        mision.FechaHora = DateTime.UtcNow;
        _context.MisionesVuelo.Add(mision);
        await _context.SaveChangesAsync();
        return mision;
    }

    public async Task<bool> CambiarEstadoAsync(int id, EstadoMision nuevoEstado)
    {
        var mision = await _context.MisionesVuelo.FindAsync(id);
        if (mision == null) return false;

        mision.Estado = nuevoEstado;
        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<bool> EliminarAsync(int id)
    {
        var mision = await _context.MisionesVuelo.FindAsync(id);
        if (mision == null) return false;

        _context.MisionesVuelo.Remove(mision);
        await _context.SaveChangesAsync();
        return true;
    }
}
