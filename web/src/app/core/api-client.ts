import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { Problem } from './api.types';

/** Served behind the same origin: nginx proxies /api to the API container. */
const BASE = '/api/v1';

/**
 * The one place HTTP is spoken. Every failure — including a network error or a
 * non-JSON response — arrives at callers as a Problem, so no view has to deal with
 * HttpErrorResponse or guess at an error's shape.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);

  get<T>(path: string, params: Record<string, string | number | undefined | null> = {}): Observable<T> {
    let httpParams = new HttpParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        httpParams = httpParams.set(key, String(value));
      }
    }
    return this.http.get<T>(`${BASE}${path}`, { params: httpParams }).pipe(catchError(toProblem));
  }

  post<T>(path: string, body: unknown, headers: Record<string, string> = {}): Observable<T> {
    return this.http.post<T>(`${BASE}${path}`, body, { headers }).pipe(catchError(toProblem));
  }
}

function toProblem(error: HttpErrorResponse): Observable<never> {
  const body = error.error;
  if (body && typeof body === 'object' && typeof body.code === 'string' && typeof body.status === 'number') {
    return throwError(() => body as Problem);
  }
  // Network failure, a proxy error page, or anything else that never reached the API.
  return throwError(
    () =>
      ({
        type: 'about:blank',
        title: 'Request failed',
        status: error.status || 0,
        detail: error.status ? `The server returned ${error.status}.` : 'The server could not be reached.',
        code: 'TRANSPORT_ERROR',
      }) satisfies Problem,
  );
}
