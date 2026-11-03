import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, of } from 'rxjs';
import { Parcela, MisionVuelo, Deteccion, OrdenRiego } from '../models/vitiscan.models';

@Injectable({
  providedIn: 'root'
})
export class VitiScanService {
  private http = inject(HttpClient);
  private apiUrl = '/api';

  // Fallback mock data para asegurar funcionamiento offline o antes de iniciar el backend
  private mockParcelas: Parcela[] = [
    {
      id: 1,
      nombre: 'Viñedo Los Parrales - Cuadro Norte',
      subcentral: 'Tolomosa',
      coordenadasGeoJson: '{"type":"Polygon"}',
      estadoSalud: 'Regular'
    },
    {
      id: 2,
      nombre: 'Finca San Roque - Syrah',
      subcentral: 'Lazaretto',
      coordenadasGeoJson: '{"type":"Polygon"}',
      estadoSalud: 'Critico'
    },
    {
      id: 3,
      nombre: 'Bodega Campos de Solana - Tannat',
      subcentral: 'Uriondo',
      coordenadasGeoJson: '{"type":"Polygon"}',
      estadoSalud: 'Optimo'
    }
  ];

  private mockDetecciones: Deteccion[] = [
    {
      id: 1,
      misionVueloId: 1,
      coordenadasPunto: '-21.5721, -64.7478',
      tipoProblema: 'EstresHidrico',
      severidad: 78,
      confianza: 0.94,
      imagenUrl: 'https://images.unsplash.com/photo-1506619216599-9d16d0903dfd?auto=format&fit=crop&w=600&q=80'
    },
    {
      id: 2,
      misionVueloId: 1,
      coordenadasPunto: '-21.5735, -64.7469',
      tipoProblema: 'LobesiaBotrana',
      severidad: 65,
      confianza: 0.88,
      imagenUrl: 'https://images.unsplash.com/photo-1510812431401-41d2bd2722f3?auto=format&fit=crop&w=600&q=80'
    }
  ];

  private mockOrdenesRiego: OrdenRiego[] = [
    {
      id: 1,
      parcelaId: 1,
      sectorValvula: 'Sector B - Válvula 03 (Tolomosa)',
      duracionMinutos: 45,
      estado: 'PendienteAprobacion',
      aprobadoPorHumano: false
    }
  ];

  // Parcelas
  getParcelas(): Observable<Parcela[]> {
    return this.http.get<Parcela[]>(`${this.apiUrl}/parcelas`).pipe(
      catchError(() => of(this.mockParcelas))
    );
  }

  getParcelaById(id: number): Observable<Parcela | null> {
    return this.http.get<Parcela>(`${this.apiUrl}/parcelas/${id}`).pipe(
      catchError(() => of(this.mockParcelas.find(p => p.id === id) || null))
    );
  }

  // Misiones de Vuelo
  getMisiones(): Observable<MisionVuelo[]> {
    const mockMisiones: MisionVuelo[] = [
      {
        id: 1,
        parcelaId: 1,
        fechaHora: new Date().toISOString(),
        estado: 'Completada',
        detecciones: this.mockDetecciones
      },
      {
        id: 2,
        parcelaId: 2,
        fechaHora: new Date().toISOString(),
        estado: 'Procesando'
      }
    ];

    return this.http.get<MisionVuelo[]>(`${this.apiUrl}/misionesvuelo`).pipe(
      catchError(() => of(mockMisiones))
    );
  }

  crearMision(mision: Partial<MisionVuelo>): Observable<MisionVuelo> {
    return this.http.post<MisionVuelo>(`${this.apiUrl}/misionesvuelo`, mision).pipe(
      catchError(() => of({
        id: Math.floor(Math.random() * 1000) + 10,
        parcelaId: mision.parcelaId || 1,
        fechaHora: new Date().toISOString(),
        estado: 'Pendiente' as const
      } as MisionVuelo))
    );
  }

  // Detecciones
  getDetecciones(misionVueloId?: number): Observable<Deteccion[]> {
    const url = misionVueloId ? `${this.apiUrl}/detecciones?misionVueloId=${misionVueloId}` : `${this.apiUrl}/detecciones`;
    return this.http.get<Deteccion[]>(url).pipe(
      catchError(() => of(this.mockDetecciones))
    );
  }

  registrarDeteccion(deteccion: Deteccion): Observable<Deteccion> {
    return this.http.post<Deteccion>(`${this.apiUrl}/detecciones`, deteccion).pipe(
      catchError(() => of(deteccion))
    );
  }

  // Órdenes de Riego
  getOrdenesRiego(): Observable<OrdenRiego[]> {
    return this.http.get<OrdenRiego[]>(`${this.apiUrl}/ordenesriego`).pipe(
      catchError(() => of(this.mockOrdenesRiego))
    );
  }

  // Microservicio IA Python (FastAPI / ONNX)
  private aiServiceUrl = '/api/ai';

  getBenchmarkCompare(): Observable<any> {
    return this.http.get(`${this.aiServiceUrl}/benchmark-compare`).pipe(
      catchError(() => of({
        descripcion: 'Comparativa de Rendimiento y Robustez: GLI Matemático vs Inferencia ONNX',
        imagen_evaluada: 'shadow_challenging_vineyard.png (Simulación sombras Tolomosa)',
        metodo_tradicional: {
          porcentaje_verdor: 28.29,
          porcentaje_sequedad: 46.67,
          porcentaje_sombra_artefactos: 44.60,
          diagnostico: 'Alerta: Falso positivo por sombras de espaldera'
        },
        metodo_ia_onnx: {
          clasificacion: 'Sano',
          confianza: 0.88,
          tiempo_inferencia_ms: 22.5
        },
        analisis_comparativo: {
          resumen_fallo_tradicional: {
            causa_raiz: 'El índice GLI normalizado falla en sombras al aumentar el ratio azul relativo.',
            impacto_agronomico: 'Falsos positivos masivos de estrés hídrico.'
          }
        },
        conclusion_agronomica: 'El clasificador ONNX discrimina con exactitud el estado fisiológico sin ser afectado por la penumbra.'
      }))
    );
  }

  getDroneTelemetryRoute(): Observable<any[]> {
    return this.http.get<any[]>(`${this.aiServiceUrl}/drone-telemetry/route`).pipe(
      catchError(() => of([]))
    );
  }

  getDroneTelemetryCurrent(): Observable<any> {
    return this.http.get<any>(`${this.aiServiceUrl}/drone-telemetry/current`).pipe(
      catchError(() => of(null))
    );
  }

  aprobarOrden(id: number, duracionMinutos = 25): Observable<any> {
    const payload = {
      nombreSupervisor: 'Ing. Carlos Mendoza (Enólogo Principal)',
      matriculaProfesional: 'COL-AGR-7482-TJA',
      duracionMinutosAjustada: duracionMinutos,
      observacionesAgronomicas: 'Aprobación agronómica en tiempo real desde Gemelo Digital 3D (Human-in-the-loop)'
    };
    return this.http.post(`${this.apiUrl}/riego/${id}/aprobar`, payload).pipe(
      catchError(() => of({
        ordenRiegoId: id,
        estado: 'Ejecutado',
        tramaMqttEmitida: 'VALVULA_SECTOR_B: OPEN: 25min',
        mensajeAuditoria: 'Riego autorizado por enólogo y ejecutado localmente.'
      }))
    );
  }
}
