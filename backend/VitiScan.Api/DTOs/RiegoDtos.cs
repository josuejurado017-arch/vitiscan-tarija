using System.ComponentModel.DataAnnotations;

namespace VitiScan.Api.DTOs;

/// <summary>
/// Payload enviado por el supervisor o enólogo para autorizar el riego (Human-in-the-loop).
/// </summary>
public class AprobarRiegoRequest
{
    [Required(ErrorMessage = "El nombre del supervisor o enólogo es obligatorio.")]
    public string NombreSupervisor { get; set; } = string.Empty; // Ej: "Ing. Carlos Mendoza (Enólogo Principal)"

    [Required(ErrorMessage = "La matrícula o credencial profesional es obligatoria para la firma.")]
    public string MatriculaProfesional { get; set; } = string.Empty; // Ej: "COL-AGR-7482-TJA"

    [Range(5, 180, ErrorMessage = "La duración del riego debe oscilar entre 5 y 180 minutos.")]
    public int? DuracionMinutosAjustada { get; set; } // Opcional: El enólogo puede ajustar el tiempo sugerido

    public string? ObservacionesAgronomicas { get; set; } // Ej: "Validado en campo. Foco de estrés hídrico moderado a severo por alta evapotranspiración."
}

/// <summary>
/// DTO con el resultado del análisis de IA para evaluar si se dispara la creación automática de OrdenRiego.
/// </summary>
public class DeteccionAiResultDto
{
    public int ParcelaId { get; set; } = 1;
    public int MisionVueloId { get; set; } = 1;
    public string Clasificacion { get; set; } = string.Empty; // "Estrés Hídrico Severo"
    public double Confianza { get; set; } // Ej: 0.88 (> 0.80)
    public string CoordenadasPunto { get; set; } = "-21.5721,-64.7478";
    public string SectorValvula { get; set; } = "VALVULA_SECTOR_B";
    public int DuracionSugeridaMinutos { get; set; } = 25;
    public string? ImagenUrl { get; set; }
}

/// <summary>
/// Registro de auditoría devuelto tras la aprobación humana.
/// </summary>
public class AuditoriaRiegoResponse
{
    public int OrdenRiegoId { get; set; }
    public string Estado { get; set; } = string.Empty;
    public DateTime TimestampAprobacionUtc { get; set; }
    public string AprobadoPor { get; set; } = string.Empty;
    public string Matricula { get; set; } = string.Empty;
    public string FirmaAprobacionSha256 { get; set; } = string.Empty;
    public string SectorValvula { get; set; } = string.Empty;
    public int DuracionMinutos { get; set; }
    public string TramaMqttEmitida { get; set; } = string.Empty;
    public MqttDispatchDetails MqttDetalles { get; set; } = new();
    public string WebhookStatus { get; set; } = string.Empty;
    public string MensajeAuditoria { get; set; } = string.Empty;
}

public class MqttDispatchDetails
{
    public string Broker { get; set; } = "mqtt://iot.vitiscan-tarija.bo:1883";
    public string Topic { get; set; } = string.Empty;
    public string Payload { get; set; } = string.Empty;
    public int Qos { get; set; } = 1;
    public bool Retain { get; set; } = false;
    public string ProtocoloHardware { get; set; } = "LoRaWAN / Solenoide 24VAC";
}
