using VitiScan.Api.DTOs;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public interface IIrrigationMqttDispatcher
{
    Task<(string tramaRaw, MqttDispatchDetails detalles, string firmaSha256)> DispatchIrrigationCommandAsync(
        OrdenRiego orden,
        string nombreSupervisor,
        string matriculaSupervisor,
        DateTime timestampUtc);
}
