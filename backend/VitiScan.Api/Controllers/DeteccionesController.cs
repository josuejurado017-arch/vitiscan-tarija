using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.Models;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class DeteccionesController : ControllerBase
{
    private readonly IDeteccionService _deteccionService;

    public DeteccionesController(IDeteccionService deteccionService)
    {
        _deteccionService = deteccionService;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<Deteccion>>> GetAll([FromQuery] int? misionVueloId)
    {
        if (misionVueloId.HasValue)
        {
            var filtradas = await _deteccionService.ObtenerPorMisionAsync(misionVueloId.Value);
            return Ok(filtradas);
        }

        var todas = await _deteccionService.ObtenerTodasAsync();
        return Ok(todas);
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<Deteccion>> GetById(int id)
    {
        var deteccion = await _deteccionService.ObtenerPorIdAsync(id);
        if (deteccion == null) return NotFound(new { message = $"Detección con id {id} no encontrada." });
        return Ok(deteccion);
    }

    [HttpPost]
    public async Task<ActionResult<Deteccion>> Create([FromBody] Deteccion deteccion)
    {
        var creada = await _deteccionService.RegistrarDeteccionAsync(deteccion);
        return CreatedAtAction(nameof(GetById), new { id = creada.Id }, creada);
    }
}
