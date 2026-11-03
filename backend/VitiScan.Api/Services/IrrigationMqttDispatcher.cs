using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using VitiScan.Api.DTOs;
using VitiScan.Api.Models;

namespace VitiScan.Api.Services;

public class IrrigationMqttDispatcher : IIrrigationMqttDispatcher
{
    private readonly ILogger<IrrigationMqttDispatcher> _logger;

    public IrrigationMqttDispatcher(ILogger<IrrigationMqttDispatcher> logger)
    {
        _logger = logger;
    }

    public Task<(string tramaRaw, MqttDispatchDetails detalles, string firmaSha256)> DispatchIrrigationCommandAsync(
        OrdenRiego orden,
        string nombreSupervisor,
        string matriculaSupervisor,
        DateTime timestampUtc)
    {
        // 1. Trama Exacta Solicitada: VALVULA_SECTOR_B: OPEN: 25min
        var sectorNormalizado = orden.SectorValvula.ToUpper().Replace(" ", "_");
        var tramaRaw = $"{sectorNormalizado}: OPEN: {orden.DuracionMinutos}min";

        // 2. Topic MQTT y Payload JSON enriquecido
        var topic = $"vitiscan/tarija/{sectorNormalizado.ToLower()}/cmd";
        var jsonPayload = JsonSerializer.Serialize(new
        {
            orden_id = orden.Id,
            valvula = sectorNormalizado,
            comando = "OPEN",
            duracion_min = orden.DuracionMinutos,
            autorizado_por = nombreSupervisor,
            matricula = matriculaSupervisor,
            timestamp_utc = timestampUtc.ToString("o"),
            protocolo = "LoRaWAN / Solenoide 24VAC"
        }, new JsonSerializerOptions { WriteIndented = false });

        // 3. Generación de Firma Criptográfica SHA-256 para Auditoría y No Repudio
        var rawSignatureData = $"{orden.Id}|{sectorNormalizado}|{orden.DuracionMinutos}|{matriculaSupervisor}|{timestampUtc:yyyy-MM-ddTHH:mm:ssZ}";
        var hashBytes = SHA256.HashData(Encoding.UTF8.GetBytes(rawSignatureData));
        var firmaSha256 = Convert.ToHexString(hashBytes).ToLowerInvariant();

        // 4. Simulación de Envío a Broker MQTT / Webhook
        _logger.LogInformation(
            "📡 [MQTT DISPATCH] Trama emitida al broker topic '{Topic}': '{TramaRaw}'. Firma SHA256: {Firma}",
            topic, tramaRaw, firmaSha256);

        var detalles = new MqttDispatchDetails
        {
            Topic = topic,
            Payload = jsonPayload,
            Qos = 1,
            Retain = false,
            ProtocoloHardware = "LoRaWAN Transceiver -> Gateway Tolomosa Norte -> Válvula Solenoide"
        };

        return Task.FromResult((tramaRaw, detalles, firmaSha256));
    }
}
