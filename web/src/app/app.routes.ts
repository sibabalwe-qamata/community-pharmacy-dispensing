import { Routes } from '@angular/router';

/**
 * Four views, each lazily loaded so a route change only pulls in what it needs.
 * Search, ledger and filter state live in query params, so every view is linkable
 * and survives a reload.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'medicines' },
  {
    path: 'medicines',
    title: 'Medicines',
    loadComponent: () => import('./features/medicines/medicine-search').then((m) => m.MedicineSearch),
  },
  {
    path: 'medicines/:code',
    title: 'Medicine detail',
    loadComponent: () => import('./features/medicines/medicine-detail').then((m) => m.MedicineDetail),
  },
  {
    path: 'dispense',
    title: 'Capture dispense',
    loadComponent: () => import('./features/dispense/dispense-capture').then((m) => m.DispenseCapture),
  },
  {
    path: 'patients',
    title: 'Patient ledger',
    loadComponent: () => import('./features/ledger/patient-ledger').then((m) => m.PatientLedger),
  },
  { path: '**', redirectTo: 'medicines' },
];
