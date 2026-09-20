/** Mirrors the API's response models (api/app/schemas). */

export interface Page<T> {
  items: T[];
  page_size: number;
  next_cursor: string | null;
}

export interface MedicineSummary {
  code: string;
  name: string;
  form: string;
  strength_value: string;
  strength_unit: string;
  is_active: boolean;
}

export interface MedicineDetailDto extends MedicineSummary {
  current_rule: Rule | null;
}

export interface Rule {
  id: number;
  effective_from: string;
  /** Exclusive; null means open-ended. */
  effective_to: string | null;
  max_quantity_per_dispense: number;
  max_quantity_per_30_days: number;
  requires_authorisation: boolean;
}

export interface RuleHistory {
  items: Rule[];
  in_force_rule_id: number | null;
}

export interface DispenseCreate {
  medicine_code: string;
  patient_ref: string;
  quantity: number;
  /** ISO-8601 with an explicit offset; the API rejects naive timestamps. */
  dispensed_at: string;
  authorisation_ref: string | null;
}

export interface Dispense {
  id: number;
  medicine_code: string;
  patient_ref: string;
  quantity: number;
  dispensed_at: string;
  authorisation_ref: string | null;
  rule_id: number;
  created_at: string;
}

/** One broken rule. `field` names the request field it belongs to. */
export interface Violation {
  code: string;
  field: string;
  message: string;
  rule_id?: number;
}

/** The API's single error shape (RFC 9457 problem+json). */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  errors?: Violation[];
}
