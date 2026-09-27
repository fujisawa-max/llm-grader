import { test, expect } from "@playwright/test";
import type { ReviewDocument, ReviewNode, ReviewSnapshot } from "../types/reviews";

function fixture(): ReviewDocument {
  const node: ReviewNode = { review_node_id: "q1", stable_key: "q1", source_draft_stable_key: "q1", source_draft_node_id: null,
    parent_key: null, node_type: "major_question", depth: 0, sort_order: 0, label: { raw: "問題1", normalized: "問題1" },
    body_text: "問題文", ordered_content: [{ type: "text", order: 0, text: "問題文" },
      { type: "formula_region", order: 1, region_id: "formula-1" }, { type: "figure_region", order: 2, region_id: "figure-1" }],
    included: true, score_semantics: "direct", score_points: 10, review_flags: [], formula_decisions: {}, figure_decisions: {}, warning_states: {} };
  return { id: "review", draft_id: "draft", test_id: "test", state: "editing", current_revision: 1, revision_number: 1,
    revision_sha256: "snapshot", current_revision_sha256: "snapshot", source_pdf_sha256: "pdf", source_ir_sha256: "ir", page_count: 2,
    snapshot: { schema_version: "question-import-review.v1", source_draft_sha256: "draft", nodes: [node],
      vision_pin: { run_id: "pinned", results: [] }, state: "editing", reviewed: false, document_context: {}, review_flags: [], warning_states: {} },
    regions: [{ region_id: "formula-1", region_type: "formula", assigned_question_key: "q1", page_index: 0, bbox: [10, 20, 50, 40], source_element_ids: ["span"], review_flags: [], text_fragments: [{ native_text: "2 1 x", element_id: "span", bbox: [10, 20, 50, 40] }] },
      { region_id: "figure-1", region_type: "figure", assigned_question_key: "q1", page_index: 1, bbox: [10, 20, 80, 90], source_element_ids: ["image"], review_flags: [] }],
    warnings: [{ id: "warning", code: "reasoning_output_requires_review", scope: "region", source_id: "formula-1", owner: "q1", blocking: true }],
    source_regions: { q1: [{ page_index: 0, bbox: [10, 10, 90, 100] }, { page_index: 1, bbox: [10, 20, 80, 90] }] },
    automatic_nodes: [{ stable_key: "q1", label: node.label, body_text: node.body_text, ordered_content: node.ordered_content, score: { semantics: "direct", points: 10 } }],
    summary: { included_questions: 1, excluded_questions: 0, unresolved_warnings: 1, formula_reviewed: 0, formula_unreviewed: 1, figure_reviewed: 0, figure_unreviewed: 1, score_unresolved: 0, total_points_candidate: 10 } };
}

test("review compares evidence, switches pages, saves teacher edits and reports conflicts", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined, configurable: true }));
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const data = fixture();
  const saved: ReviewSnapshot[] = [];
  let conflict = false;
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url()).pathname;
    if (url.endsWith("/confirmation")) return route.fulfill({ json: null });
    if (url.endsWith("/users")) return route.fulfill({ json: [] });
    if (url.endsWith("/mark-reviewed")) {
      data.snapshot = { ...data.snapshot, state: "reviewed", reviewed: true };
      data.current_revision++; data.revision_number++;
      return route.fulfill({ json: data });
    }
    if (url.endsWith("/revisions") && route.request().method() === "POST") {
      if (conflict) return route.fulfill({ status: 409, json: { error: { code: "revision_conflict" } } });
      const body = route.request().postDataJSON() as { snapshot: ReviewSnapshot; base_revision: number };
      expect(body.base_revision).toBe(data.current_revision);
      saved.push(body.snapshot); data.snapshot = body.snapshot; data.current_revision++; data.revision_number++;
      return route.fulfill({ json: data });
    }
    if (url.endsWith("/revisions")) return route.fulfill({ json: { revisions: [{ revision_number: 1, state: "editing", created_at: "2026-09-16", change_metadata: {} }] } });
    if (url.endsWith("/metadata")) return route.fulfill({ json: { page_index: url.includes("/pages/1/") ? 1 : 0, page_count: 2, preview_width: 100, preview_height: 150,
      regions: [{ source_type: "node", source_id: "q1", pixel_bbox: [10, 10, 90, 100] }, { source_type: "formula", source_id: "formula-1", pixel_bbox: [10, 20, 50, 40] }, { source_type: "figure", source_id: "figure-1", pixel_bbox: [10, 20, 80, 90] }] } });
    if (url.endsWith("/preview") || url.endsWith("/crop")) return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aR1cAAAAASUVORK5CYII=", "base64") });
    if (url.endsWith("/vision-raw")) return route.fulfill({ json: { raw: { content: "<script>untrusted</script>" }, source_raw_sha256: "raw" } });
    if (url.endsWith("/evidence")) {
      const region = data.regions.find(r => url.includes(r.region_id))!;
      return route.fulfill({ json: { region, native_elements: [], crop_available: true, crop_source: "pinned_vision", raw_available: true,
        pin: { has_candidate: true }, parsed_view: { transcription_normalized: "2 1 x", source_field: "reasoning", parser_version: "v1", structured: false, parse_status: "partial", output: { labels: ["-2π", "π"] }, review_flags: ["reasoning_output_requires_review"] } } });
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/question-import-reviews/review");
  await expect(page.getByRole("heading", { name: "教師による確認" })).toBeVisible();
  await expect(page.getByRole("link", { name: "← 試験の問題画面に戻る" })).toBeVisible();
  await expect(page.getByLabel("確認状況")).toContainText("設問 1 / 除外 0");
  await expect(page.getByRole("navigation", { name: "設問構成" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "問題文と資料" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "確認事項" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "変更履歴" })).toBeVisible();
  await expect(page.getByRole("button", { name: "確認済みにする" })).toBeVisible();
  await expect(page.getByLabel("設問の階層")).toHaveValue("");
  await expect(page.getByLabel("配点の扱い")).toHaveValue("direct");
  await expect(page.getByRole("option", { name: "各小問に配点" })).toHaveAttribute("value", "each_child");
  await expect(page.getByRole("button", { name: "前のページ" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "次のページ" })).toBeEnabled();
  const visibleReviewText = await page.locator(".teacher-review").evaluate(element => (element as HTMLElement).innerText);
  expect(visibleReviewText).not.toMatch(/Teacher Review|Test Workspace|Question tree|Major question|Subquestion|Score semantics|Ordered content|Mark Reviewed|Previous|Next|each_child|major_question/);
  await expect(page.locator("rect[data-source-id=q1]")).toHaveCount(1);
  await page.getByRole("button", { name: "数式 2 · 読み取り結果を比較", exact: true }).click();
  await expect(page.locator("rect[data-source-id=formula-1]")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "PDFから読み取った内容" })).toBeVisible();
  await page.getByText("画像解析の元データ（技術情報）").click();
  await expect(page.getByText('"<script>untrusted</script>"', { exact: false })).toBeVisible();
  await page.getByLabel("確認結果").selectOption("teacher_edit");
  const single = String.raw`\sin \frac{5}{12}\pi`;
  await page.getByLabel("教師が確認した数式", { exact: true }).fill(single);
  await page.getByLabel("確認事項 1の状態").selectOption("acknowledged");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0].nodes[0].formula_decisions["formula-1"].teacher_transcription).toBe(single);
  await page.reload();
  await page.getByRole("button", { name: "数式 2 · 読み取り結果を比較", exact: true }).click();
  await expect(page.getByLabel("教師が確認した数式", { exact: true })).toHaveValue(single);
  const deliberateDouble = String.raw`a\\b`;
  await page.getByLabel("教師が確認した数式", { exact: true }).fill(deliberateDouble);
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(2);
  expect(saved[1].nodes[0].formula_decisions["formula-1"].teacher_transcription).toBe(deliberateDouble);
  await page.getByLabel("配点の扱い").selectOption("each_child");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(3);
  expect(saved[2].nodes[0].score_semantics).toBe("each_child");
  await page.getByRole("button", { name: "小問を追加" }).click();
  await expect(page.getByRole("heading", { name: "追加問題" })).toBeVisible();
  await expect(page.getByLabel("設問の階層")).toHaveValue("q1");
  await page.getByLabel("設問番号・見出し").fill("追加した小問");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(4);
  expect(saved[3].nodes[1].node_type).toBe("subquestion");
  expect(saved[3].nodes[1].stable_key).toMatch(/^teacher-[0-9a-f-]{36}$/);
  await page.locator(".review-tree button[data-source-key=q1]").click();
  await page.getByRole("button", { name: "小問を追加" }).click();
  await page.getByLabel("設問番号・見出し").fill("もう一つの小問");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(5);
  await page.getByRole("button", { name: "上へ移動" }).click();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(6);
  expect(saved[5].nodes.find(node => node.label.raw === "もう一つの小問")?.sort_order).toBe(0);
  await page.getByLabel("設問の階層").selectOption("");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect.poll(() => saved.length).toBe(7);
  expect(saved[6].nodes.find(node => node.label.raw === "もう一つの小問")?.node_type).toBe("major_question");
  await page.locator(".review-tree button[data-source-key=q1]").click();
  await page.getByRole("button", { name: "図 3 · 読み取り結果を比較", exact: true }).click();
  await expect(page.getByText("一部のみ読み取り済み・要確認")).toBeVisible();
  await expect(page.getByAltText("原PDF 2ページ")).toBeVisible();
  await expect(page.locator("rect[data-source-id=figure-1]")).toHaveCount(1);
  conflict = true;
  await page.getByLabel("確認結果").selectOption("accepted_as_evidence");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect(page.locator(".teacher-review [role=alert]")).toContainText("別の画面で新しい修正版が保存されています");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "最新の内容を再読み込み" }).click();
  await page.getByRole("button", { name: "確認済みにする" }).click();
  await expect(page.locator("header .badge")).toHaveText("確認済み");
  expect(pageErrors).toEqual([]);
});
