using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.Models;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class OrdenesRiegoController : ControllerBase
{
    private readonly IOrdenRiegoService _ordenRiegoService;

    public OrdenesRiegoController(IOrdenRiegoService ordenRiegoService)
    {
        _ordenRiegoService = ordenRiegoService;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<OrdenRiego>>> GetAll()
    {
        var ordenes = await _ordenRiegoService.ObtenerTodasAsync();
        return Ok(ordenes);
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<OrdenRiego>> GetById(int id)
    {
        var orden = await _ordenRiegoService.ObtenerPorIdAsync(id);
        if (orden == null) return NotFound(new { message = $"Orden de riego con id {id} no encontrada." });
        return Ok(orden);
    }

    [HttpPost]
    public async Task<ActionResult<OrdenRiego>> Create([FromBody] OrdenRiego orden)
    {
        var creada = await _ordenRiegoService.CrearAsync(orden);
        return CreatedAtAction(nameof(GetById), new { id = creada.Id }, creada);
    }

    [HttpPatch("{id:int}/aprobar")]
    public async Task<IActionResult> Aprobar(int id)
    {
        var aprobado = await _ordenRiegoService.AprobarOrdenAsync(id);
        if (!aprobado) return NotFound(new { message = $"Orden de riego con id {id} no encontrada." });
        return Ok(new { message = "Orden de riego aprobada por humano con éxito." });
    }

    [HttpPatch("{id:int}/ejecutar")]
    public async Task<IActionResult> Ejecutar(int id)
    {
        var ejecutado = await _ordenRiegoService.EjecutarOrdenAsync(id);
        if (!ejecutado)
            return BadRequest(new { message = $"No se pudo ejecutar la orden {id}. Verifique que exista y esté aprobada por un humano." });
        return Ok(new { message = "Orden de riego ejecutada con éxito." });
    }
}
