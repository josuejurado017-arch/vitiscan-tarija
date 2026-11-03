using VitiScan.Api.DTOs;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public interface IOrdenRiegoService
{
    Task<IEnumerable<OrdenRiego>> ObtenerTodasAsync();
    Task<OrdenRiego?> ObtenerPorIdAsync(int id);
    Task<OrdenRiego> CrearAsync(OrdenRiego orden);

    /// <summary>
    /// Evalúa el resultado de /analyze-ai. Si arroja 'Estrés Hídrico Severo' con confianza > 80%,
    /// crea automáticamente la orden con estado PendienteAprobacion.
    /// </summary>
    Task<OrdenRiego?> ProcesarDeteccionIaAsync(DeteccionAiResultDto dto);

    /// <summary>
    /// Aprobación manual del supervisor/enólogo (Human-in-the-loop), emisión MQTT y firma de auditoría.
    /// </summary>
    Task<AuditoriaRiegoResponse?> AprobarOrdenPorSupervisorAsync(int id, AprobarRiegoRequest request);

    Task<bool> AprobarOrdenAsync(int id);
    Task<bool> EjecutarOrdenAsync(int id);
    Task<bool> EliminarAsync(int id);
}
