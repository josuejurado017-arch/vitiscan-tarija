using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public interface IDeteccionService
{
    Task<IEnumerable<Deteccion>> ObtenerPorMisionAsync(int misionVueloId);
    Task<IEnumerable<Deteccion>> ObtenerTodasAsync();
    Task<Deteccion?> ObtenerPorIdAsync(int id);
    Task<Deteccion> RegistrarDeteccionAsync(Deteccion deteccion);
}
