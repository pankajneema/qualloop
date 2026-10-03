/** API read models used by the P02 screens (docs/build/phases/P02-test-contract.md section 2). */

export type Role = 'admin' | 'quality' | 'viewer';

export type Me = {
  id: string;
  email: string;
  name: string;
  role: Role;
  can_approve: boolean;
  plants: { id: string; name: string; code: string; timezone: string }[];
};

export type Page<T> = { items: T[]; next_cursor: string | null };

export const SUPPLIER_STATUSES = [
  'approved',
  'approved_with_action_plan',
  'on_watch',
  'blocked',
  'inactive',
] as const;
export type SupplierStatus = (typeof SUPPLIER_STATUSES)[number];

export const SUPPLIER_CATEGORIES = ['raw_material', 'bought_out', 'job_work', 'service'] as const;
export type SupplierCategory = (typeof SUPPLIER_CATEGORIES)[number];

export type Supplier = {
  id: string;
  code: string;
  name: string;
  gstin: string | null;
  city: string | null;
  state: string | null;
  category: SupplierCategory;
  status: SupplierStatus;
  status_reason: string | null;
  status_changed_by: string | null;
  status_changed_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ConsentChannel = 'whatsapp' | 'email' | 'sms';
export type ConsentStatus = 'opted_in' | 'opted_out';

export type Consent = {
  id: string;
  channel: ConsentChannel;
  status: ConsentStatus;
  source: string;
  consent_at: string;
  revoked_at: string | null;
};

export type Contact = {
  id: string;
  supplier_id: string;
  name: string;
  role: string | null;
  mobile: string | null;
  email: string | null;
  is_quality_contact: boolean;
  verified_mobile_at: string | null;
  verified_email_at: string | null;
  active: boolean;
  disabled_at: string | null;
  disabled_reason: string | null;
  replaced_by_contact_id: string | null;
  needs_reverification: boolean;
  consents: Consent[];
};

export type Part = {
  id: string;
  part_no: string;
  name: string;
  category: string | null;
  current_revision: string | null;
  archived_at: string | null;
};

export type Customer = { id: string; name: string; code: string; archived_at: string | null };

export type SupplierPart = {
  id: string;
  supplier_id: string;
  part_id: string;
  supplier_part_no: string | null;
  ppm_target: number | null;
  archived_at: string | null;
};

export type CustomerPart = {
  id: string;
  customer_id: string;
  part_id: string;
  customer_part_no: string | null;
  archived_at: string | null;
};

export type ImportEntity = 'suppliers' | 'parts' | 'supplier_parts';
export const IMPORT_ENTITIES: ImportEntity[] = ['suppliers', 'parts', 'supplier_parts'];

export type ImportStatus =
  'uploaded' | 'mapped' | 'validated' | 'importing' | 'completed' | 'failed' | 'cancelled';

export type ImportBatch = {
  id: string;
  entity: ImportEntity;
  file_name: string;
  file_hash: string;
  status: ImportStatus;
  mapping: Record<string, string>;
  suggested_mapping: Record<string, string>;
  columns: string[];
  target_fields: { name: string; required: boolean }[];
  rows_received: number;
  rows_valid: number;
  rows_imported: number;
  rows_duplicate: number;
  rows_rejected: number;
  rows_unmapped: number;
  rows_review: number;
  confirmed_at: string | null;
  file_hash_seen_before: boolean;
  previous_batch_ids: string[];
  created_at: string;
};

export type PreviewStatus = 'valid' | 'duplicate' | 'rejected' | 'unmapped' | 'review';

export type PreviewRow = {
  row_number: number;
  status: PreviewStatus;
  reason: string | null;
  values: Record<string, string | null>;
};
