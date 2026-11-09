using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.DTOs;
using VitiScan.Api.Models;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class RiegoController : ControllerBase
{
    private readonly IOrdenRiegoService _ordenRiegoService;
    private readonly ILogger<RiegoController> _logger;

    public RiegoController(IOrdenRiegoService ordenRiegoService, ILogger<RiegoController> logger)
    {
        _ordenRiegoService = ordenRiegoService;
        _logger = logger;
    }

    /// <summary>
    /// Endpoint 1: Procesa el resultado de /analyze-ai.
    /// Si arroja 'Estrés Hídrico Severo' con confianza > 80%, crea automáticamente una OrdenRiego en estado 'PendienteAprobacion'.
    /// </summary>
    [HttpPost("procesar-analisis-ia")]
    [ProducesResponseType(typeof(OrdenRiego), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> ProcesarAnalisisIa([FromBody] DeteccionAiResultDto dto)
    {
        if (dto == null) return BadRequest(new { message = "El payload de detección IA es requerido." });

        var ordenCreada = await _ordenRiegoService.ProcesarDeteccionIaAsync(dto);

        if (ordenCreada != null)
        {
            return CreatedAtAction(
                nameof(GetById),
                new { id = ordenCreada.Id },
                new
                {
                    mensaje = "Alerta: 'Estrés Hídrico Severo' detectado con confianza > 80%. Se creó automáticamente una OrdenRiego en estado 'PendienteAprobacion'. Requiere validación de enólogo.",
                    orden = ordenCreada
                });
        }

        return Ok(new
        {
            mensaje = "Análisis procesado. Los valores no superaron el umbral de 'Estrés Hídrico Severo' con confianza > 80%. No se requiere orden de riego automática.",
            clasificacion = dto.Clasificacion,
            confianza = dto.Confianza
        });
    }

    /// <summary>
    /// Endpoint 2: POST /api/riego/{id}/aprobar
    /// Recibe la confirmación manual de un supervisor/enólogo (cumpliendo Human-in-the-loop).
    /// Emite la trama MQTT (VALVULA_SECTOR_B: OPEN: 25min) y devuelve el log de auditoría con firma digital SHA256.
    /// </summary>
    [HttpPost("{id:int}/aprobar")]
    [ProducesResponseType(typeof(AuditoriaRiegoResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<AuditoriaRiegoResponse>> AprobarRiego(
        int id,
        [FromBody] AprobarRiegoRequest request)
    {
        if (!ModelState.IsValid)
        {
            return BadRequest(ModelState);
        }

        var auditoria = await _ordenRiegoService.AprobarOrdenPorSupervisorAsync(id, request);

        if (auditoria == null)
        {
            return NotFound(new { message = $"No se encontró la orden de riego con Id {id}." });
        }

        return Ok(auditoria);
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<OrdenRiego>> GetById(int id)
    {
        var orden = await _ordenRiegoService.ObtenerPorIdAsync(id);
        if (orden == null) return NotFound(new { message = $"Orden de riego #{id} no encontrada." });
        return Ok(orden);
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<OrdenRiego>>> GetAll()
    {
        var ordenes = await _ordenRiegoService.ObtenerTodasAsync();
        return Ok(ordenes);
    }
}
