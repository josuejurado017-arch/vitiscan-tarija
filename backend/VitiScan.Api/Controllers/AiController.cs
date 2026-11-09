using Microsoft.AspNetCore.Mvc;
using VitiScan.Api.DTOs;
using VitiScan.Api.Services;

namespace VitiScan.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AiController : ControllerBase
{
    private readonly IAiInferenceService _aiService;
    private readonly ILogger<AiController> _logger;

    public AiController(IAiInferenceService aiService, ILogger<AiController> logger)
    {
        _aiService = aiService;
        _logger = logger;
    }

    /// <summary>
    /// Benchmark comparativo: Ejecuta simultáneamente el algoritmo tradicional GLI y la inferencia ONNX en C#
    /// sobre la imagen de prueba con sombras de Tolomosa, demostrando la superioridad de la IA.
    /// </summary>
    [HttpGet("benchmark-compare")]
    [ProducesResponseType(typeof(BenchmarkComparisonResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<BenchmarkComparisonResult>> GetBenchmarkCompare()
    {
        var result = await _aiService.RunBenchmarkAsync(null, null);
        return Ok(result);
    }

    [HttpPost("benchmark-compare")]
    [ProducesResponseType(typeof(BenchmarkComparisonResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<BenchmarkComparisonResult>> PostBenchmarkCompare([FromForm] IFormFile? file = null)
    {
        Stream? stream = null;
        string? fileName = null;

        if (file != null && file.Length > 0)
        {
            stream = file.OpenReadStream();
            fileName = file.FileName;
        }

        var result = await _aiService.RunBenchmarkAsync(stream, fileName);
        return Ok(result);
    }

    /// <summary>
    /// Inferencia nativa con modelo ONNX (ResNet/YOLOv8) en C# sin dependencias externas de Python.
    /// Clasifica entre: [Sano, Estrés Hídrico Severo, Brote Lobesia Botrana].
    /// </summary>
    [HttpGet("analyze")]
    [HttpGet("analyze-ai")]
    [ProducesResponseType(typeof(AiClassificationResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<AiClassificationResult>> GetAnalyzeAi()
    {
        return await ProcessImageAnalysis(null, null);
    }

    [HttpPost("analyze")]
    [HttpPost("analyze-ai")]
    [ProducesResponseType(typeof(AiClassificationResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<AiClassificationResult>> PostAnalyzeAi([FromForm] IFormFile? file = null)
    {
        Stream? stream = null;
        string? fileName = null;

        if (file != null && file.Length > 0)
        {
            stream = file.OpenReadStream();
            fileName = file.FileName;
        }

        return await ProcessImageAnalysis(stream, fileName);
    }

    private async Task<ActionResult<AiClassificationResult>> ProcessImageAnalysis(Stream? incomingStream, string? incomingFileName)
    {
        Stream stream;
        string fileName;

        if (incomingStream != null)
        {
            stream = incomingStream;
            fileName = incomingFileName ?? "uploaded_image.png";
        }
        else
        {
            // Imagen por defecto con clorosis/estrés
            var defaultPath = Path.Combine(AppContext.BaseDirectory, "Models", "ML", "test_images", "water_stress_vineyard.png");
            if (!System.IO.File.Exists(defaultPath))
            {
                defaultPath = Path.Combine(Directory.GetCurrentDirectory(), "Models", "ML", "test_images", "water_stress_vineyard.png");
            }

            if (System.IO.File.Exists(defaultPath))
            {
                stream = System.IO.File.OpenRead(defaultPath);
                fileName = "water_stress_vineyard.png";
            }
            else
            {
                return BadRequest(new { message = "Se requiere un archivo de imagen para el análisis." });
            }
        }

        using (stream)
        {
            var result = await _aiService.ClassifyImageAsync(stream, fileName);
            return Ok(result);
        }
    }

    /// <summary>
    /// Algoritmo tradicional de umbralización basado en Green Leaf Index sintético: (2*G - R - B) / (2*G + R + B).
    /// </summary>
    [HttpGet("analyze-traditional")]
    [ProducesResponseType(typeof(TraditionalGliResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<TraditionalGliResult>> GetAnalyzeTraditional()
    {
        return await ProcessTraditionalAnalysis(null);
    }

    [HttpPost("analyze-traditional")]
    [ProducesResponseType(typeof(TraditionalGliResult), StatusCodes.Status200OK)]
    public async Task<ActionResult<TraditionalGliResult>> PostAnalyzeTraditional([FromForm] IFormFile? file = null)
    {
        Stream? stream = null;
        if (file != null && file.Length > 0)
        {
            stream = file.OpenReadStream();
        }
        return await ProcessTraditionalAnalysis(stream);
    }

    private async Task<ActionResult<TraditionalGliResult>> ProcessTraditionalAnalysis(Stream? incomingStream)
    {
        Stream stream;

        if (incomingStream != null)
        {
            stream = incomingStream;
        }
        else
        {
            var defaultPath = Path.Combine(AppContext.BaseDirectory, "Models", "ML", "test_images", "shadow_challenging_vineyard.png");
            if (!System.IO.File.Exists(defaultPath))
            {
                defaultPath = Path.Combine(Directory.GetCurrentDirectory(), "Models", "ML", "test_images", "shadow_challenging_vineyard.png");
            }

            if (System.IO.File.Exists(defaultPath))
            {
                stream = System.IO.File.OpenRead(defaultPath);
            }
            else
            {
                return BadRequest(new { message = "Se requiere un archivo de imagen para el análisis." });
            }
        }

        using (stream)
        {
            var result = await _aiService.CalculateTraditionalGliAsync(stream);
            return Ok(result);
        }
    }

    /// <summary>
    /// Telemetría GPS simulada sobre las coordenadas de viñedos en Tolomosa, Tarija (-21.5721° S, -64.7478° W).
    /// </summary>
    [HttpGet("drone-telemetry/route")]
    public ActionResult<List<DroneWaypointDto>> GetFlightRoute()
    {
        return Ok(_aiService.GetTolomosaFlightRoute());
    }

    [HttpGet("drone-telemetry/current")]
    public ActionResult<DroneWaypointDto> GetCurrentPosition()
    {
        return Ok(_aiService.GetCurrentDronePosition());
    }
}
