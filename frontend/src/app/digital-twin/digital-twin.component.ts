import {
  Component,
  ElementRef,
  OnInit,
  OnDestroy,
  ViewChild,
  Input,
  Output,
  EventEmitter,
  signal,
  inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { VitiScanService } from '../services/vitiscan.service';

export type EstadoSaludHilera = 'Saludable' | 'EstresHidrico' | 'Lobesia';

export interface TelemetriaHilera {
  id: string;
  nombre: string;
  sector: 'Sector A' | 'Sector B' | 'Sector C';
  variedad: string;
  estado: EstadoSaludHilera;
  humedadSuelo: number; // Porcentaje %
  ndvi: number; // 0.0 a 1.0
  temperaturaCanopia: number; // °C
  deficitHidricoMm: number; // mm
  valvulaAsociada: string;
  duracionRiegoMin: number; // minutos
  riegoActivo?: boolean;
}

interface RowMeshEntry {
  mesh: THREE.Mesh;
  telemetria: TelemetriaHilera;
  originalMaterials: {
    salud: THREE.Material;
    sector: THREE.Material;
  };
}

@Component({
  selector: 'app-digital-twin',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="relative w-full h-[calc(100vh-130px)] rounded-2xl overflow-hidden border border-gray-800 bg-[#070a11] shadow-2xl">
      <!-- Contenedor WebGL para Three.js -->
      <div #canvasContainer class="w-full h-full cursor-grab active:cursor-grabbing"></div>

      <!-- Barra de Herramientas Superior: Controles de Coloración y Vistas -->
      <div class="absolute top-4 left-4 right-4 flex flex-wrap justify-between items-center gap-3 pointer-events-none">
        <!-- Tarjeta de Identificación del Viñedo -->
        <div class="bg-gray-900/90 backdrop-blur-md border border-gray-800 rounded-xl px-4 py-2.5 shadow-xl pointer-events-auto flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-emerald-400 animate-pulse"></div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-extrabold uppercase tracking-wider text-emerald-400">Gemelo Digital 3D</span>
              <span class="text-[11px] text-gray-400">| Tolomosa, Tarija</span>
            </div>
            <p class="text-xs font-semibold text-white">Ladera Central - Viñedo en Pendiente</p>
          </div>
        </div>

        <!-- Selector de Coloración / Modo de Inspección -->
        <div class="bg-gray-900/90 backdrop-blur-md border border-gray-800 rounded-xl p-1.5 shadow-xl pointer-events-auto flex items-center gap-1 text-xs">
          <span class="text-gray-400 font-medium px-2 hidden sm:inline">Coloración:</span>
          
          <button
            (click)="setModoColoracion('salud')"
            [ngClass]="modoColoracion() === 'salud' ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/40' : 'text-gray-400 hover:text-white'"
            class="px-3 py-1.5 rounded-lg font-semibold transition flex items-center gap-1.5">
            <span>🌿</span>
            <span>Salud / NDVI</span>
          </button>

          <button
            (click)="setModoColoracion('sector')"
            [ngClass]="modoColoracion() === 'sector' ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/40' : 'text-gray-400 hover:text-white'"
            class="px-3 py-1.5 rounded-lg font-semibold transition flex items-center gap-1.5">
            <span>🗺️</span>
            <span>Por Sectores</span>
          </button>
        </div>

        <!-- Controles de Cámara Rápidos -->
        <div class="bg-gray-900/90 backdrop-blur-md border border-gray-800 rounded-xl p-1.5 shadow-xl pointer-events-auto flex items-center gap-1 text-xs">
          <button (click)="resetCamara()" title="Reiniciar Vista"
            class="p-2 hover:bg-gray-800 text-gray-300 hover:text-white rounded-lg transition">
            🔄 Centrar
          </button>
          <button (click)="vistaCenital()" title="Vista Aérea / Top"
            class="p-2 hover:bg-gray-800 text-gray-300 hover:text-white rounded-lg transition">
            📐 Cenital
          </button>
          <button (click)="toggleAutoRotacion()"
            [ngClass]="autoRotacion() ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/30' : 'text-gray-400 hover:bg-gray-800'"
            class="px-2.5 py-1.5 rounded-lg transition flex items-center gap-1">
            <span>{{ autoRotacion() ? '⏸️ Parar' : '▶️ Órbita' }}</span>
          </button>
        </div>
      </div>

      <!-- Leyenda Inferior Flotante -->
      <div class="absolute bottom-4 left-4 right-4 flex flex-col md:flex-row justify-between items-center bg-gray-900/85 backdrop-blur-md border border-gray-800 rounded-xl p-3 px-5 text-xs text-gray-300 gap-3 pointer-events-auto">
        <div class="flex flex-wrap items-center gap-4">
          @if (modoColoracion() === 'salud') {
            <span class="text-gray-400 font-semibold">Estado Fitoclimático:</span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-emerald-500 inline-block shadow-sm shadow-emerald-500"></span>
              <span class="text-gray-200">Saludable (NDVI &gt; 0.70)</span>
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-amber-500 inline-block animate-pulse shadow-sm shadow-amber-500"></span>
              <span class="text-amber-300 font-medium">Estrés Hídrico (Humedad &lt; 20%)</span>
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-red-500 inline-block animate-pulse shadow-sm shadow-red-500"></span>
              <span class="text-red-300 font-medium">Sospecha Lobesia Botrana</span>
            </span>
          } @else {
            <span class="text-gray-400 font-semibold">Distribución por Sectores:</span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-cyan-500 inline-block"></span>
              <span>Sector A (Tannat - 4 Hileras)</span>
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-purple-500 inline-block"></span>
              <span>Sector B (Syrah - 4 Hileras)</span>
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full bg-amber-500 inline-block"></span>
              <span>Sector C (Cabernet - 4 Hileras)</span>
            </span>
          }
        </div>

        <div class="text-[11px] text-gray-400 flex items-center gap-2">
          <span>💡 Clic en cualquier hilera con estrés para telemetría y riego localizado</span>
        </div>
      </div>

      <!-- Modal de Telemetría e Intervención Agronómica -->
      @if (hileraModal(); as hilera) {
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
          <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden p-6 text-white space-y-5">
            <!-- Header Modal -->
            <div class="flex justify-between items-start border-b border-gray-800 pb-4">
              <div>
                <div class="flex items-center gap-2.5">
                  <span class="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider"
                    [ngClass]="{
                      'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30': hilera.estado === 'Saludable',
                      'bg-amber-500/20 text-amber-400 border border-amber-500/30': hilera.estado === 'EstresHidrico',
                      'bg-red-500/20 text-red-400 border border-red-500/30': hilera.estado === 'Lobesia'
                    }">
                    {{ hilera.estado === 'EstresHidrico' ? '⚠️ Estrés Hídrico Detectado' : (hilera.estado === 'Lobesia' ? '🚨 Alerta Fitosanitaria' : '🌿 Condición Óptima') }}
                  </span>
                  <span class="text-xs text-gray-400 font-mono">{{ hilera.id }}</span>
                </div>
                <h3 class="text-xl font-bold text-white mt-1">{{ hilera.nombre }}</h3>
                <p class="text-xs text-gray-400">{{ hilera.sector }} • Variedad: {{ hilera.variedad }}</p>
              </div>

              <button
                (click)="cerrarModal()"
                class="w-8 h-8 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white flex items-center justify-center transition">
                ✕
              </button>
            </div>

            <!-- Grilla de Métricas de Telemetría -->
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
              <!-- Humedad Suelo -->
              <div class="bg-gray-800/80 p-3 rounded-xl border border-gray-700/60">
                <span class="text-gray-400 block">Humedad de Suelo</span>
                <span class="text-lg font-bold"
                  [ngClass]="hilera.humedadSuelo < 22 ? 'text-amber-400' : 'text-emerald-400'">
                  {{ hilera.humedadSuelo }}%
                </span>
                <div class="w-full bg-gray-700 h-1.5 rounded-full mt-2 overflow-hidden">
                  <div class="h-full rounded-full transition-all duration-500"
                    [ngClass]="hilera.humedadSuelo < 22 ? 'bg-amber-400' : 'bg-emerald-400'"
                    [style.width.%]="hilera.humedadSuelo"></div>
                </div>
              </div>

              <!-- NDVI -->
              <div class="bg-gray-800/80 p-3 rounded-xl border border-gray-700/60">
                <span class="text-gray-400 block">Índice NDVI</span>
                <span class="text-lg font-bold"
                  [ngClass]="hilera.ndvi < 0.5 ? 'text-amber-400' : 'text-emerald-400'">
                  {{ hilera.ndvi }}
                </span>
                <span class="text-[10px] text-gray-400 block mt-1">Reflectancia NIR/Red</span>
              </div>

              <!-- Temp Canopia -->
              <div class="bg-gray-800/80 p-3 rounded-xl border border-gray-700/60">
                <span class="text-gray-400 block">Temp. Canopia</span>
                <span class="text-lg font-bold text-white">{{ hilera.temperaturaCanopia }} °C</span>
                <span class="text-[10px] text-gray-400 block mt-1">Termografía térmica</span>
              </div>

              <!-- Déficit Hídrico -->
              <div class="bg-gray-800/80 p-3 rounded-xl border border-gray-700/60">
                <span class="text-gray-400 block">Déficit Hídrico</span>
                <span class="text-lg font-bold text-cyan-400">{{ hilera.deficitHidricoMm }} mm</span>
                <span class="text-[10px] text-gray-400 block mt-1">Lámina neta estimada</span>
              </div>

              <!-- Válvula de Riego -->
              <div class="col-span-2 bg-gray-800/80 p-3 rounded-xl border border-gray-700/60 flex items-center justify-between">
                <div>
                  <span class="text-gray-400 block">Válvula Inteligente IoT</span>
                  <span class="font-semibold text-white font-mono">{{ hilera.valvulaAsociada }}</span>
                </div>
                <span class="text-xs px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 font-mono">
                  LoRaWAN OK
                </span>
              </div>
            </div>

            <!-- Panel de Notificación de Riego Autorizado -->
            @if (riegoAutorizadoEstado()) {
              <div class="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-xs space-y-1 animate-fade-in">
                <div class="flex items-center gap-2 text-emerald-400 font-bold text-sm">
                  <span>✓ Riego Localizado Autorizado con Éxito</span>
                </div>
                <p class="text-gray-300">
                  Comando enviado a la <strong>{{ hilera.valvulaAsociada }}</strong> por una duración de <strong>{{ hilera.duracionRiegoMin }} minutos</strong>.
                </p>
                <p class="text-emerald-400/80 font-mono text-[11px]">
                  Telemetría actualizada en gemelo 3D y registrada en base de datos.
                </p>
              </div>
            }

            <!-- Footer con Acciones -->
            <div class="flex items-center justify-end gap-3 pt-2">
              <button
                (click)="cerrarModal()"
                class="px-4 py-2.5 rounded-xl text-xs font-semibold text-gray-300 hover:text-white hover:bg-gray-800 transition">
                Cerrar
              </button>

              @if (hilera.estado === 'EstresHidrico' && !riegoAutorizadoEstado()) {
                <button
                  (click)="autorizarRiego(hilera)"
                  [disabled]="riegoEnProceso()"
                  class="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white rounded-xl text-xs font-bold transition shadow-lg shadow-cyan-600/30 flex items-center gap-2">
                  @if (riegoEnProceso()) {
                    <span class="animate-spin">🔄</span>
                    <span>Transmitiendo Orden...</span>
                  } @else {
                    <span>💧 Autorizar Riego Localizado ({{ hilera.duracionRiegoMin }} min)</span>
                  }
                </button>
              }
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    @keyframes fadeIn {
      from { opacity: 0; transform: scale(0.97); }
      to { opacity: 1; transform: scale(1); }
    }
    .animate-fade-in {
      animation: fadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }
  `]
})
export class DigitalTwinComponent implements OnInit, OnDestroy {
  @ViewChild('canvasContainer', { static: true }) canvasContainer!: ElementRef<HTMLDivElement>;

  // Input para permitir coloración por input externo
  @Input() set modo(value: 'salud' | 'sector') {
    this.modoColoracion.set(value);
    this.actualizarColoracionHileras();
  }

  // Evento emitido al hacer clic en hilera con estrés
  @Output() onRowSelected = new EventEmitter<TelemetriaHilera>();
  @Output() onAutorizarRiego = new EventEmitter<TelemetriaHilera>();

  private vitiscanService = inject(VitiScanService);

  // Estados reactivos (Signals)
  modoColoracion = signal<'salud' | 'sector'>('salud');
  hileraModal = signal<TelemetriaHilera | null>(null);
  riegoAutorizadoEstado = signal<boolean>(false);
  riegoEnProceso = signal<boolean>(false);
  autoRotacion = signal<boolean>(false);

  // Three.js Core
  private renderer?: THREE.WebGLRenderer;
  private scene?: THREE.Scene;
  private camera?: THREE.PerspectiveCamera;
  private controls?: OrbitControls;
  private animationFrameId?: number;
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();

  // Gestión de mallas de hileras
  private rowEntries: RowMeshEntry[] = [];
  private interactiveMeshes: THREE.Mesh[] = [];
  private beaconsGroup = new THREE.Group();

  // Control de clic vs arrastre
  private pointerDownPos = { x: 0, y: 0 };
  private boundOnPointerDown = this.onPointerDown.bind(this);
  private boundOnPointerUp = this.onPointerUp.bind(this);
  private boundOnWindowResize = this.onWindowResize.bind(this);

  // Dimensiones del Terreno en Pendiente (Valle Central Tarija)
  private readonly terrainWidth = 84;
  private readonly terrainDepth = 64;

  ngOnInit(): void {
    this.initThree();
  }

  ngOnDestroy(): void {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }

    const container = this.canvasContainer?.nativeElement;
    if (container) {
      container.removeEventListener('pointerdown', this.boundOnPointerDown);
      container.removeEventListener('pointerup', this.boundOnPointerUp);
    }
    window.removeEventListener('resize', this.boundOnWindowResize);

    this.controls?.dispose();
    this.renderer?.dispose();
  }

  // 1. Inicialización de Three.js
  private initThree(): void {
    const container = this.canvasContainer.nativeElement;
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;

    // Escena y Niebla Atmosférica
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0f18);
    this.scene.fog = new THREE.FogExp2(0x0a0f18, 0.012);

    // Cámara Perspectiva
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 500);
    this.camera.position.set(0, 28, 48);

    // Renderer con Antialias y Sombras
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(this.renderer.domElement);

    // OrbitControls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.04; // Evitar pasar por debajo del terreno
    this.controls.minDistance = 12;
    this.controls.maxDistance = 110;
    this.controls.target.set(0, 2, 0);

    // Iluminación Cálida tipo Tarija
    this.setupLighting();

    // Terreno con Relieve y Pendiente
    this.buildSlopedTerrain();

    // Hileras de Viñas Organizadas por Sectores
    this.buildVineyardRows();

    // Grupo para balizas/marcadores luminosos
    this.scene.add(this.beaconsGroup);

    // Listeners para Raycasting interactivo
    container.addEventListener('pointerdown', this.boundOnPointerDown);
    container.addEventListener('pointerup', this.boundOnPointerUp);
    window.addEventListener('resize', this.boundOnWindowResize);

    // Bucle de Renderizado
    this.startAnimationLoop();
  }

  // 2. Iluminación
  private setupLighting(): void {
    const ambientLight = new THREE.AmbientLight(0xdce7f5, 0.65);
    this.scene!.add(ambientLight);

    // Sol de la Tarde en el Valle de Tarija
    const sunLight = new THREE.DirectionalLight(0xfff3d6, 1.4);
    sunLight.position.set(30, 45, 20);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.width = 2048;
    sunLight.shadow.mapSize.height = 2048;
    sunLight.shadow.camera.near = 10;
    sunLight.shadow.camera.far = 120;
    const d = 40;
    sunLight.shadow.camera.left = -d;
    sunLight.shadow.camera.right = d;
    sunLight.shadow.camera.top = d;
    sunLight.shadow.camera.bottom = -d;
    this.scene!.add(sunLight);

    const hemiLight = new THREE.HemisphereLight(0x7ea2d6, 0x223026, 0.5);
    this.scene!.add(hemiLight);
  }

  // 3. Terreno con relieve sutil simulando viñedo en pendiente de Tarija
  private buildSlopedTerrain(): void {
    const segments = 64;
    const geometry = new THREE.PlaneGeometry(this.terrainWidth, this.terrainDepth, segments, segments);

    const pos = geometry.attributes['position'];
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      // La coordenada Z antes de rotar representa la elevación
      const elevation = this.computeElevation(x, -y);
      pos.setZ(i, elevation);
    }
    geometry.computeVertexNormals();

    const terrainMat = new THREE.MeshStandardMaterial({
      color: 0x1e2722, // Tonalidad arcillosa y fértil
      roughness: 0.92,
      metalness: 0.05,
      flatShading: false
    });

    const terrainMesh = new THREE.Mesh(geometry, terrainMat);
    terrainMesh.rotation.x = -Math.PI / 2;
    terrainMesh.receiveShadow = true;
    this.scene!.add(terrainMesh);

    // Rejilla de referencia agronómica sutil
    const grid = new THREE.GridHelper(this.terrainWidth, 28, 0x2e3c35, 0x17211c);
    grid.position.y = 0.05;
    this.scene!.add(grid);
  }

  // Función matemática de elevación del terreno en pendiente
  private computeElevation(x: number, z: number): number {
    // Pendiente natural del valle descendiendo hacia el cauce
    const slope = (z / this.terrainDepth) * 5.8;
    // Ondulaciones topográficas suaves
    const hills = Math.sin(x * 0.09) * 1.1 + Math.cos(z * 0.08) * 0.7;
    return slope + hills;
  }

  // 4. Construcción de Hileras de Viñas por Sectores
  private buildVineyardRows(): void {
    // Definición de Sectores del Viñedo Tarijeño
    const sectoresConfig: Array<{
      nombre: 'Sector A' | 'Sector B' | 'Sector C';
      variedad: string;
      startX: number;
      numHileras: number;
      spacingX: number;
      colorSector: number;
      estadosHileras: EstadoSaludHilera[];
    }> = [
      {
        nombre: 'Sector A',
        variedad: 'Tannat (Lote Norte)',
        startX: -28,
        numHileras: 4,
        spacingX: 4.8,
        colorSector: 0x06b6d4, // Cyan
        estadosHileras: ['Saludable', 'Saludable', 'Saludable', 'Saludable']
      },
      {
        nombre: 'Sector B',
        variedad: 'Syrah (Ladera Central)',
        startX: -8,
        numHileras: 4,
        spacingX: 4.8,
        colorSector: 0x8b5cf6, // Violeta / Púrpura
        // Aquí ubicamos el Estrés Hídrico para el requerimiento
        estadosHileras: ['Saludable', 'EstresHidrico', 'EstresHidrico', 'Saludable']
      },
      {
        nombre: 'Sector C',
        variedad: 'Cabernet Sauvignon (Terraza Sur)',
        startX: 12,
        numHileras: 4,
        spacingX: 4.8,
        colorSector: 0xf59e0b, // Ámbar
        estadosHileras: ['Saludable', 'Lobesia', 'Saludable', 'Saludable']
      }
    ];

    const rowLength = 46;
    const numPosts = 6;
    const postSpacing = rowLength / (numPosts - 1);
    const postGeometry = new THREE.CylinderGeometry(0.09, 0.11, 2.4, 7);
    const postMaterial = new THREE.MeshStandardMaterial({ color: 0x544033, roughness: 0.9 });

    sectoresConfig.forEach((sec, sIdx) => {
      // Letrero 3D de cabecera de Sector
      this.createSectorSign(sec.nombre, sec.startX + (sec.numHileras * sec.spacingX) / 2 - 2.4, -rowLength / 2 - 3);

      for (let h = 0; h < sec.numHileras; h++) {
        const x = sec.startX + h * sec.spacingX;
        const estado = sec.estadosHileras[h] || 'Saludable';
        const hileraId = `H-${sec.nombre.replace('Sector ', '')}${h + 1}`;

        const telemetria: TelemetriaHilera = {
          id: hileraId,
          nombre: `Hilera ${h + 1} - ${sec.nombre}`,
          sector: sec.nombre,
          variedad: sec.variedad,
          estado: estado,
          humedadSuelo: estado === 'EstresHidrico' ? 17.4 : (estado === 'Lobesia' ? 24.1 : 32.8),
          ndvi: estado === 'EstresHidrico' ? 0.41 : (estado === 'Lobesia' ? 0.52 : 0.78),
          temperaturaCanopia: estado === 'EstresHidrico' ? 31.8 : 26.2,
          deficitHidricoMm: estado === 'EstresHidrico' ? 16.5 : 3.0,
          valvulaAsociada: `Válvula 0${sIdx + 1}-R0${h + 1} (${sec.nombre})`,
          duracionRiegoMin: 45
        };

        // 1. Postes Guía de Madera y Alambres tensores
        for (let p = 0; p < numPosts; p++) {
          const z = -rowLength / 2 + p * postSpacing;
          const y = this.computeElevation(x, z);

          const post = new THREE.Mesh(postGeometry, postMaterial);
          post.position.set(x, y + 1.2, z);
          post.castShadow = true;
          this.scene!.add(post);
        }

        // Alambres tensores (espaldera)
        const wireGeo = new THREE.BoxGeometry(0.03, 0.03, rowLength);
        const wireMat = new THREE.MeshBasicMaterial({ color: 0x94a3b8 });
        const wireY = this.computeElevation(x, 0) + 1.7;
        const wire = new THREE.Mesh(wireGeo, wireMat);
        wire.position.set(x, wireY, 0);
        this.scene!.add(wire);

        // 2. Masa Vegetal / Follaje Modular de la Hilera
        const rowVegetation = this.createVineRowMesh(x, rowLength, telemetria, sec.colorSector);
        this.scene!.add(rowVegetation);

        // 3. Si la hilera tiene estrés o plaga, agregar baliza holográfica flotante
        if (estado === 'EstresHidrico' || estado === 'Lobesia') {
          this.createAlertBeacon(x, 0, estado, telemetria.id);
        }
      }
    });
  }

  // Generador de la Malla Modular de la Hilera
  private createVineRowMesh(x: number, length: number, telemetria: TelemetriaHilera, colorSector: number): THREE.Mesh {
    // Malla modular alargada para la hilera
    const geometry = new THREE.BoxGeometry(1.2, 1.3, length, 1, 1, 12);

    // Ajustar los vértices a la curvatura del terreno
    const pos = geometry.attributes['position'];
    for (let i = 0; i < pos.count; i++) {
      const zWorld = pos.getZ(i);
      const terrainY = this.computeElevation(x, zWorld);
      pos.setY(i, pos.getY(i) + terrainY + 1.25);
    }
    geometry.computeVertexNormals();

    // Material por Salud (Verde = Saludable, Amarillo = Estrés Hídrico, Rojo = Lobesia)
    let colorSalud = 0x10b981; // Verde
    let emissiveColor = 0x000000;

    if (telemetria.estado === 'EstresHidrico') {
      colorSalud = 0xf59e0b; // Amarillo / Naranja
      emissiveColor = 0x452200;
    } else if (telemetria.estado === 'Lobesia') {
      colorSalud = 0xef4444; // Rojo
      emissiveColor = 0x3d0a0a;
    }

    const materialSalud = new THREE.MeshStandardMaterial({
      color: colorSalud,
      emissive: emissiveColor,
      roughness: 0.65,
      metalness: 0.1
    });

    const materialSector = new THREE.MeshStandardMaterial({
      color: colorSector,
      roughness: 0.65,
      metalness: 0.1
    });

    const mesh = new THREE.Mesh(geometry, materialSalud);
    mesh.position.set(x, 0, 0);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = { telemetria };

    // Registrar para interactividad
    const entry: RowMeshEntry = {
      mesh,
      telemetria,
      originalMaterials: {
        salud: materialSalud,
        sector: materialSector
      }
    };
    this.rowEntries.push(entry);
    this.interactiveMeshes.push(mesh);

    return mesh;
  }

  // Baliza holográfica sobre hileras críticas
  private createAlertBeacon(x: number, z: number, estado: EstadoSaludHilera, rowId: string): void {
    const beaconColor = estado === 'EstresHidrico' ? 0xf59e0b : 0xef4444;
    const coneGeo = new THREE.ConeGeometry(0.8, 2.2, 5);
    const coneMat = new THREE.MeshBasicMaterial({ color: beaconColor, wireframe: true });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.rotation.x = Math.PI;

    const terrainY = this.computeElevation(x, z);
    cone.position.set(x, terrainY + 4.8, z);
    cone.name = `beacon_${rowId}`;

    this.beaconsGroup.add(cone);
  }

  // Rótulo 3D para Sectores
  private createSectorSign(texto: string, x: number, z: number): void {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.fillStyle = '#0f172a';
    ctx.roundRect(0, 0, 256, 64, 12);
    ctx.fill();

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 4;
    ctx.roundRect(0, 0, 256, 64, 12);
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 24px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(texto, 128, 32);

    const texture = new THREE.CanvasTexture(canvas);
    const signMat = new THREE.MeshBasicMaterial({ map: texture, transparent: true });
    const signGeo = new THREE.PlaneGeometry(6, 1.5);
    const sign = new THREE.Mesh(signGeo, signMat);

    const y = this.computeElevation(x, z);
    sign.position.set(x, y + 3.2, z);
    this.scene!.add(sign);
  }

  // 5. Alternar la coloración mediante Input o Estado
  setModoColoracion(nuevoModo: 'salud' | 'sector'): void {
    this.modoColoracion.set(nuevoModo);
    this.actualizarColoracionHileras();
  }

  private actualizarColoracionHileras(): void {
    const modo = this.modoColoracion();
    this.rowEntries.forEach(entry => {
      entry.mesh.material = modo === 'salud'
        ? entry.originalMaterials.salud
        : entry.originalMaterials.sector;
    });
  }

  // 6. Interacción Raycaster al hacer Clic en Hilera
  private onPointerDown(e: MouseEvent): void {
    this.pointerDownPos = { x: e.clientX, y: e.clientY };
  }

  private onPointerUp(e: MouseEvent): void {
    // Si hubo arrastre mayor a 6 píxeles, es una rotación orbital, no un clic
    const dist = Math.hypot(e.clientX - this.pointerDownPos.x, e.clientY - this.pointerDownPos.y);
    if (dist > 6) return;

    const container = this.canvasContainer.nativeElement;
    const rect = container.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera!);
    const intersects = this.raycaster.intersectObjects(this.interactiveMeshes, false);

    if (intersects.length > 0) {
      const selectedMesh = intersects[0].object as THREE.Mesh;
      const telemetria: TelemetriaHilera = selectedMesh.userData['telemetria'];

      if (telemetria) {
        // Notificar selección
        this.onRowSelected.emit(telemetria);

        // Abrir modal especialmente si tiene estrés hídrico o anomalía
        this.abrirModalHilera(telemetria);
      }
    }
  }

  abrirModalHilera(hilera: TelemetriaHilera): void {
    this.hileraModal.set(hilera);
    this.riegoAutorizadoEstado.set(false);
    this.riegoEnProceso.set(false);
  }

  cerrarModal(): void {
    this.hileraModal.set(null);
  }

  // 7. Acción: Autorizar Riego Localizado
  autorizarRiego(hilera: TelemetriaHilera): void {
    this.riegoEnProceso.set(true);

    // Simular comunicación IoT LoRaWAN hacia la válvula
    setTimeout(() => {
      this.riegoEnProceso.set(false);
      this.riegoAutorizadoEstado.set(true);

      // Actualizar estado de la hilera a recuperación/irrigado
      hilera.estado = 'Saludable';
      hilera.humedadSuelo = 38.5;
      hilera.ndvi = 0.68;
      hilera.riegoActivo = true;

      // Actualizar visualmente en el Gemelo 3D
      const entry = this.rowEntries.find(r => r.telemetria.id === hilera.id);
      if (entry) {
        const materialVerde = new THREE.MeshStandardMaterial({
          color: 0x10b981,
          emissive: 0x053321,
          roughness: 0.65
        });
        entry.originalMaterials.salud = materialVerde;
        if (this.modoColoracion() === 'salud') {
          entry.mesh.material = materialVerde;
        }

        // Remover baliza holográfica de alerta
        const beacon = this.beaconsGroup.getObjectByName(`beacon_${hilera.id}`);
        if (beacon) {
          this.beaconsGroup.remove(beacon);
        }
      }

      // Notificar al servicio o componentes padres
      this.onAutorizarRiego.emit(hilera);
      this.vitiscanService.aprobarOrden(1).subscribe();
    }, 1200);
  }

  // 8. Controles de Cámara Auxiliares
  resetCamara(): void {
    this.camera?.position.set(0, 28, 48);
    this.controls?.target.set(0, 2, 0);
    this.controls?.update();
  }

  vistaCenital(): void {
    this.camera?.position.set(0, 68, 0.1);
    this.controls?.target.set(0, 0, 0);
    this.controls?.update();
  }

  toggleAutoRotacion(): void {
    this.autoRotacion.update(v => !v);
    if (this.controls) {
      this.controls.autoRotate = this.autoRotacion();
      this.controls.autoRotateSpeed = 1.2;
    }
  }

  private onWindowResize(): void {
    const container = this.canvasContainer?.nativeElement;
    if (!container || !this.renderer || !this.camera) return;

    const w = container.clientWidth;
    const h = container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  // 9. Loop de Animación
  private startAnimationLoop(): void {
    const animate = () => {
      this.animationFrameId = requestAnimationFrame(animate);

      this.controls?.update();

      // Animación oscilante de las balizas holográficas de advertencia
      const time = Date.now() * 0.003;
      this.beaconsGroup.children.forEach(b => {
        b.rotation.y += 0.02;
        b.position.y += Math.sin(time) * 0.008;
      });

      this.renderer?.render(this.scene!, this.camera!);
    };

    animate();
  }
}
