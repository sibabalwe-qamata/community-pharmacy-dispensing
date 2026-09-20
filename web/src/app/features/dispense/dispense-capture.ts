import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { Dispense, DispenseCreate, Problem } from '../../core/api.types';
import { DispensesApi, newIdempotencyKey } from '../../core/dispenses-api';
import { unattachedViolations, violationsFor } from '../../core/problem';

/** The five request fields, also the five form control names — kept in one place so
 * "which violations are unattached" and "which controls exist" can never drift apart. */
const KNOWN_FIELDS = ['medicine_code', 'patient_ref', 'quantity', 'dispensed_at', 'authorisation_ref'] as const;

type CaptureStatus = 'idle' | 'submitting' | 'succeeded' | 'rejected';

@Component({
  selector: 'app-dispense-capture',
  imports: [ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h2>Capture dispense</h2>

      @if (problem(); as p) {
        <div class="problem">
          <h3>{{ p.title }}</h3>
          <p>{{ p.detail }}</p>
          @for (v of unownedErrors(); track v.code + '|' + v.field + '|' + v.message) {
            <p class="field-error">{{ v.message }} <span class="muted">({{ v.code }})</span></p>
          }
        </div>
      }

      @if (created(); as dispense) {
        <div class="success">
          <p>
            Dispense #{{ dispense.id }} recorded — quantity {{ dispense.quantity }}, validated against rule #{{
              dispense.rule_id
            }}.
          </p>
          <p>
            <a [routerLink]="['/patients']" [queryParams]="{ patient_ref: dispense.patient_ref }">View patient ledger</a>
          </p>
          <button type="button" (click)="startNewCapture()">Capture another</button>
        </div>
      }

      <form [formGroup]="form" (ngSubmit)="submit()">
        <label>
          <span>Medicine code</span>
          <input type="text" formControlName="medicine_code" [class.invalid]="medicineCodeErrors().length > 0" />
          @for (v of medicineCodeErrors(); track v.code + '|' + v.message) {
            <p class="field-error">{{ v.message }}</p>
          }
        </label>

        <label>
          <span>Patient reference</span>
          <input type="text" formControlName="patient_ref" [class.invalid]="patientRefErrors().length > 0" />
          @for (v of patientRefErrors(); track v.code + '|' + v.message) {
            <p class="field-error">{{ v.message }}</p>
          }
        </label>

        <label>
          <span>Quantity</span>
          <input type="number" min="1" step="1" formControlName="quantity" [class.invalid]="quantityErrors().length > 0" />
          @for (v of quantityErrors(); track v.code + '|' + v.message) {
            <p class="field-error">{{ v.message }}</p>
          }
        </label>

        <label>
          <span>Dispensed at</span>
          <input type="datetime-local" formControlName="dispensed_at" [class.invalid]="dispensedAtErrors().length > 0" />
          @for (v of dispensedAtErrors(); track v.code + '|' + v.message) {
            <p class="field-error">{{ v.message }}</p>
          }
        </label>

        <label>
          <span>Authorisation reference (optional)</span>
          <input
            type="text"
            formControlName="authorisation_ref"
            [class.invalid]="authorisationRefErrors().length > 0"
          />
          @for (v of authorisationRefErrors(); track v.code + '|' + v.message) {
            <p class="field-error">{{ v.message }}</p>
          }
        </label>

        <button type="submit" [disabled]="submitting()">
          {{ submitting() ? 'Submitting…' : 'Capture dispense' }}
        </button>
      </form>
    </section>
  `,
  styles: `
    form {
      max-width: 28rem;
    }
  `,
})
export class DispenseCapture {
  private readonly fb = inject(FormBuilder);
  private readonly dispensesApi = inject(DispensesApi);

  /** Query param from the medicine detail view's link here (?medicine_code=...), bound
   * automatically by the router's withComponentInputBinding — no ActivatedRoute needed. */
  readonly medicine_code = input<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    medicine_code: ['', Validators.required],
    patient_ref: ['', Validators.required],
    quantity: [1, [Validators.required, Validators.min(1)]],
    dispensed_at: ['', Validators.required],
    authorisation_ref: [''],
  });

  // --- State: exactly one of these describes "what's happening right now". ---
  private readonly status = signal<CaptureStatus>('idle');
  protected readonly problem = signal<Problem | null>(null);
  protected readonly created = signal<Dispense | null>(null);

  /** True once a submit has failed and the user hasn't yet edited the form since. Drives
   * the valueChanges watch below that retires a spent-but-rejected key on the next edit. */
  private readonly attemptedFailedSubmit = signal(false);

  /**
   * One idempotency key per capture attempt. Created once here, reused across retries of
   * the same submission (network error, or pressing submit again with the same body) so
   * the API replays the original outcome instead of double-dispensing. It only moves
   * forward on a 201 (this.created.set(...)) or an explicit new-capture (startNewCapture()),
   * plus the edit-after-rejection case handled in the constructor below.
   */
  private readonly idempotencyKey = signal(newIdempotencyKey());

  readonly submitting = computed(() => this.status() === 'submitting');

  readonly medicineCodeErrors = computed(() => violationsFor(this.problem(), 'medicine_code'));
  readonly patientRefErrors = computed(() => violationsFor(this.problem(), 'patient_ref'));
  readonly quantityErrors = computed(() => violationsFor(this.problem(), 'quantity'));
  readonly dispensedAtErrors = computed(() => violationsFor(this.problem(), 'dispensed_at'));
  readonly authorisationRefErrors = computed(() => violationsFor(this.problem(), 'authorisation_ref'));

  /** Violations that own no control — MEDICINE_INACTIVE, NO_RULE_IN_FORCE, and friends —
   * shown in the top panel so a rejection never silently drops a reason. */
  readonly unownedErrors = computed(() => unattachedViolations(this.problem(), KNOWN_FIELDS));

  constructor() {
    // Prefill from the ?medicine_code= query param once it arrives (it may not be present
    // at construction time yet, hence an effect rather than a one-off constructor read).
    effect(() => {
      const code = this.medicine_code();
      if (code) {
        this.form.controls.medicine_code.setValue(code);
      }
    });

    // Editing the form after a failed submit must retire the rejected attempt's key: the
    // API replays a repeated key with the SAME body, but answers a repeated key with a
    // DIFFERENT body with a 422 IDEMPOTENCY_KEY_REUSED. So the first edit after a rejection
    // gets a fresh key; further edits before the next submit don't need another one.
    this.form.valueChanges.pipe(takeUntilDestroyed()).subscribe(() => {
      if (this.attemptedFailedSubmit() && this.status() !== 'submitting') {
        this.idempotencyKey.set(newIdempotencyKey());
        this.attemptedFailedSubmit.set(false);
      }
    });
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    // A fresh attempt starts with a clean slate — stale violations from a previous
    // rejection must never sit under this attempt's fields.
    this.problem.set(null);
    this.status.set('submitting');

    const raw = this.form.getRawValue();
    const body: DispenseCreate = {
      medicine_code: raw.medicine_code.trim(),
      patient_ref: raw.patient_ref.trim(),
      quantity: raw.quantity,
      // datetime-local gives a LOCAL string with no offset (e.g. "2026-09-20T14:30"). The
      // API rejects a naive timestamp, so this is a deliberate conversion, not an
      // incidental one: `new Date(...)` parses that string as the browser's local time,
      // and `.toISOString()` re-serializes that same instant in UTC with a trailing "Z".
      dispensed_at: new Date(raw.dispensed_at).toISOString(),
      authorisation_ref: raw.authorisation_ref.trim() === '' ? null : raw.authorisation_ref.trim(),
    };

    this.dispensesApi.create(body, this.idempotencyKey()).subscribe({
      next: (dispense) => {
        this.created.set(dispense);
        this.status.set('succeeded');
        this.attemptedFailedSubmit.set(false);
        // This capture is done and its key is spent — the next one gets its own, right
        // away, not on the user's next edit.
        this.idempotencyKey.set(newIdempotencyKey());
      },
      error: (err: Problem) => {
        this.problem.set(err);
        this.status.set('rejected');
        // Keep the same key: a bare retry (network blip, or pressing submit again with an
        // unchanged body) should replay, not double-dispense. See the valueChanges
        // subscription above for what happens the moment the user actually edits.
        this.attemptedFailedSubmit.set(true);
      },
    });
  }

  startNewCapture(): void {
    this.form.reset({
      medicine_code: '',
      patient_ref: '',
      quantity: 1,
      dispensed_at: '',
      authorisation_ref: '',
    });
    this.created.set(null);
    this.problem.set(null);
    this.status.set('idle');
    this.attemptedFailedSubmit.set(false);
    this.idempotencyKey.set(newIdempotencyKey());
  }
}
