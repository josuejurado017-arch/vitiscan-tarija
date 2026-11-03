using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.Models;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class MisionesVueloController : ControllerBase
{
    private readonly IMisionVueloService _misionService;

    public MisionesVueloController(IMisionVueloService misionService)
    {
        _misionService = misionService;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<MisionVuelo>>> GetAll()
    {
        var misiones = await _misionService.ObtenerTodasAsync();
        return Ok(misiones);
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<MisionVuelo>> GetById(int id)
    {
        var mision = await _misionService.ObtenerPorIdAsync(id);
        if (mision == null) return NotFound(new { message = $"Misión con id {id} no encontrada." });
        return Ok(mision);
    }

    [HttpPost]
    public async Task<ActionResult<MisionVuelo>> Create([FromBody] MisionVuelo mision)
    {
        var creada = await _misionService.CrearAsync(mision);
        return CreatedAtAction(nameof(GetById), new { id = creada.Id }, creada);
    }

    [HttpPatch("{id:int}/estado")]
    public async Task<IActionResult> UpdateEstado(int id, [FromBody] EstadoMision nuevoEstado)
    {
        var actualizado = await _misionService.CambiarEstadoAsync(id, nuevoEstado);
        if (!actualizado) return NotFound(new { message = $"Misión con id {id} no encontrada." });
        return NoContent();
    }

    [HttpDelete("{id:int}")]
    public async Task<IActionResult> Delete(int id)
    {
        var eliminado = await _misionService.EliminarAsync(id);
        if (!eliminado) return NotFound(new { message = $"Misión con id {id} no encontrada." });
        return NoContent();
    }
}
