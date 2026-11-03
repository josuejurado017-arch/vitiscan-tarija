using VitiScan.Api.DTOs;

namespace VitiScan.Api.Services;

public interface IAiInferenceService
{
    Task<AiClassificationResult> ClassifyImageAsync(Stream imageStream, string? fileName = null);
    Task<TraditionalGliResult> CalculateTraditionalGliAsync(Stream imageStream);
    Task<BenchmarkComparisonResult> RunBenchmarkAsync(Stream? imageStream = null, string? fileName = null);
    List<DroneWaypointDto> GetTolomosaFlightRoute();
    DroneWaypointDto GetCurrentDronePosition();
}
