namespace VitiScan.Api.Models;

public class OrdenRiego
{
    public int Id { get; set; }
    public int ParcelaId { get; set; }
    public Parcela? Parcela { get; set; }

    public string SectorValvula { get; set; } = string.Empty;
    public int DuracionMinutos { get; set; } = 25;
    public EstadoOrdenRiego Estado { get; set; } = EstadoOrdenRiego.PendienteAprobacion;
    public bool AprobadoPorHumano { get; set; } = false;

    // Metadatos de Auditoría y Flujo de Control Human-in-the-loop
    public DateTime FechaCreacion { get; set; } = DateTime.UtcNow;
    public DateTime? FechaAprobacion { get; set; }
    public string? AprobadoPorSupervisor { get; set; }
    public string? MatriculaSupervisor { get; set; }
    public string? FirmaDigitalSha256 { get; set; }
    public string? ObservacionesAgronomicas { get; set; }
    public string? MotivoDisparoIa { get; set; }
    public string? TramaMqttEmitida { get; set; }
}
