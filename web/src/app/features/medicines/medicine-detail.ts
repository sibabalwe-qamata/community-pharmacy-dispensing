import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { MedicinesApi } from '../../core/medicines-api';
import { MedicineDetailDto, Problem, Rule, RuleHistory } from '../../core/api.types';

/**
 * Medicine detail, route `/medicines/:code`.
 *
 * `code` arrives as an input via `withComponentInputBinding()` (bound from the `:code`
 * route param). Loads the medicine and its rule history side by side and renders the
 * history as a timeline, oldest first.
 */
@Component({
  selector: 'app-medicine-detail',
  standalone: true,
  imports: [RouterLink],
  template: `
    <section>
      <p><a [routerLink]="['/medicines']">&larr; Back to search</a></p>

      @if (loading()) {
        <p class="muted">Loading…</p>
      } @else if (error(); as problem) {
        <div class="problem">
          <h3>{{ problem.title }}</h3>
          <p>{{ problem.detail }}</p>
        </div>
      } @else if (medicine(); as med) {
        <header>
          <h2>
            {{ med.name }}
            <span class="muted">({{ med.code }})</span>
            @if (!med.is_active) {
              <span class="badge">inactive</span>
            }
          </h2>
          <p class="muted">{{ med.form }} &middot; {{ med.strength_value }} {{ med.strength_unit }}</p>
        </header>

        @if (!med.current_rule) {
          <p class="muted">No rule is currently in force for this medicine.</p>
        }

        <h3>Rule history</h3>
        @if (rules().length) {
          <table>
            <thead>
              <tr>
                <th>Effective period</th>
                <th>Max per dispense</th>
                <th>Max per 30 days</th>
                <th>Authorisation required</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <!--
                effective_to is exclusive: a period ending 2024-01-01 and the next one
                starting 2024-01-01 are back-to-back, not overlapping.
              -->
              @for (rule of rules(); track rule.id) {
                <tr>
                  <td>{{ rule.effective_from }} &rarr; {{ rule.effective_to ?? 'open-ended' }}</td>
                  <td>{{ rule.max_quantity_per_dispense }}</td>
                  <td>{{ rule.max_quantity_per_30_days }}</td>
                  <td>{{ rule.requires_authorisation ? 'Yes' : 'No' }}</td>
                  <td>
                    @if (rule.id === inForceRuleId()) {
                      <span class="badge in-force">in force now</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        } @else {
          <p class="muted">No rule history recorded for this medicine.</p>
        }

        <p>
          <a [routerLink]="['/dispense']" [queryParams]="{ medicine_code: code() }">Dispense this medicine</a>
        </p>
      }
    </section>
  `,
  styles: `
    :host {
      display: block;
    }
  `,
})
export class MedicineDetail {
  private readonly api = inject(MedicinesApi);

  /** Bound from the `:code` route param by withComponentInputBinding. */
  readonly code = input.required<string>();

  readonly medicine = signal<MedicineDetailDto | null>(null);
  readonly ruleHistory = signal<RuleHistory | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Problem | null>(null);

  /** Oldest first, per the API contract (MedicinesApi.rules). */
  readonly rules = computed<Rule[]>(() => this.ruleHistory()?.items ?? []);
  readonly inForceRuleId = computed(() => this.ruleHistory()?.in_force_rule_id ?? null);

  constructor() {
    effect(() => {
      const code = this.code();
      untracked(() => this.load(code));
    });
  }

  private load(code: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.medicine.set(null);
    this.ruleHistory.set(null);

    forkJoin({
      medicine: this.api.get(code),
      rules: this.api.rules(code),
    }).subscribe({
      next: ({ medicine, rules }) => {
        this.medicine.set(medicine);
        this.ruleHistory.set(rules);
        this.loading.set(false);
      },
      error: (problem: Problem) => {
        this.error.set(problem);
        this.loading.set(false);
      },
    });
  }
}
