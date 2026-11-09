# ADR-001: Consideraciones de Sincronización y Ventanas de Alerta
- **Fecha:** 2026-11-09
- **Estado:** Aceptado / Fijado por Arquitectura
- **Contexto:** Definición de la temporización para la red ESP-NOW de los Viñedos de Tarija.

## Decisiones Técnicas Tomadas
1. **Escucha de Alertas Fuera de Ciclo:** Ventanas de escucha de **35 ms** dentro de superframes de **1500 ms**, diseñadas para no solaparse con la cascada TDMA principal.
2. **Separación Física:** 22 metros de separación por cada rama del viñedo (coordenadas sintéticas iniciales para el Valle Central de Tarija).
3. **Límite Estricto de la Cabecera Binaria:** La cabecera se mantiene estrictamente en **6 bytes** sin incluir timestamp ni identificador de ciclo para cumplir con el límite de ESP-NOW. El simulador y el firmware gestionarán la sincronización externa o la deriva de reloj sin añadir bytes ocultos que rompan el struct de 12 bytes.
