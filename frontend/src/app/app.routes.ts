import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard/dashboard.component';
import { DigitalTwinComponent } from './digital-twin/digital-twin.component';
import { FlightMonitorComponent } from './flight-monitor/flight-monitor.component';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent, title: 'Dashboard | VitiScan Tarija' },
  { path: 'digital-twin', component: DigitalTwinComponent, title: 'Gemelo Digital 3D | VitiScan Tarija' },
  { path: 'flight-monitor', component: FlightMonitorComponent, title: 'Monitor de Vuelo | VitiScan Tarija' },
  { path: '**', redirectTo: 'dashboard' }
];
