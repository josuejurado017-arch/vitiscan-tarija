using Microsoft.EntityFrameworkCore;
using VitiScan.Api.Data;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public class ParcelaService : IParcelaService
{
    private readonly AppDbContext _context;

    public ParcelaService(AppDbContext context)
    {
        _context = context;
    }

    public async Task<IEnumerable<Parcela>> ObtenerTodasAsync()
    {
        return await _context.Parcelas
            .AsNoTracking()
            .ToListAsync();
    }

    public async Task<Parcela?> ObtenerPorIdAsync(int id)
    {
        return await _context.Parcelas
            .Include(p => p.MisionesVuelo)
            .Include(p => p.OrdenesRiego)
            .FirstOrDefaultAsync(p => p.Id == id);
    }

    public async Task<Parcela> CrearAsync(Parcela parcela)
    {
        _context.Parcelas.Add(parcela);
        await _context.SaveChangesAsync();
        return parcela;
    }

    public async Task<bool> ActualizarAsync(int id, Parcela parcela)
    {
        var existente = await _context.Parcelas.FindAsync(id);
        if (existente == null) return false;

        existente.Nombre = parcela.Nombre;
        existente.Subcentral = parcela.Subcentral;
        existente.CoordenadasGeoJson = parcela.CoordenadasGeoJson;
        existente.EstadoSalud = parcela.EstadoSalud;

        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<bool> EliminarAsync(int id)
    {
        var existente = await _context.Parcelas.FindAsync(id);
        if (existente == null) return false;

        _context.Parcelas.Remove(existente);
        await _context.SaveChangesAsync();
        return true;
    }
}
