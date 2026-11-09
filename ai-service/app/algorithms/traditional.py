import time
import io
import base64
import numpy as np
from PIL import Image
from ..models.schemas import TraditionalAnalysisResponse

def analyze_traditional_gli(image: Image.Image) -> TraditionalAnalysisResponse:
    """
    Algoritmo tradicional sin IA basado en Green Leaf Index (GLI):
    GLI = (2*G - R - B) / (2*G + R + B)
    """
    start_time = time.perf_counter()

    # Convertir a RGB y normalizar a float32 [0.0, 1.0]
    img_rgb = image.convert('RGB')
    arr = np.array(img_rgb, dtype=np.float32) / 255.0

    R = arr[:, :, 0]
    G = arr[:, :, 1]
    B = arr[:, :, 2]

    # GLI sintético
    numerador = 2.0 * G - R - B
    denominador = 2.0 * G + R + B
    # Evitar división por cero en pixeles negros
    denominador = np.where(denominador == 0, 1e-6, denominador)
    gli = numerador / denominador

    # Brillo general para detección de sombras
    luminancia = 0.299 * R + 0.587 * G + 0.114 * B
    mascara_sombra = luminancia < 0.20

    # Clasificación por umbrales tradicionales
    # Verdor saludable: GLI > 0.12 y no estar en penumbra extrema
    mascara_verde = (gli > 0.12) & (~mascara_sombra)
    
    # Sequedad o estrés detectado por el método tradicional:
    # GLI bajo o negativo (-0.15 a 0.12)
    # NOTA: Las sombras profundas provocan falsos positivos de sequedad
    mascara_sequedad = (gli <= 0.12) & (gli > -0.4)

    total_pixeles = arr.shape[0] * arr.shape[1]
    pct_verdor = float((np.sum(mascara_verde) / total_pixeles) * 100.0)
    pct_sequedad = float((np.sum(mascara_sequedad) / total_pixeles) * 100.0)
    pct_sombra = float((np.sum(mascara_sombra) / total_pixeles) * 100.0)

    # Diagnóstico tradicional empírico
    if pct_sequedad > 35.0:
        diagnostico = "Alerta: Alto estrés hídrico o clorosis foliar detectada por umbralización"
    elif pct_verdor > 45.0:
        diagnostico = "Follaje predominantemente saludable"
    else:
        diagnostico = "Cobertura vegetal moderada / Suelo visible"

    # Generar Máscara Visual en Base64
    # Verde: Vegetación sana, Rojo/Naranja: Sequedad/Estrés, Gris: Sombras/Otros
    mask_visual = np.zeros((arr.shape[0], arr.shape[1], 3), dtype=np.uint8)
    mask_visual[mascara_verde] = [34, 197, 94]      # Verde esmeralda (#22c55e)
    mask_visual[mascara_sequedad] = [239, 68, 68]   # Rojo/Naranja alerta (#ef4444)
    mask_visual[mascara_sombra] = [55, 65, 81]      # Gris sombra (#374151)

    mask_img = Image.fromarray(mask_visual)
    buffer = io.BytesIO()
    mask_img.save(buffer, format="PNG")
    mask_b64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return TraditionalAnalysisResponse(
        porcentaje_verdor=round(pct_verdor, 2),
        porcentaje_sequedad=round(pct_sequedad, 2),
        porcentaje_sombra_artefactos=round(pct_sombra, 2),
        diagnostico=diagnostico,
        tiempo_ejecucion_ms=round(elapsed_ms, 2),
        mascara_sequedad_base64=mask_b64
    )
