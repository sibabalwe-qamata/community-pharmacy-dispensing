import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { EMPTY, catchError, switchMap, tap } from 'rxjs';

import { Dispense, Page, Problem } from '../../core/api.types';
import { DispensesApi } from '../../core/dispenses-api';
import { isProblem } from '../../core/problem';

/** How many rows one page asks the API for. The API echoes back the actual page_size. */
const PAGE_SIZE = 20;

type ViewState = 'empty-filter' | 'loading' | 'error' | 'empty-results' | 'results';

/**
 * Patient dispense ledger. `patient_ref` (required) and `medicine_code` (optional) live
 * in the URL query params, alongside `cursor` — the app's router is configured with
 * withComponentInputBinding(), so those params arrive here as plain signal inputs and
 * this view never needs its own filter service. The URL is the only source of truth:
 * typing into the filter fields or clicking Next/Back both just navigate, and whatever
 * comes back in as inputs is what gets fetched and rendered.
 */
@Component({
  selector: 'app-patient-ledger',
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h2>Patient ledger</h2>

      <form (submit)="onSubmit($event)">
        <label>
          <span>Patient ref</span>
          <input
            type="text"
            name="patient_ref"
            [value]="patientRefDraft()"
            (input)="onPatientRefInput($event)"
            placeholder="PT-00001"
            required
          />
        </label>
        <label>
          <span>Medicine code (optional)</span>
          <input
            type="text"
            name="medicine_code"
            [value]="medicineCodeDraft()"
            (input)="onMedicineCodeInput($event)"
          />
        </label>
        <button type="submit">Apply</button>
      </form>

      @switch (viewState()) {
        @case ('empty-filter') {
          <p class="muted">Enter a patient ref above to see their dispense ledger.</p>
        }
        @case ('loading') {
          <p class="muted">Loading…</p>
        }
        @case ('error') {
          <div class="problem">
            <h3>{{ problem()!.title }}</h3>
            <p>{{ problem()!.detail }}</p>
          </div>
        }
        @case ('empty-results') {
          <p class="muted">No dispenses for this patient.</p>
        }
        @case ('results') {
          <table>
            <thead>
              <tr>
                <!--
                  The API stores dispensed_at as a UTC instant; this renders it in the
                  viewer's local browser timezone. The pharmacy's business timezone is
                  Africa/Johannesburg, so a rendered local time can differ from the
                  business date the dispense rules were actually evaluated against.
                -->
                <th>Dispensed at</th>
                <th>Medicine</th>
                <th>Quantity</th>
                <th>Authorisation ref</th>
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              @for (dispense of items(); track dispense.id) {
                <tr>
                  <td>{{ dispense.dispensed_at | date: 'medium' }}</td>
                  <td>{{ dispense.medicine_code }}</td>
                  <td>{{ dispense.quantity }}</td>
                  <td>{{ dispense.authorisation_ref ?? '—' }}</td>
                  <td>{{ dispense.rule_id }}</td>
                </tr>
              }
            </tbody>
          </table>
        }
      }

      @if (page()) {
        <div class="pager">
          <!--
            Back is client-side: keyset cursors only move forward, so the API gives us no
            way to ask for "the page before this one". Instead we keep a stack of the
            cursors we navigated through in this browsing session and pop it to go back.
          -->
          <button type="button" (click)="back()" [disabled]="!canGoBack()">Back</button>
          <button type="button" (click)="next()" [disabled]="!nextCursor()">Next</button>
          <span class="muted">Page size: {{ page()!.page_size }}</span>
        </div>
      }
    </section>
  `,
  styles: `
    form {
      display: flex;
      align-items: flex-end;
      gap: 1rem;
      flex-wrap: wrap;
      margin-bottom: 1.25rem;
    }

    form label {
      margin-bottom: 0;
      min-width: 12rem;
    }

    form button {
      height: 2.25rem;
    }
  `,
})
export class PatientLedger {
  private readonly dispensesApi = inject(DispensesApi);
  private readonly router = inject(Router);

  // Query params, bound as inputs by withComponentInputBinding() in app.config.ts.
  readonly patient_ref = input<string | null>(null);
  readonly medicine_code = input<string | null>(null);
  readonly cursor = input<string | null>(null);

  // Text the user is currently typing, kept separate from the applied (URL) filters so
  // typing doesn't fetch on every keystroke — only Apply navigates.
  protected readonly patientRefDraft = signal('');
  protected readonly medicineCodeDraft = signal('');

  protected readonly page = signal<Page<Dispense> | null>(null);
  protected readonly loading = signal(false);
  protected readonly problem = signal<Problem | null>(null);

  // Cursors visited in this browsing session, most recent last. Reset whenever the
  // filters (not the cursor) change, since a new filter starts a new keyset walk.
  private readonly cursorStack = signal<(string | null)[]>([]);
  private lastFilters: { patientRef: string | null; medicineCode: string | null } | null = null;

  protected readonly items = computed(() => this.page()?.items ?? []);
  protected readonly nextCursor = computed(() => this.page()?.next_cursor ?? null);
  protected readonly canGoBack = computed(() => this.cursorStack().length > 0);

  private readonly appliedFilters = computed(() => ({
    patientRef: this.patient_ref()?.trim() || null,
    medicineCode: this.medicine_code()?.trim() || null,
    cursor: this.cursor() || null,
  }));

  protected readonly viewState = computed<ViewState>(() => {
    if (!this.appliedFilters().patientRef) return 'empty-filter';
    if (this.loading()) return 'loading';
    if (this.problem()) return 'error';
    return this.items().length > 0 ? 'results' : 'empty-results';
  });

  constructor() {
    // Keep the draft fields in step with the URL (initial load, a link in from dispense
    // capture, or the user navigating browser history) without fighting live typing.
    effect(() => {
      this.patientRefDraft.set(this.patient_ref() ?? '');
      this.medicineCodeDraft.set(this.medicine_code() ?? '');
    });

    // Reset the back-stack whenever the applied filters change, not merely the cursor.
    effect(() => {
      const { patientRef, medicineCode } = this.appliedFilters();
      const changed =
        this.lastFilters === null ||
        this.lastFilters.patientRef !== patientRef ||
        this.lastFilters.medicineCode !== medicineCode;
      if (changed) {
        this.lastFilters = { patientRef, medicineCode };
        this.cursorStack.set([]);
      }
    });

    // switchMap cancels an in-flight request if the filters/cursor change again before
    // it resolves, so a slow first response can never clobber a newer one.
    toObservable(this.appliedFilters)
      .pipe(
        switchMap(({ patientRef, medicineCode, cursor }) => {
          if (!patientRef) {
            this.page.set(null);
            this.problem.set(null);
            this.loading.set(false);
            return EMPTY;
          }
          this.loading.set(true);
          this.problem.set(null);
          this.page.set(null);
          return this.dispensesApi.list({ patient_ref: patientRef, medicine_code: medicineCode }, PAGE_SIZE, cursor).pipe(
            tap((page) => {
              this.page.set(page);
              this.loading.set(false);
            }),
            catchError((err: unknown) => {
              this.page.set(null);
              this.problem.set(
                isProblem(err)
                  ? err
                  : {
                      type: 'about:blank',
                      title: 'Request failed',
                      status: 0,
                      detail: 'Something went wrong loading this ledger.',
                      code: 'UNKNOWN_ERROR',
                    },
              );
              this.loading.set(false);
              return EMPTY;
            }),
          );
        }),
        takeUntilDestroyed(),
      )
      .subscribe();
  }

  protected onPatientRefInput(event: Event): void {
    this.patientRefDraft.set((event.target as HTMLInputElement).value);
  }

  protected onMedicineCodeInput(event: Event): void {
    this.medicineCodeDraft.set((event.target as HTMLInputElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();
    this.navigate({
      patient_ref: this.patientRefDraft().trim() || null,
      medicine_code: this.medicineCodeDraft().trim() || null,
      cursor: null,
    });
  }

  protected next(): void {
    const target = this.nextCursor();
    if (!target) return;
    this.cursorStack.update((stack) => [...stack, this.cursor() || null]);
    this.navigate({ cursor: target });
  }

  protected back(): void {
    const stack = this.cursorStack();
    if (!stack.length) return;
    const previous = stack[stack.length - 1];
    this.cursorStack.set(stack.slice(0, -1));
    this.navigate({ cursor: previous });
  }

  private navigate(queryParams: Record<string, string | null>): void {
    void this.router.navigate([], {
      queryParams,
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
