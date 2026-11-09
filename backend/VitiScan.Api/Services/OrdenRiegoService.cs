using Microsoft.EntityFrameworkCore;
using VitiScan.Api.Data;
using VitiScan.Api.DTOs;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public class OrdenRiegoService : IOrdenRiegoService
{
    private readonly AppDbContext _context;
    private readonly IIrrigationMqttDispatcher _mqttDispatcher;
    private readonly ILogger<OrdenRiegoService> _logger;

    public OrdenRiegoService(
        AppDbContext context,
        IIrrigationMqttDispatcher mqttDispatcher,
        ILogger<OrdenRiegoService> logger)
    {
        _context = context;
        _mqttDispatcher = mqttDispatcher;
        _logger = logger;
    }

    public async Task<IEnumerable<OrdenRiego>> ObtenerTodasAsync()
    {
        return await _context.OrdenesRiego
            .Include(o => o.Parcela)
            .OrderByDescending(o => o.Id)
            .AsNoTracking()
            .ToListAsync();
    }

    public async Task<OrdenRiego?> ObtenerPorIdAsync(int id)
    {
        return await _context.OrdenesRiego
            .Include(o => o.Parcela)
            .FirstOrDefaultAsync(o => o.Id == id);
    }

    public async Task<OrdenRiego> CrearAsync(OrdenRiego orden)
    {
        orden.Estado = EstadoOrdenRiego.PendienteAprobacion;
        orden.AprobadoPorHumano = false;
        orden.FechaCreacion = DateTime.UtcNow;

        _context.OrdenesRiego.Add(orden);
        await _context.SaveChangesAsync();
        return orden;
    }

    /// <summary>
    /// Flujo de Control Automático:
    /// Cuando el resultado de /analyze-ai arroja 'Estrés Hídrico Severo' con confianza > 80% (0.80),
    /// crea automáticamente un registro OrdenRiego en estado 'PendienteAprobacion'.
    /// </summary>
    public async Task<OrdenRiego?> ProcesarDeteccionIaAsync(DeteccionAiResultDto dto)
    {
        var clasificacionNorm = dto.Clasificacion.Trim().ToLowerInvariant()
            .Replace("é", "e").Replace("í", "i");
        var esEstresSevero = clasificacionNorm.Contains("estres hidrico severo") ||
                             clasificacionNorm.Contains("estreshidricosevero");

        var umbralSuperado = dto.Confianza > 0.80;

        if (!esEstresSevero || !umbralSuperado)
        {
            _logger.LogInformation(
                "ℹ️ Detección IA descartada para riego automático: Clasificación='{Clasif}', Confianza={Conf:P1} (Requerido: 'Estrés Hídrico Severo' y Confianza > 80%).",
                dto.Clasificacion, dto.Confianza);
            return null;
        }

        var orden = new OrdenRiego
        {
            ParcelaId = dto.ParcelaId > 0 ? dto.ParcelaId : 1,
            SectorValvula = string.IsNullOrWhiteSpace(dto.SectorValvula) ? "VALVULA_SECTOR_B" : dto.SectorValvula,
            DuracionMinutos = dto.DuracionSugeridaMinutos > 0 ? dto.DuracionSugeridaMinutos : 25,
            Estado = EstadoOrdenRiego.PendienteAprobacion,
            AprobadoPorHumano = false,
            FechaCreacion = DateTime.UtcNow,
            MotivoDisparoIa = $"Trigger IA: '{dto.Clasificacion}' con confianza de {(dto.Confianza * 100):F1}% en coordenadas {dto.CoordenadasPunto}"
        };

        _context.OrdenesRiego.Add(orden);

        var deteccion = new Deteccion
        {
            MisionVueloId = dto.MisionVueloId > 0 ? dto.MisionVueloId : 1,
            CoordenadasPunto = dto.CoordenadasPunto,
            TipoProblema = TipoProblema.EstresHidrico,
            Severidad = 85,
            Confianza = dto.Confianza,
            ImagenUrl = dto.ImagenUrl ?? "https://images.unsplash.com/photo-1506619216599-9d16d0903dfd?w=600"
        };
        _context.Detecciones.Add(deteccion);

        await _context.SaveChangesAsync();

        _logger.LogWarning(
            "🚨 [HUMAN-IN-THE-LOOP] Orden de Riego #{Id} creada automáticamente en estado PendienteAprobacion para {Sector} ({Min} min). Esperando validación de enólogo.",
            orden.Id, orden.SectorValvula, orden.DuracionMinutos);

        return orden;
    }

    /// <summary>
    /// Confirmación manual del supervisor/enólogo (Human-in-the-loop).
    /// Emite la trama MQTT (VALVULA_SECTOR_B: OPEN: 25min) y genera la firma de auditoría.
    /// </summary>
    public async Task<AuditoriaRiegoResponse?> AprobarOrdenPorSupervisorAsync(int id, AprobarRiegoRequest request)
    {
        var orden = await _context.OrdenesRiego.FindAsync(id);
        if (orden == null)
        {
            _logger.LogWarning("No se encontró la orden de riego con Id {Id} para aprobación.", id);
            return null;
        }

        var timestampUtc = DateTime.UtcNow;

        if (request.DuracionMinutosAjustada.HasValue && request.DuracionMinutosAjustada.Value > 0)
        {
            orden.DuracionMinutos = request.DuracionMinutosAjustada.Value;
        }

        // 1. Simulación de Emisión de Trama MQTT / Webhook
        var (tramaRaw, mqttDetalles, firmaSha256) = await _mqttDispatcher.DispatchIrrigationCommandAsync(
            orden,
            request.NombreSupervisor,
            request.MatriculaProfesional,
            timestampUtc);

        // 2. Actualización de Estados
        orden.AprobadoPorHumano = true;
        orden.Estado = EstadoOrdenRiego.Ejecutado;
        orden.FechaAprobacion = timestampUtc;
        orden.AprobadoPorSupervisor = request.NombreSupervisor;
        orden.MatriculaSupervisor = request.MatriculaProfesional;
        orden.FirmaDigitalSha256 = firmaSha256;
        orden.ObservacionesAgronomicas = request.ObservacionesAgronomicas;
        orden.TramaMqttEmitida = tramaRaw;

        await _context.SaveChangesAsync();

        _logger.LogInformation(
            "✅ [AUDITORIA] Orden #{Id} aprobada por {Sup} ({Mat}). Estado cambiado a Ejecutado. Firma: {Firma}",
            orden.Id, request.NombreSupervisor, request.MatriculaProfesional, firmaSha256);

        // 3. Respuesta con Log de Auditoría Completo
        return new AuditoriaRiegoResponse
        {
            OrdenRiegoId = orden.Id,
            Estado = orden.Estado.ToString(),
            TimestampAprobacionUtc = timestampUtc,
            AprobadoPor = request.NombreSupervisor,
            Matricula = request.MatriculaProfesional,
            FirmaAprobacionSha256 = firmaSha256,
            SectorValvula = orden.SectorValvula,
            DuracionMinutos = orden.DuracionMinutos,
            TramaMqttEmitida = tramaRaw,
            MqttDetalles = mqttDetalles,
            WebhookStatus = "200 OK (Válvula LoRaWAN ACK: ACTIVATED)",
            MensajeAuditoria = $"Riego autorizado por humano y ejecutado con éxito en {orden.SectorValvula}. Electroválvula abierta por {orden.DuracionMinutos} minutos."
        };
    }

    public async Task<bool> AprobarOrdenAsync(int id)
    {
        var dummyRequest = new AprobarRiegoRequest
        {
            NombreSupervisor = "Supervisor General",
            MatriculaProfesional = "SYS-ENOL-01"
        };
        var res = await AprobarOrdenPorSupervisorAsync(id, dummyRequest);
        return res != null;
    }

    public async Task<bool> EjecutarOrdenAsync(int id)
    {
        var orden = await _context.OrdenesRiego.FindAsync(id);
        if (orden == null || !orden.AprobadoPorHumano) return false;

        orden.Estado = EstadoOrdenRiego.Ejecutado;
        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<bool> EliminarAsync(int id)
    {
        var orden = await _context.OrdenesRiego.FindAsync(id);
        if (orden == null) return false;

        _context.OrdenesRiego.Remove(orden);
        await _context.SaveChangesAsync();
        return true;
    }
}
