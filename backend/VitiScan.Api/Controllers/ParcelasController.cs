using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.Models;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ParcelasController : ControllerBase
{
    private readonly IParcelaService _parcelaService;

    public ParcelasController(IParcelaService parcelaService)
    {
        _parcelaService = parcelaService;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<Parcela>>> GetAll()
    {
        var parcelas = await _parcelaService.ObtenerTodasAsync();
        return Ok(parcelas);
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<Parcela>> GetById(int id)
    {
        var parcela = await _parcelaService.ObtenerPorIdAsync(id);
        if (parcela == null) return NotFound(new { message = $"Parcela con id {id} no encontrada." });
        return Ok(parcela);
    }

    [HttpPost]
    public async Task<ActionResult<Parcela>> Create([FromBody] Parcela parcela)
    {
        var creada = await _parcelaService.CrearAsync(parcela);
        return CreatedAtAction(nameof(GetById), new { id = creada.Id }, creada);
    }

    [HttpPut("{id:int}")]
    public async Task<IActionResult> Update(int id, [FromBody] Parcela parcela)
    {
        var actualizado = await _parcelaService.ActualizarAsync(id, parcela);
        if (!actualizado) return NotFound(new { message = $"Parcela con id {id} no encontrada." });
        return NoContent();
    }

    [HttpDelete("{id:int}")]
    public async Task<IActionResult> Delete(int id)
    {
        var eliminado = await _parcelaService.EliminarAsync(id);
        if (!eliminado) return NotFound(new { message = $"Parcela con id {id} no encontrada." });
        return NoContent();
    }
}
