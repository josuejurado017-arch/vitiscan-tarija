using System.Text.Json.Serialization;

namespace VitiScan.Api.Models;

public class Parcela
{
    public int Id { get; set; }
    public string Nombre { get; set; } = string.Empty;
    public string Subcentral { get; set; } = string.Empty; // Ej: Tolomosa, Lazaretto, Uriondo
    public string CoordenadasGeoJson { get; set; } = string.Empty;
    public string EstadoSalud { get; set; } = "Bueno"; // Optimo, Bueno, Regular, Critico

    [JsonIgnore]
    public ICollection<MisionVuelo> MisionesVuelo { get; set; } = new List<MisionVuelo>();

    [JsonIgnore]
    public ICollection<OrdenRiego> OrdenesRiego { get; set; } = new List<OrdenRiego>();
}
