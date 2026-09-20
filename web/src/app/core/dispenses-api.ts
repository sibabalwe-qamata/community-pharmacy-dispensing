import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiClient } from './api-client';
import { Dispense, DispenseCreate, Page } from './api.types';

@Injectable({ providedIn: 'root' })
export class DispensesApi {
  private readonly api = inject(ApiClient);

  /**
   * POST /dispenses. The key must stay the same across retries of one capture and
   * change for the next one — the API replays the original outcome for a repeated key
   * and refuses a repeated key carrying a different body. Callers own the key's
   * lifetime, which is why it is a parameter rather than generated here.
   */
  create(body: DispenseCreate, idempotencyKey: string): Observable<Dispense> {
    return this.api.post<Dispense>('/dispenses', body, { 'Idempotency-Key': idempotencyKey });
  }

  /** GET /dispenses — newest first, filterable, keyset-paginated. */
  list(
    filters: { patient_ref?: string | null; medicine_code?: string | null },
    limit: number,
    cursor: string | null,
  ): Observable<Page<Dispense>> {
    return this.api.get<Page<Dispense>>('/dispenses', {
      patient_ref: filters.patient_ref ?? null,
      medicine_code: filters.medicine_code ?? null,
      limit,
      cursor,
    });
  }
}

/** A fresh idempotency key. The API requires at least 8 characters. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
