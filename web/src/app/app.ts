import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header>
      <h1>EMGuidance Formulary</h1>
      <nav>
        <a routerLink="/medicines" routerLinkActive="active">Medicines</a>
        <a routerLink="/dispense" routerLinkActive="active">Capture dispense</a>
        <a routerLink="/patients" routerLinkActive="active">Patient ledger</a>
      </nav>
    </header>
    <main>
      <router-outlet />
    </main>
  `,
  styles: `
    header {
      border-bottom: 1px solid var(--line);
      margin-bottom: 1.5rem;
    }
    h1 {
      font-size: 1.25rem;
      margin: 0 0 0.5rem;
    }
    nav {
      display: flex;
      gap: 1rem;
      padding-bottom: 0.75rem;
    }
    a.active {
      font-weight: 600;
      text-decoration: underline;
    }
  `,
})
export class App {}
