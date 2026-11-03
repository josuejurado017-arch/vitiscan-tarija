from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class TraditionalAnalysisResponse(BaseModel):
    metodo: str = "Algoritmo Tradicional Umbralización GLI"
    formula: str = "GLI = (2*G - R - B) / (2*G + R + B)"
    porcentaje_verdor: float = Field(..., description="Porcentaje de vegetación fotosintéticamente activa")
    porcentaje_sequedad: float = Field(..., description="Porcentaje de vegetación con estrés hídrico o suelo")
    porcentaje_sombra_artefactos: float = Field(..., description="Pixeles en penumbra susceptibles a error")
    diagnostico: str
    tiempo_ejecucion_ms: float
    mascara_sequedad_base64: str = Field(..., description="Imagen PNG en Base64 con máscara de sequedad")

class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    etiqueta: str
    confianza: float

class AIAnalysisResponse(BaseModel):
    metodo: str = "Inferencia Deep Learning ONNX (ResNet/YOLOv8)"
    modelo_formato: str = "ONNX Runtime v1.31 (Opset 17)"
    clasificacion: str = Field(..., description="Sano | Estrés Hídrico Severo | Brote Lobesia Botrana")
    confianza: float = Field(..., description="Probabilidad de la clase predicha (0.0 a 1.0)")
    probabilidades: Dict[str, float]
    bounding_boxes: List[BoundingBox]
    resiliencia_a_sombras: str = "Alta (Invariante a iluminación mediante filtros convolucionales)"
    tiempo_inferencia_ms: float

class BenchmarkComparisonResponse(BaseModel):
    descripcion: str
    imagen_evaluada: str
    metodo_tradicional: Dict[str, Any]
    metodo_ia_onnx: Dict[str, Any]
    analisis_comparativo: Dict[str, Any]
    conclusion_agronomica: str

class TelemetryWaypoint(BaseModel):
    paso: int
    timestamp: str
    latitud: float
    longitud: float
    altitud_msnm: float
    altitud_agl: float
    velocidad_ms: float
    bateria_pct: int
    sector: str
    disparo_camara: bool
    evento_ia: Optional[str] = None
