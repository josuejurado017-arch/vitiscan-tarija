import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { VitiScanService } from '../services/vitiscan.service';
import { Parcela, Deteccion, OrdenRiego } from '../models/vitiscan.models';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="space-y-6">
      <!-- Header / Resumen del Valle de Tarija -->
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl">
        <div>
          <div class="flex items-center gap-3">
            <span class="px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              Valle Central de Tarija
            </span>
            <span class="text-xs text-gray-400">Actualizado hace unos momentos</span>
          </div>
          <h1 class="text-2xl md:text-3xl font-bold text-white mt-2">Centro de Control VitiScan</h1>
          <p class="text-gray-400 text-sm mt-1">
            Monitoreo multiespectral de viñedos, detección temprana de plagas y gestión hídrica autónoma.
          </p>
        </div>
        <div class="mt-4 md:mt-0 flex gap-3">
          <a routerLink="/flight-monitor" class="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-semibold transition-all shadow-lg shadow-indigo-600/30 flex items-center gap-2">
            <span>🛰️ Iniciar Monitoreo</span>
          </a>
          <a routerLink="/digital-twin" class="px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 rounded-xl text-sm font-semibold transition-all flex items-center gap-2">
            <span>🌐 Gemelo Digital 3D</span>
          </a>
        </div>
      </div>

      <!-- Tarjetas de Métricas Clave (KPIs) -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs uppercase tracking-wider text-gray-400 font-semibold">Parcelas Activas</span>
            <span class="p-2 bg-blue-500/10 text-blue-400 rounded-lg text-lg">🍇</span>
          </div>
          <p class="text-3xl font-extrabold text-white mt-3">{{ parcelas().length }}</p>
          <p class="text-xs text-gray-400 mt-1">Tolomosa, Lazaretto y Uriondo</p>
        </div>

        <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs uppercase tracking-wider text-gray-400 font-semibold">Detecciones de Riesgo</span>
            <span class="p-2 bg-amber-500/10 text-amber-400 rounded-lg text-lg">⚠️</span>
          </div>
          <p class="text-3xl font-extrabold text-amber-400 mt-3">{{ detecciones().length }}</p>
          <p class="text-xs text-gray-400 mt-1">Estrés Hídrico & Lobesia Botrana</p>
        </div>

        <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs uppercase tracking-wider text-gray-400 font-semibold">Órdenes de Riego</span>
            <span class="p-2 bg-cyan-500/10 text-cyan-400 rounded-lg text-lg">💧</span>
          </div>
          <p class="text-3xl font-extrabold text-cyan-400 mt-3">{{ ordenesRiego().length }}</p>
          <p class="text-xs text-gray-400 mt-1">Requieren validación agronómica</p>
        </div>

        <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs uppercase tracking-wider text-gray-400 font-semibold">Índice Salud Promedio</span>
            <span class="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg text-lg">🌿</span>
          </div>
          <p class="text-3xl font-extrabold text-emerald-400 mt-3">82.4%</p>
          <p class="text-xs text-emerald-400/80 mt-1">Condición favorable general</p>
        </div>
      </div>

      <!-- Sección Principal: Parcelas y Detecciones Críticas -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Listado de Parcelas de Tarija -->
        <div class="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <div class="flex justify-between items-center mb-4">
            <div>
              <h2 class="text-lg font-bold text-white">Estado de Viñedos por Subcentral</h2>
              <p class="text-xs text-gray-400">Datos georreferenciados del Valle de la Concepción y Lazaretto</p>
            </div>
            <span class="text-xs px-2.5 py-1 rounded bg-gray-800 text-gray-300 border border-gray-700">
              PostgreSQL / PostGIS Ready
            </span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-sm text-gray-300">
              <thead class="text-xs uppercase text-gray-400 border-b border-gray-800">
                <tr>
                  <th class="py-3 px-4">Parcela</th>
                  <th class="py-3 px-4">Subcentral</th>
                  <th class="py-3 px-4">Salud</th>
                  <th class="py-3 px-4 text-right">Acción</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-800">
                @for (parcela of parcelas(); track parcela.id) {
                  <tr class="hover:bg-gray-800/40 transition">
                    <td class="py-3 px-4 font-semibold text-white">{{ parcela.nombre }}</td>
                    <td class="py-3 px-4 text-gray-400">{{ parcela.subcentral }}</td>
                    <td class="py-3 px-4">
                      <span class="px-2.5 py-1 rounded-full text-xs font-semibold"
                        [ngClass]="{
                          'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30': parcela.estadoSalud === 'Optimo' || parcela.estadoSalud === 'Bueno',
                          'bg-amber-500/20 text-amber-400 border border-amber-500/30': parcela.estadoSalud === 'Regular',
                          'bg-red-500/20 text-red-400 border border-red-500/30': parcela.estadoSalud === 'Critico'
                        }">
                        {{ parcela.estadoSalud }}
                      </span>
                    </td>
                    <td class="py-3 px-4 text-right">
                      <a routerLink="/digital-twin" class="text-indigo-400 hover:text-indigo-300 text-xs font-semibold underline">
                        Inspeccionar 3D →
                      </a>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </div>

        <!-- Panel Lateral: Órdenes de Riego y Acción Rápida -->
        <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between">
          <div>
            <h2 class="text-lg font-bold text-white mb-1">Órdenes de Riego Inteligente</h2>
            <p class="text-xs text-gray-400 mb-4">Aprobación de bombeo para mitigación de estrés hídrico</p>

            <div class="space-y-3">
              @for (orden of ordenesRiego(); track orden.id) {
                <div class="p-4 bg-gray-800/60 border border-gray-700/60 rounded-xl">
                  <div class="flex justify-between items-start">
                    <div>
                      <p class="text-sm font-semibold text-white">{{ orden.sectorValvula }}</p>
                      <p class="text-xs text-cyan-400 mt-0.5">⏱️ Duración recomendada: {{ orden.duracionMinutos }} min</p>
                    </div>
                    <span class="text-xs px-2 py-0.5 rounded font-medium"
                      [ngClass]="orden.aprobadoPorHumano ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'">
                      {{ orden.aprobadoPorHumano ? 'Aprobada' : 'Pendiente' }}
                    </span>
                  </div>

                  @if (!orden.aprobadoPorHumano) {
                    <button (click)="aprobarOrden(orden.id!)"
                      class="mt-3 w-full py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition">
                      Aprobar Riego Manual
                    </button>
                  } @else {
                    <div class="mt-2 text-xs text-emerald-400 flex items-center gap-1">
                      <span>✓ Listo para telemetría de válvula</span>
                    </div>
                  }
                </div>
              }
            </div>
          </div>

          <div class="mt-6 pt-4 border-t border-gray-800 text-center">
            <span class="text-xs text-gray-500">Módulo de Integración IoT / LoRaWAN Tarija</span>
          </div>
        </div>
      </div>
    </div>
  `
})
export class DashboardComponent implements OnInit {
  private service = inject(VitiScanService);

  parcelas = signal<Parcela[]>([]);
  detecciones = signal<Deteccion[]>([]);
  ordenesRiego = signal<OrdenRiego[]>([]);

  ngOnInit(): void {
    this.service.getParcelas().subscribe(data => this.parcelas.set(data));
    this.service.getDetecciones().subscribe(data => this.detecciones.set(data));
    this.service.getOrdenesRiego().subscribe(data => this.ordenesRiego.set(data));
  }

  aprobarOrden(id: number): void {
    this.service.aprobarOrden(id).subscribe(() => {
      this.ordenesRiego.update(list =>
        list.map(o => o.id === id ? { ...o, aprobadoPorHumano: true } : o)
      );
    });
  }
}
