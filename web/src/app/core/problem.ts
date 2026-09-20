import { Problem, Violation } from './api.types';

export function isProblem(value: unknown): value is Problem {
  return typeof value === 'object' && value !== null && 'code' in value && 'status' in value;
}

/** Violations belonging to one form control. */
export function violationsFor(problem: Problem | null, field: string): Violation[] {
  return (problem?.errors ?? []).filter((violation) => violation.field === field);
}

/**
 * Violations that no control on the form owns — an inactive medicine, a breached
 * window, a rule with no field of its own. These must still be shown, because a
 * rejection has to display every reason at once.
 */
export function unattachedViolations(problem: Problem | null, knownFields: readonly string[]): Violation[] {
  const errors = problem?.errors ?? [];
  const unowned = errors.filter((violation) => !knownFields.includes(violation.field));
  // A problem with no violations at all (404, key reuse) still needs one line shown.
  if (!errors.length && problem) {
    return [{ code: problem.code, field: '', message: problem.detail }];
  }
  return unowned;
}
