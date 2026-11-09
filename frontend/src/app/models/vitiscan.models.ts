export interface Parcela {
  id: number;
  nombre: string;
  subcentral: string;
  coordenadasGeoJson: string;
  estadoSalud: 'Optimo' | 'Bueno' | 'Regular' | 'Critico';
}

export interface MisionVuelo {
  id: number;
  parcelaId: number;
  parcela?: Parcela;
  fechaHora: string;
  estado: 'Pendiente' | 'Procesando' | 'Completada';
  detecciones?: Deteccion[];
}

export interface Deteccion {
  id?: number;
  misionVueloId: number;
  coordenadasPunto: string;
  tipoProblema: 'EstresHidrico' | 'LobesiaBotrana' | 'Ninguno';
  severidad: number; // 0-100
  confianza: number; // 0.0 - 1.0
  imagenUrl: string;
}

export interface OrdenRiego {
  id?: number;
  parcelaId: number;
  parcela?: Parcela;
  sectorValvula: string;
  duracionMinutos: number;
  estado: 'PendienteAprobacion' | 'Ejecutado';
  aprobadoPorHumano: boolean;
}
