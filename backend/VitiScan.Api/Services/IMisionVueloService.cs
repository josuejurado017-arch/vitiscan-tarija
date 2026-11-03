using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public interface IMisionVueloService
{
    Task<IEnumerable<MisionVuelo>> ObtenerTodasAsync();
    Task<MisionVuelo?> ObtenerPorIdAsync(int id);
    Task<MisionVuelo> CrearAsync(MisionVuelo mision);
    Task<bool> CambiarEstadoAsync(int id, EstadoMision nuevoEstado);
    Task<bool> EliminarAsync(int id);
}
