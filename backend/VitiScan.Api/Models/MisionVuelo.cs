namespace VitiScan.Api.Models;

public class MisionVuelo
{
    public int Id { get; set; }
    public int ParcelaId { get; set; }
    public Parcela? Parcela { get; set; }
    public DateTime FechaHora { get; set; } = DateTime.UtcNow;
    public EstadoMision Estado { get; set; } = EstadoMision.Pendiente;

    public ICollection<Deteccion> Detecciones { get; set; } = new List<Deteccion>();
}
