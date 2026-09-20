import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, debounceTime, distinctUntilChanged } from 'rxjs';

import { MedicinesApi } from '../../core/medicines-api';
import { MedicineSummary, Problem } from '../../core/api.types';

const PAGE_SIZE = 20;

/**
 * Medicine search, route `/medicines`.
 *
 * The search term and the pagination cursor live in the URL (`q`, `cursor`), not in a
 * service: `withComponentInputBinding()` feeds them in here as inputs, and every
 * navigation writes them back with `Router.navigate`. That makes the view linkable and
 * lets it survive a reload — there is no other source of truth for "what page am I on".
 */
@Component({
  selector: 'app-medicine-search',
  standalone: true,
  imports: [RouterLink],
  template: `
    <section>
      <h2>Medicines</h2>

      <label>
        <span>Search by name or code</span>
        <input
          type="search"
          placeholder="e.g. paracetamol or PARA500"
          [value]="searchText()"
          (input)="onSearchInput($any($event.target).value)"
        />
      </label>

      @if (loading()) {
        <p class="muted">Loading…</p>
      } @else if (error(); as problem) {
        <div class="problem">
          <h3>{{ problem.title }}</h3>
          <p>{{ problem.detail }}</p>
        </div>
      } @else if (results().length === 0) {
        <p class="muted">No medicines match.</p>
      } @else {
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Form</th>
              <th>Strength</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (item of results(); track item.code) {
              <tr>
                <td><a [routerLink]="['/medicines', item.code]">{{ item.code }}</a></td>
                <td>{{ item.name }}</td>
                <td>{{ item.form }}</td>
                <td>{{ item.strength_value }} {{ item.strength_unit }}</td>
                <td>
                  @if (!item.is_active) {
                    <span class="badge">inactive</span>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      }

      <div class="pager">
        <!--
          Back is client-side: the API's cursor is a keyset ("give me items after X") and
          only ever points forward, so there is no "previous cursor" to ask the server for.
          We keep a stack of cursors we have already navigated through and pop it to go back.
        -->
        <button type="button" (click)="goBack()" [disabled]="!canGoBack()">Back</button>
        <button type="button" (click)="goNext()" [disabled]="!nextCursor() || loading()">Next</button>
      </div>
    </section>
  `,
  styles: `
    :host {
      display: block;
    }
  `,
})
export class MedicineSearch {
  private readonly api = inject(MedicinesApi);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** Bound from the `q` query param by withComponentInputBinding. */
  readonly q = input<string>();
  /** Bound from the `cursor` query param by withComponentInputBinding. */
  readonly cursor = input<string>();

  readonly searchText = signal('');
  private readonly searchInput$ = new Subject<string>();

  readonly results = signal<MedicineSummary[]>([]);
  readonly nextCursor = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal<Problem | null>(null);

  /** Cursors of pages already visited for the current search term, most recent last. */
  private readonly cursorStack = signal<(string | null)[]>([]);
  readonly canGoBack = computed(() => this.cursorStack().length > 0);

  constructor() {
    // Keep the text box in sync with the URL (initial load, back/forward navigation),
    // without fighting the user while they are typing.
    effect(() => {
      const urlQ = this.q() ?? '';
      untracked(() => {
        if (this.searchText() !== urlQ) {
          this.searchText.set(urlQ);
        }
      });
    });

    // A fresh search term invalidates any cursors collected for the previous term.
    let seenQ = false;
    let lastQ: string | undefined;
    effect(() => {
      const currentQ = this.q();
      untracked(() => {
        if (seenQ && currentQ !== lastQ) {
          this.cursorStack.set([]);
        }
        seenQ = true;
        lastQ = currentQ;
      });
    });

    // The URL is the only trigger for loading data.
    effect(() => {
      const q = this.q() ?? null;
      const cursor = this.cursor() ?? null;
      untracked(() => this.load(q, cursor));
    });

    this.searchInput$
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed())
      .subscribe((value) => {
        void this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { q: value.trim() ? value : null, cursor: null },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      });
  }

  onSearchInput(value: string): void {
    this.searchText.set(value);
    this.searchInput$.next(value);
  }

  goNext(): void {
    const next = this.nextCursor();
    if (!next) {
      return;
    }
    this.cursorStack.update((stack) => [...stack, this.cursor() ?? null]);
    this.navigateToCursor(next);
  }

  goBack(): void {
    const stack = this.cursorStack();
    if (!stack.length) {
      return;
    }
    const previous = stack[stack.length - 1];
    this.cursorStack.set(stack.slice(0, -1));
    this.navigateToCursor(previous);
  }

  private navigateToCursor(cursor: string | null): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { cursor },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  private load(q: string | null, cursor: string | null): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.search(q, PAGE_SIZE, cursor).subscribe({
      next: (page) => {
        this.results.set(page.items);
        this.nextCursor.set(page.next_cursor);
        this.loading.set(false);
      },
      error: (problem: Problem) => {
        this.results.set([]);
        this.nextCursor.set(null);
        this.error.set(problem);
        this.loading.set(false);
      },
    });
  }
}
