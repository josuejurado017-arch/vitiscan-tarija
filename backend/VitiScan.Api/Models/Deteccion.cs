using System.Text.Json.Serialization;

namespace VitiScan.Api.Models;

public class Deteccion
{
    public int Id { get; set; }
    public int MisionVueloId { get; set; }

    [JsonIgnore]
    public MisionVuelo? MisionVuelo { get; set; }

    public string CoordenadasPunto { get; set; } = string.Empty; // Formato "lat,lng" o GeoJson Point
    public TipoProblema TipoProblema { get; set; } = TipoProblema.Ninguno;
    public int Severidad { get; set; } // 0 a 100
    public double Confianza { get; set; } // 0.00 a 1.00
    public string ImagenUrl { get; set; } = string.Empty;
}
