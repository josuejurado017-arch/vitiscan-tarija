using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public interface IParcelaService
{
    Task<IEnumerable<Parcela>> ObtenerTodasAsync();
    Task<Parcela?> ObtenerPorIdAsync(int id);
    Task<Parcela> CrearAsync(Parcela parcela);
    Task<bool> ActualizarAsync(int id, Parcela parcela);
    Task<bool> EliminarAsync(int id);
}
