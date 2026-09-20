import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiClient } from './api-client';
import { MedicineDetailDto, MedicineSummary, Page, Rule, RuleHistory } from './api.types';

/** Every /medicines call the UI makes. One service per resource, so no view has to
 * know a URL, a query-parameter name or a cursor convention. */
@Injectable({ providedIn: 'root' })
export class MedicinesApi {
  private readonly api = inject(ApiClient);

  /** GET /medicines — `q` matches name or code partially; `cursor` comes from a previous page. */
  search(q: string | null, limit: number, cursor: string | null): Observable<Page<MedicineSummary>> {
    return this.api.get<Page<MedicineSummary>>('/medicines', { q, limit, cursor });
  }

  /** GET /medicines/{code} — includes the rule in force right now. */
  get(code: string): Observable<MedicineDetailDto> {
    return this.api.get<MedicineDetailDto>(`/medicines/${encodeURIComponent(code)}`);
  }

  /** GET /medicines/{code}/rules — full history, oldest first, plus which one is in force. */
  rules(code: string): Observable<RuleHistory> {
    return this.api.get<RuleHistory>(`/medicines/${encodeURIComponent(code)}/rules`);
  }

  /** POST /medicines/{code}/rules — introduces a rule from a date, superseding what is in force. */
  addRule(
    code: string,
    rule: {
      effective_from: string;
      max_quantity_per_dispense: number;
      max_quantity_per_30_days: number;
      requires_authorisation: boolean;
    },
  ): Observable<Rule> {
    return this.api.post<Rule>(`/medicines/${encodeURIComponent(code)}/rules`, rule);
  }
}
