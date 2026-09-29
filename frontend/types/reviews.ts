export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type BBox = [number, number, number, number];
interface ContentBase { order: number; page_index?: number; bbox?: BBox; source_element_ids?: string[]; source_slice?: [number, number, number]; }
export type OrderedContent =
  | (ContentBase & { type: "text"; text: string; merged_source_segments?: Record<string, unknown>[] })
  | (ContentBase & { type: "formula_region" | "figure_region"; region_id: string })
  | (ContentBase & { type: "score_expression"; text?: string; expression_id?: string });
// Unrecognized server items retain all fields and are rendered without editing.
export interface UnknownContent { type: string; order: number; text?: string; region_id?: string; source_slice?: [number, number, number]; merged_source_segments?: Record<string, unknown>[]; [key: string]: unknown; }
export type ContentItem = OrderedContent | UnknownContent;
export type Decision = { decision: string; teacher_transcription?: string; note?: string; evidence_identity?: Json };
export type WarningResolution = { state: "unreviewed" | "acknowledged" | "resolved"; note?: string };
export interface ReviewNode {
  review_node_id: string; stable_key: string; source_draft_stable_key: string | null;
  source_draft_node_id: string | null; parent_key: string | null; node_type: "major_question" | "subquestion";
  depth: number; sort_order: number; label: { raw: string; normalized: string }; body_text: string;
  ordered_content: ContentItem[]; included: boolean;
  score_semantics: "direct" | "each_child" | "unset" | "ambiguous"; score_points: number | null;
  effective_points_candidate?: number | null; review_flags: string[];
  source_mapping_decision?: "automatic" | "teacher_manual_mapping" | "teacher_unmapped_override";
  formula_decisions: Record<string, Decision>; figure_decisions: Record<string, Decision>;
  warning_states: Record<string, WarningResolution>;
}
export interface PinnedEvidence {
  region_id: string; result_id: string; view_sha256: string; normalized_sha256: string;
  raw_sha256: string; crop_sha256: string; parser_name: string | null; parser_version: string | null;
  source_field: string | null; has_candidate: boolean; review_flags: string[];
  parse_status: string | null; structured: boolean | null;
}
export interface ReviewSnapshot {
  schema_version: string; source_draft_sha256: string; nodes: ReviewNode[];
  vision_pin: { run_id: string | null; results: PinnedEvidence[] };
  state: "editing" | "reviewed"; reviewed: boolean; warning_states?: Record<string, WarningResolution>;
  review_flags: string[]; document_context: Json; editing_contract?: number;
}
export interface SourceRegion { page_index: number; bbox: BBox; }
export interface Region extends SourceRegion {
  region_id: string; region_type: "formula" | "figure"; assigned_question_key: string | null;
  source_element_ids: string[]; review_flags: string[];
  text_fragments?: { native_text: string; element_id: string; bbox: BBox }[];
  routing_evidence?: Json; image_evidence?: Json[];
}
export interface ReviewWarning { id: string; code: string; scope: string; source_id: string; owner: string | null; blocking: boolean; }
export interface Summary {
  included_questions: number; excluded_questions: number; unresolved_warnings: number;
  formula_reviewed: number; formula_unreviewed: number; figure_reviewed: number; figure_unreviewed: number;
  score_unresolved: number; total_points_candidate: number | null;
}
export interface AutomaticNode {
  stable_key: string; body_text: string; label: ReviewNode["label"]; ordered_content: ContentItem[];
  score: { semantics: ReviewNode["score_semantics"]; points: number | null };
}
export interface ReviewDocument {
  id: string; draft_id: string; test_id: string; state: string; current_revision: number;
  revision_number: number; revision_sha256: string; current_revision_sha256: string;
  snapshot: ReviewSnapshot; summary: Summary; page_count: number; warnings: ReviewWarning[];
  regions: Region[]; source_regions: Record<string, SourceRegion[]>; automatic_nodes: AutomaticNode[];
  source_pdf_sha256: string; source_ir_sha256: string;
}
export interface PreviewMetadata {
  page_index: number; page_count: number; preview_width: number; preview_height: number;
  regions: { source_type: string; source_id: string; pixel_bbox: BBox;
    pixel_coordinate_space?: "pixel"; source_bbox?: BBox;
    source_coordinate_space?: "pdf_point" }[];
}
export interface ParsedView {
  transcription_normalized?: string; source_field?: string; parser_name?: string; parser_version?: string;
  structured?: boolean; parse_status?: string; parser_warnings?: string[]; review_flags?: string[];
  output: Record<string, Json>; unstructured_observation?: string;
}
export interface RegionEvidence {
  region: Region; native_elements: Json[]; pin: PinnedEvidence | null; parsed_view: ParsedView | null;
  crop_available: boolean; raw_available: boolean;
  crop_source: "pinned_vision" | "review_preview";
}
export interface RevisionInfo {
  revision_number: number; created_at: string; state: string; revision_sha256: string;
  change_metadata: { changed_nodes?: string[]; state?: string };
}
export interface ReviewEntry {
  id: string | null; draft_id: string; source_filename: string; draft_created_at: string;
  parser_version: string; question_count: number; review_required: boolean; warning_count: number;
  has_vision: boolean; state: string; current_revision: number | null;
}
