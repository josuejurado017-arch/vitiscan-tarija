namespace VitiScan.Api.DTOs;

public class BoundingBoxDto
{
    public int X1 { get; set; }
    public int Y1 { get; set; }
    public int X2 { get; set; }
    public int Y2 { get; set; }
    public string Etiqueta { get; set; } = string.Empty;
    public double Confianza { get; set; }
}

public class AiClassificationResult
{
    public string Metodo { get; set; } = "Inferencia Deep Learning ONNX Nativa (.NET 8 C#)";
    public string ModeloFormato { get; set; } = "Microsoft.ML.OnnxRuntime v1.20.1 (ResNet/YOLOv8)";
    public string Clasificacion { get; set; } = string.Empty; // Sano | Estrés Hídrico Severo | Brote Lobesia Botrana
    public double Confianza { get; set; }
    public Dictionary<string, double> Probabilidades { get; set; } = new();
    public List<BoundingBoxDto> BoundingBoxes { get; set; } = new();
    public string ResilienciaASombras { get; set; } = "Alta (Invariante a iluminación mediante filtros convolucionales)";
    public double TiempoInferenciaMs { get; set; }
}

public class TraditionalGliResult
{
    public string Metodo { get; set; } = "Algoritmo Tradicional Umbralización GLI (.NET)";
    public string Formula { get; set; } = "GLI = (2*G - R - B) / (2*G + R + B)";
    public double PorcentajeVerdor { get; set; }
    public double PorcentajeSequedad { get; set; }
    public double PorcentajeSombraArtefactos { get; set; }
    public string Diagnostico { get; set; } = string.Empty;
    public double TiempoEjecucionMs { get; set; }
    public string MascaraSequedadBase64 { get; set; } = string.Empty;
}

public class BenchmarkComparisonResult
{
    public string Descripcion { get; set; } = "Comparativa de Rendimiento y Robustez: GLI Matemático vs Inferencia ONNX (.NET Nativo)";
    public string ImagenEvaluada { get; set; } = string.Empty;
    public TraditionalGliResult MetodoTradicional { get; set; } = new();
    public AiClassificationResult MetodoIaOnnx { get; set; } = new();
    public Dictionary<string, object> AnalisisComparativo { get; set; } = new();
    public string ConclusionAgronomica { get; set; } = string.Empty;
}

public class DroneWaypointDto
{
    public int Paso { get; set; }
    public string Timestamp { get; set; } = string.Empty;
    public double Latitud { get; set; }
    public double Longitud { get; set; }
    public double AltitudMsnm { get; set; }
    public double AltitudAgl { get; set; }
    public double VelocidadMs { get; set; }
    public int BateriaPct { get; set; }
    public string Sector { get; set; } = string.Empty;
    public bool DisparoCamara { get; set; }
    public string? EventoIa { get; set; }
}
