import { expect, test } from "@playwright/test";
import { buildReviewTargets, resolveReviewTarget } from "../lib/modelAnswerReviewTargets";
import type { ModelAnswerImportDraft } from "../lib/api/modelAnswerImports";
import { questionBreadcrumb } from "../lib/modelAnswerQuestionNavigation";
import { validateModelAnswerRegistration } from "../lib/modelAnswerRegistrationValidation";

test("review targets keep nested breadcrumbs and place unresolved and excluded after questions", () => {
  const draft = {
    questions: [
      { id: "nested", parent_id: "sub", label: "問題2 > (2) > 2." },
      { id: "q2", parent_id: null, label: "問題2" },
      { id: "sub", parent_id: "q2", label: "問題2 > (2)" },
    ],
    entries: [
      { id: "source-1", question_id: null, disposition: "unassigned", candidate_text: "Answer candidate" },
      { id: "source-2", question_id: "q2", disposition: "excluded", candidate_text: "Question text" },
    ],
  } as ModelAnswerImportDraft;
  const targets = buildReviewTargets(draft);
  expect(targets.map((target) => target.label)).toEqual([
    "問題2", "問題2 > (2)", "問題2 > (2) > 2.",
    "対応する設問なし (1)", "除外済み > 模範解答ではない文章 (1)",
  ]);
  expect(resolveReviewTarget(targets, "question:deleted")?.id).toBe("question:q2");
  expect(resolveReviewTarget(targets, "unassigned:source-1")?.entryId).toBe("source-1");
});

test("API hierarchy rank wins over interleaved source and question response order", () => {
  const draft = {
    questions: [
      { id: "q3a", parent_id: "q3", label: "問題3 > (1)", hierarchy_order: 7 },
      { id: "q2b2", parent_id: "q2b", label: "問題2 > (2) > 2.", hierarchy_order: 5 },
      { id: "q2b1", parent_id: "q2b", label: "問題2 > (2) > 1.", hierarchy_order: 4 },
      { id: "q1", parent_id: null, label: "問題1", hierarchy_order: 0 },
    ],
    entries: [
      { id: "pdf-last", question_id: "q3a" },
      { id: "pdf-first", question_id: "q1" },
      { id: "unresolved", question_id: null, candidate_text: "Unresolved candidate" },
    ],
  } as ModelAnswerImportDraft;
  expect(buildReviewTargets(draft).map((target) => target.label)).toEqual([
    "問題1", "問題2 > (2) > 1.", "問題2 > (2) > 2.", "問題3 > (1)",
    "対応する設問なし (1)",
  ]);
});

test("shared breadcrumb resolves nested labels and retains server label when a structural parent is absent", () => {
  const questions = [
    { id: "q2", parent_id: null, display_label: "問題2" },
    { id: "q2b", parent_id: "q2", display_label: "(2)" },
    { id: "nested", parent_id: "q2b", display_label: "2." },
  ];
  expect(questionBreadcrumb(questions[2], questions)).toBe("問題2 > (2) > 2.");
  const leaf = {...questions[2], label: "問題2 > (2) > 2."};
  expect(questionBreadcrumb(leaf, [leaf]))
    .toBe("問題2 > (2) > 2.");
});

test("registration validation is structured, candidate-addressable, and ignores excluded or unassigned entries", () => {
  const base = {
    questions: [{ id: "nested", parent_id: "sub", label: "問題2 > (2) > 2.", is_gradable: true }],
    confirmed_entry_ids: [],
    entries: [{ id: "valid", question_id: "nested", answer_text: "Answer", answer_kind: "primary",
      disposition: "include", semantic_classification: { status: "classified", segments: [] } }],
  } as unknown as ModelAnswerImportDraft;
  const labels = new Map([["question:nested", "問題2 > (2) > 2."]]);
  expect(validateModelAnswerRegistration(base, labels)).toEqual([]);

  const blocked = {
    ...base,
    entries: [
      ...base.entries,
      { id: "empty", question_id: "nested", answer_text: "", answer_kind: "primary", disposition: "include" },
      { id: "uncertain", question_id: "nested", answer_text: "Maybe", answer_kind: "primary", disposition: "include",
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "question" }, { category: "uncertain" }] } },
      { id: "unassigned", question_id: null, answer_text: "Rubric text", answer_kind: "primary", disposition: "include",
        semantic_classification: { status: "classified", segments: [{ category: "rubric" }] } },
      { id: "excluded", question_id: "nested", answer_text: "Excluded", disposition: "excluded",
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "note" }] } },
    ],
  } as unknown as ModelAnswerImportDraft;
  const result = validateModelAnswerRegistration(blocked, labels);
  expect(result.map((item) => item.reasonCode)).toContain("duplicate_primary_answer");
  expect(result.some((item) => item.reasonCode === "classification_review_required")).toBe(false);
  expect(result.some((item) => item.reasonCode === "empty_answer_text")).toBe(false);
  expect(result.some((item) => item.candidateId === "unassigned")).toBe(false);
  expect(result.some((item) => item.candidateId === "excluded")).toBe(false);
  expect(result.every((item) => item.severity === "blocking")).toBe(true);
  const alternativeOnly = { ...base, entries: [{ id: "alternative", question_id: "nested", answer_text: "Other", answer_kind: "alternative", disposition: "include" }] } as unknown as ModelAnswerImportDraft;
  expect(validateModelAnswerRegistration(alternativeOnly, labels).map((item) => item.reasonCode))
    .toContain("primary_answer_required");
});

test("registration validation ignores blank/noise and irrelevant uncertain entries but keeps true formal blockers", () => {
  const draft = {
    questions: [{ id: "q1", parent_id: null, label: "問題1", is_gradable: true }],
    confirmed_entry_ids: [],
    entries: [
      { id: "accepted", question_id: "q1", answer_text: "Answer", candidate_text: "source", disposition: "include",
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "uncertain" }] } },
      { id: "teacher-edited", question_id: "q1", answer_text: "Teacher answer", answer_kind: "alternative", disposition: "include",
        teacher_correction: { teacher_confirmed: true },
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "uncertain" }] } },
      { id: "blank", question_id: "q1", answer_text: " \n\t", candidate_text: "\u00a0", disposition: "ignored",
        semantic_classification: { status: "ignored", reason: "blank_or_whitespace", segments: [] } },
      { id: "excluded-uncertain", question_id: "q1", answer_text: "", disposition: "excluded",
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "question" }] } },
      { id: "rubric", question_id: null, answer_text: "5 points", disposition: "unassigned",
        semantic_classification: { status: "needs_teacher_review", segments: [{ category: "rubric" }] } },
    ],
  } as unknown as ModelAnswerImportDraft;
  const result = validateModelAnswerRegistration(draft, new Map([["question:q1", "問題1"]]));
  expect(result).toEqual([]);
  const teacherAccepted = { ...draft, entries: draft.entries.map((entry) => entry.id === "accepted"
    ? { ...entry, teacher_correction: { teacher_confirmed: true } } : entry) } as ModelAnswerImportDraft;
  expect(validateModelAnswerRegistration(teacherAccepted, new Map([["question:q1", "問題1"]]))).toEqual([]);
});

test("blank ignored extraction does not create a target or registration warning beside a valid answer", () => {
  const draft = {
    questions: [{ id: "q1", parent_id: null, label: "問題1", is_gradable: true }],
    confirmed_entry_ids: [],
    entries: [
      { id: "answer", question_id: "q1", answer_text: "Answer", disposition: "include" },
      { id: "noise", question_id: "q1", answer_text: " \n", candidate_text: "\t", disposition: "ignored",
        ignore_reason: "blank_or_whitespace" },
    ],
  } as unknown as ModelAnswerImportDraft;
  expect(buildReviewTargets(draft).map((target) => target.id)).toEqual(["question:q1"]);
  expect(validateModelAnswerRegistration(draft, new Map([["question:q1", "問題1"]]))).toEqual([]);
});

test("diagram-only readiness allows explicit teacher confirmation and rejects stale/unaccepted content", () => {
  const diagram = {id: "diagram-id", state: "accepted", status: "unresolved", reason_code: "diagram_ricoh_output_truncated",
    trust_state: "teacher_confirmable", teacher_confirmed: true, assigned_question_id: "child", target_key: "parent",
    source_sha256: "source", crop_sha256: "crop"};
  const draft = {source_sha256: "source", questions: [{id: "child", is_gradable: true}], confirmed_entry_ids: [],
    entries: [{id: "manual", question_id: "child", source: {kind: "teacher_manual"}, answer_text: "", disposition: "include",
      diagram_records: [diagram]}]} as unknown as ModelAnswerImportDraft;
  const labels = new Map([["question:child", "問題3 > (1)"]]);
  expect(validateModelAnswerRegistration(draft, labels)).toEqual([]);
  for (const update of [{teacher_confirmed: false}, {state: "candidate"}, {state: "excluded"},
    {trust_state: "hard_invalid"}, {source_sha256: "foreign"}, {assigned_question_id: "sibling"}]) {
    const invalid = {...draft, entries: [{...draft.entries[0], diagram_records: [{...diagram, ...update}]}]} as unknown as ModelAnswerImportDraft;
    expect(validateModelAnswerRegistration(invalid, labels).map(i => i.reasonCode)).toContain("empty_answer_text");
  }
});
