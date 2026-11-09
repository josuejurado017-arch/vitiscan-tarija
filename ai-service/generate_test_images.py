from PIL import Image, ImageDraw
import numpy as np

def create_synthetic_test_images():
    w, h = 400, 300

    # 1. Imagen con Sombras Severas y Viñedo Saludable (El caso donde falla el método tradicional)
    # Suelo marrón/arcilloso base
    img_shadow = np.full((h, w, 3), [135, 110, 85], dtype=np.uint8)

    # Filas de viñedo verde brillante
    for y_row in [40, 110, 180, 250]:
        img_shadow[y_row-20:y_row+20, :] = [45, 150, 40]

    # Proyección de sombra densa en diagonal (artefacto de luz/nube/espaldera)
    # La sombra reduce drásticamente el canal verde y acentúa el ratio azul
    for y in range(h):
        for x in range(w):
            if (x * 0.7 + y) > 160 and (x * 0.7 + y) < 320:
                # Zona de sombra intensa
                img_shadow[y, x] = (img_shadow[y, x] * 0.22).astype(np.uint8)

    Image.fromarray(img_shadow).save('ai-service/test_images/shadow_challenging_vineyard.png')

    # 2. Viñedo con Estrés Hídrico Real (Clorosis y amarillamiento de hojas)
    img_stress = np.full((h, w, 3), [145, 115, 90], dtype=np.uint8)
    for y_row in [40, 110, 180, 250]:
        # Follaje amarillento / seco
        img_stress[y_row-20:y_row+20, :] = [185, 160, 45]
    Image.fromarray(img_stress).save('ai-service/test_images/water_stress_vineyard.png')

    # 3. Viñedo con Foco de Lobesia Botrana (Necrosis moteada en racimos)
    img_pest = np.full((h, w, 3), [135, 110, 85], dtype=np.uint8)
    for y_row in [40, 110, 180, 250]:
        img_pest[y_row-20:y_row+20, :] = [45, 140, 40]
        # Puntos de necrosis por orugas de Lobesia
        for x_spot in range(50, 350, 45):
            img_pest[y_row-10:y_row+10, x_spot-10:x_spot+10] = [140, 40, 30]
    Image.fromarray(img_pest).save('ai-service/test_images/lobesia_pest_vineyard.png')

    print("Imágenes de prueba sintéticas generadas en ai-service/test_images/")

if __name__ == '__main__':
    create_synthetic_test_images()
