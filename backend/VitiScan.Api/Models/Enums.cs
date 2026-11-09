namespace VitiScan.Api.Models;

public enum EstadoSaludParcela
{
    Optimo,
    Bueno,
    Regular,
    Critico
}

public enum EstadoMision
{
    Pendiente,
    Procesando,
    Completada
}

public enum TipoProblema
{
    EstresHidrico,
    LobesiaBotrana,
    Ninguno
}

public enum EstadoOrdenRiego
{
    PendienteAprobacion,
    Ejecutado
}
