export interface DiagramRecord {
  id: string; domain: string; target_key: string; page_index: number; state: "candidate" | "accepted" | "excluded";
  automatic_bbox: number[]; final_bbox?: number[]; crop_bbox?: number[]; crop_sha256?: string;
  page_width?: number; page_height?: number; page_rotation?: number; preview_url?: string;
  scope?: "exact" | "parent" | "pdf"; source_question_id?: string | null; source_question_path?: string | null; assigned_question_id?: string;
  trust_state?: "trusted" | "teacher_confirmable" | "hard_invalid";
  trust_state_at_accept?: string | null; teacher_confirmed?: boolean; confirmation_reason_code?: string | null; acceptance_method?: string | null;
  teacher_adjusted?: boolean; legacy_region_ids?: string[];
  status?: string; reason_code?: string; legacy_region_id?: string; context_sha256?: string;
  [key: string]: unknown;
}
export interface DiagramSelection { record: DiagramRecord; manual: boolean; onBounds?: (box: number[]) => void; }
