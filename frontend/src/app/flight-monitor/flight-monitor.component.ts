import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { VitiScanService } from '../services/vitiscan.service';
import { Deteccion, Parcela } from '../models/vitiscan.models';

@Component({
  selector: 'app-flight-monitor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6">
      <!-- Barra Superior de Estado del Vuelo -->
      <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center bg-gray-900 border border-gray-800 rounded-2xl p-5 gap-4 shadow-xl">
        <div class="flex items-center gap-4">
          <div class="relative flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
            <span class="text-2xl animate-pulse">🛸</span>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h1 class="text-xl font-bold text-white">Vuelo Activo: Misión MV-2026-TARIJA</h1>
              <span class="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                En Misión
              </span>
            </div>
            <p class="text-xs text-gray-400 mt-0.5">
              Dron Autónomo DJI Matrice 350 RTK con Cámara Multiespectral Zenmuse P1
            </p>
          </div>
        </div>

        <!-- Telemetría Rápida -->
        <div class="flex flex-wrap gap-4 text-xs">
          <div class="bg-gray-800/80 px-3 py-2 rounded-lg border border-gray-700">
            <span class="text-gray-400 block">Altitud AGL</span>
            <span class="font-bold text-white text-sm">{{ altitud() }} m</span>
          </div>
          <div class="bg-gray-800/80 px-3 py-2 rounded-lg border border-gray-700">
            <span class="text-gray-400 block">Velocidad</span>
            <span class="font-bold text-white text-sm">{{ velocidad() }} m/s</span>
          </div>
          <div class="bg-gray-800/80 px-3 py-2 rounded-lg border border-gray-700">
            <span class="text-gray-400 block">Batería</span>
            <span class="font-bold text-emerald-400 text-sm">{{ bateria() }}%</span>
          </div>
          <div class="bg-gray-800/80 px-3 py-2 rounded-lg border border-gray-700">
            <span class="text-gray-400 block">Coordenadas RTK</span>
            <span class="font-mono text-cyan-300 text-xs">-21.5721° S, -64.7478° W</span>
          </div>
        </div>
      </div>

      <!-- Pantalla Principal: Feed de Vuelo + Controles IA -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Visualizador HUD de Cámara del Dron -->
        <div class="lg:col-span-2 relative bg-black rounded-2xl overflow-hidden border border-gray-800 min-h-[460px] flex flex-col justify-between p-6">
          <!-- Fondo Simulado del Viñedo desde el aire -->
          <div class="absolute inset-0 bg-cover bg-center opacity-60 filter contrast-125"
            style="background-image: url('https://images.unsplash.com/photo-1506619216599-9d16d0903dfd?auto=format&fit=crop&w=1200&q=80')">
          </div>

          <!-- Cuadrícula HUD y Mira Telemétrica -->
          <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/60 pointer-events-none"></div>

          <!-- Mira Central del Dron -->
          <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div class="relative w-48 h-48 border border-cyan-500/40 rounded-full flex items-center justify-center">
              <div class="w-2 h-2 bg-cyan-400 rounded-full animate-ping"></div>
              <div class="absolute top-0 w-0.5 h-4 bg-cyan-400"></div>
              <div class="absolute bottom-0 w-0.5 h-4 bg-cyan-400"></div>
              <div class="absolute left-0 h-0.5 w-4 bg-cyan-400"></div>
              <div class="absolute right-0 h-0.5 w-4 bg-cyan-400"></div>
            </div>
          </div>

          <!-- Bounding Box de Detección Simulado si hay análisis activo -->
          @if (isAnalyzing()) {
            <div class="absolute top-1/3 left-1/3 w-40 h-32 border-2 border-dashed border-amber-400 bg-amber-500/10 rounded flex flex-col justify-between p-1.5 animate-pulse">
              <span class="text-[10px] font-bold bg-amber-500 text-black px-1 rounded inline-block self-start">
                IA SCAN: Analizando Espectro...
              </span>
              <span class="text-[9px] text-amber-300 font-mono self-end">NDVI: 0.38 [BAJO]</span>
            </div>
          }

          <!-- Header del HUD -->
          <div class="relative z-10 flex justify-between items-center text-xs">
            <div class="flex items-center gap-2 bg-gray-900/80 backdrop-blur px-3 py-1.5 rounded-lg border border-gray-700 font-mono text-cyan-400">
              <span class="w-2 h-2 rounded-full bg-red-500 animate-ping"></span>
              <span>REC 4K NIR/RGB 60FPS</span>
            </div>
            <div class="bg-gray-900/80 backdrop-blur px-3 py-1.5 rounded-lg border border-gray-700 text-gray-300 font-mono">
              VALLE CENTRAL TARIJA - POLÍGONO 01
            </div>
          </div>

          <!-- Footer del HUD con el Disparador de Análisis -->
          <div class="relative z-10 flex flex-col sm:flex-row justify-between items-center gap-4 bg-gray-900/90 backdrop-blur-md p-4 rounded-xl border border-gray-700">
            <div>
              <p class="text-sm font-bold text-white">Disparador de Análisis Multiespectral IA</p>
              <p class="text-xs text-gray-400">Captura fotograma ortomosaico y ejecuta inferencia edge de estrés y plagas.</p>
            </div>

            <button
              (click)="dispararAnalisis()"
              [disabled]="isAnalyzing()"
              class="px-5 py-2.5 rounded-xl font-bold text-xs uppercase tracking-wider transition-all flex items-center gap-2"
              [ngClass]="isAnalyzing() ? 'bg-amber-600 text-white cursor-wait' : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/30'">
              @if (isAnalyzing()) {
                <span class="animate-spin">🔄</span>
                <span>Procesando Inferencia...</span>
              } @else {
                <span>⚡ Disparar Análisis IA</span>
              }
            </button>
          </div>
        </div>

        <!-- Panel Lateral: Registro de Detecciones en Vivo -->
        <div class="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col justify-between">
          <div>
            <div class="flex justify-between items-center mb-4">
              <h2 class="text-base font-bold text-white">Detecciones de la Misión</h2>
              <span class="text-xs px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-400 font-medium">
                {{ detectionsLog().length }} eventos
              </span>
            </div>

            <div class="space-y-3 overflow-y-auto max-h-[380px] pr-1">
              @for (det of detectionsLog(); track $index) {
                <div class="p-3.5 bg-gray-800/80 border rounded-xl"
                  [ngClass]="det.tipoProblema === 'EstresHidrico' ? 'border-amber-500/40 bg-amber-500/5' : 'border-red-500/40 bg-red-500/5'">
                  <div class="flex justify-between items-start">
                    <div>
                      <span class="px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider"
                        [ngClass]="det.tipoProblema === 'EstresHidrico' ? 'bg-amber-500/20 text-amber-400' : 'bg-red-500/20 text-red-400'">
                        {{ det.tipoProblema === 'EstresHidrico' ? 'Estrés Hídrico' : 'Lobesia Botrana' }}
                      </span>
                      <p class="text-xs text-white font-semibold mt-1.5">
                        Severidad: {{ det.severidad }}% | Confianza: {{ (det.confianza * 100).toFixed(0) }}%
                      </p>
                      <p class="text-[11px] font-mono text-gray-400 mt-0.5">
                        📍 {{ det.coordenadasPunto }}
                      </p>
                    </div>
                  </div>
                  <div class="mt-2 text-[11px] text-gray-400 flex items-center justify-between border-t border-gray-700/50 pt-2">
                    <span>Misión #{{ det.misionVueloId }}</span>
                    <span class="text-emerald-400">Guardado en PostgreSQL ✓</span>
                  </div>
                </div>
              }
            </div>
          </div>

          <div class="mt-4 pt-3 border-t border-gray-800 text-xs text-gray-400 flex justify-between items-center">
            <span>Protocolo MAVLink v2.0</span>
            <span class="text-emerald-400 font-mono">ENLACE ACTIVO</span>
          </div>
        </div>
      </div>
    </div>
  `
})
export class FlightMonitorComponent implements OnInit, OnDestroy {
  private vitiscanService = inject(VitiScanService);

  altitud = signal(42);
  velocidad = signal(11.5);
  bateria = signal(86);
  isAnalyzing = signal(false);

  detectionsLog = signal<Deteccion[]>([
    {
      misionVueloId: 1,
      coordenadasPunto: '-21.5721, -64.7478',
      tipoProblema: 'EstresHidrico',
      severidad: 78,
      confianza: 0.94,
      imagenUrl: 'https://images.unsplash.com/photo-1506619216599-9d16d0903dfd?auto=format&fit=crop&w=600&q=80'
    }
  ]);

  private telemetryInterval?: any;

  ngOnInit(): void {
    // Simular fluctuación sutil de telemetría de vuelo
    this.telemetryInterval = setInterval(() => {
      this.altitud.update(a => +(a + (Math.random() * 0.6 - 0.3)).toFixed(1));
      this.velocidad.update(v => +(v + (Math.random() * 0.4 - 0.2)).toFixed(1));
    }, 2000);
  }

  ngOnDestroy(): void {
    if (this.telemetryInterval) {
      clearInterval(this.telemetryInterval);
    }
  }

  dispararAnalisis(): void {
    this.isAnalyzing.set(true);

    setTimeout(() => {
      // Simular inferencia IA de precisión
      const problemas: Array<'EstresHidrico' | 'LobesiaBotrana'> = ['EstresHidrico', 'LobesiaBotrana'];
      const seleccionado = problemas[Math.floor(Math.random() * problemas.length)];
      const severidadRand = Math.floor(Math.random() * 35) + 60; // 60 a 95
      const confianzaRand = +(Math.random() * 0.12 + 0.85).toFixed(2); // 0.85 a 0.97

      const nuevaDeteccion: Deteccion = {
        misionVueloId: 1,
        coordenadasPunto: `-21.57${Math.floor(Math.random() * 50) + 10}, -64.74${Math.floor(Math.random() * 50) + 10}`,
        tipoProblema: seleccionado,
        severidad: severidadRand,
        confianza: confianzaRand,
        imagenUrl: 'https://images.unsplash.com/photo-1510812431401-41d2bd2722f3?auto=format&fit=crop&w=600&q=80'
      };

      // Registrar mediante servicio en backend
      this.vitiscanService.registrarDeteccion(nuevaDeteccion).subscribe(saved => {
        this.detectionsLog.update(list => [nuevaDeteccion, ...list]);
        this.isAnalyzing.set(false);
      });
    }, 2200);
  }
}
