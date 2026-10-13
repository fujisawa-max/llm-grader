"""Immutable Web contract, independent of current rows and legacy assignments."""

from copy import deepcopy
import json

import pytest

from scoring.grading_definition import (
    compile_definition,
    executable_definition,
    executable_rubric,
    freeze_definition,
    reject_web_legacy_policy,
)
from scoring.pdf_native import canonical_hash
from tests.test_test_authoring import workspace as authoring_workspace, begin, base


@pytest.fixture
def workspace(tmp_path):
    yield from authoring_workspace.__wrapped__(tmp_path)


def confirm(w, row):
    return w.client.post(
        base(w) + "/authoring/confirm",
        json={
            "revision_id": row["id"],
            "expected_edit_version": row["edit_version"],
            "expected_snapshot_sha256": row["snapshot_sha256"],
        },
    )


def save(w, row, snapshot):
    response = w.client.put(
        base(w) + "/authoring",
        json={"snapshot": snapshot, "expected_edit_version": row["edit_version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_revision_alone_reconstructs_and_ignores_external_policy(workspace, tmp_path):
    w = workspace
    row = begin(w)
    before = deepcopy(row["snapshot"])
    definition = executable_definition(before)
    policy = executable_rubric(before, w.question)
    external = tmp_path / "assignment.rubric.json"
    external.write_text(
        json.dumps(
            {
                **policy,
                "criteria": [
                    {
                        **policy["criteria"][0],
                        "levels": [
                            {"score": 0, "condition": "Legacy none"},
                            {"score": 5, "condition": "Legacy partial"},
                            {"score": 10, "condition": "Legacy full"},
                        ],
                    }
                ],
            }
        )
    )
    response = confirm(w, row)
    assert response.status_code == 200, response.text
    confirmed = response.json()
    assert confirmed["snapshot"] == before
    assert (
        canonical_hash(confirmed["snapshot"])
        == row["snapshot_sha256"]
        == confirmed["snapshot_sha256"]
    )
    external.write_text("{}")
    assert executable_definition(confirmed["snapshot"]) == definition
    assert [
        level["score"]
        for level in executable_rubric(confirmed["snapshot"], w.question)["criteria"][0]["levels"]
    ] == [0, 10]
    with w.sf() as s:
        with pytest.raises(ValueError, match="LEGACY_ASSIGNMENT_NOT_ALLOWED_FOR_WEB_TEST"):
            reject_web_legacy_policy(s, w.legacy)
    duplicate = confirm(w, row)
    assert duplicate.status_code == 200 and duplicate.json()["id"] == confirmed["id"]
    assert duplicate.json()["snapshot"] == before


def test_missing_levels_save_allowed_confirmation_blocked_then_teacher_completes(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row["snapshot"])
    value["domains"]["rubric"]["entries"][0]["criteria"][0].pop("levels")
    row = save(w, row, value)
    review = w.client.get(base(w) + "/authoring/review").json()
    issue = next(i for i in review["issues"] if i.get("code") == "grading_levels_incomplete")
    assert issue["criterion_id"] == "c1" and issue["action_label"] == "得点段階を確認"
    assert not review["can_confirm"]
    before = deepcopy(row)
    assert confirm(w, row).status_code == 409
    assert w.client.get(base(w) + "/authoring").json()["revision"] == before
    value = deepcopy(row["snapshot"])
    value["domains"]["rubric"]["entries"][0]["criteria"][0]["levels"] = [
        {"score": 0, "condition": "Incorrect"},
        {"score": 5, "condition": "Valid method"},
        {"score": 10, "condition": "Complete"},
    ]
    row = save(w, row, value)
    assert w.client.get(base(w) + "/authoring/review").json()["can_confirm"]
    assert confirm(w, row).status_code == 200


@pytest.mark.parametrize(
    "levels",
    [
        [],
        [{"score": 10, "condition": ""}],
        [{"score": 11, "condition": "Invalid"}],
        [{"score": 0, "condition": "None"}],
        [{"score": 10, "condition": "A"}, {"score": 10, "condition": "B"}],
        [{"score": 0.5, "condition": "Fraction"}],
        [{"score": None, "condition": "Pending"}],
    ],
)
def test_invalid_executable_levels_never_synthesized(workspace, levels):
    row = begin(workspace)
    snapshot = deepcopy(row["snapshot"])
    snapshot["rubrics"][workspace.question][0]["levels"] = levels
    before = deepcopy(snapshot)
    definition, issues = compile_definition(snapshot)
    assert not definition["complete"]
    if levels == [{"score": 11, "condition": "Invalid"}]:
        assert not any(i["code"] == "grading_levels_incomplete" for i in issues)
        assert definition["questions"][0]["rubric"]["criteria"][0]["max_score"] == 11
    else:
        assert any(i["code"] == "grading_levels_incomplete" for i in issues)
    assert snapshot == before


def test_second_edition_explicitly_adopts_new_web_levels_parent_stays_unchanged(workspace):
    w = workspace
    row = begin(w)
    first = confirm(w, row).json()
    draft = w.client.post(
        base(w) + "/authoring/revisions", json={"confirmed_revision_id": first["id"]}
    ).json()
    assert draft["snapshot"] == first["snapshot"]
    value = deepcopy(draft["snapshot"])
    value["domains"]["rubric"]["entries"][0]["criteria"][0]["levels"].insert(
        1, {"score": 5, "condition": "Correct method, wrong result"}
    )
    draft = save(w, draft, value)
    second_response = confirm(w, draft)
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["parent_confirmed_revision_id"] == first["id"]
    assert [
        v["score"]
        for v in executable_rubric(first["snapshot"], w.question)["criteria"][0]["levels"]
    ] == [0, 10]
    assert [
        v["score"]
        for v in executable_rubric(second["snapshot"], w.question)["criteria"][0]["levels"]
    ] == [0, 5, 10]
    history = w.client.get(base(w) + "/authoring/history").json()
    assert history["active_confirmed_revision_id"] == second["id"]
    assert (
        next(r["snapshot"] for r in history["revisions"] if r["id"] == first["id"])
        == first["snapshot"]
    )


def test_legacy_snapshot_readable_never_silently_completed(workspace):
    snapshot = begin(workspace)["snapshot"]
    snapshot["domains"].pop("grading_definition")
    before = deepcopy(snapshot)
    with pytest.raises(ValueError, match="GRADING_DEFINITION_LEGACY_INCOMPLETE"):
        executable_definition(snapshot)
    assert snapshot == before
    freeze_definition(snapshot)
    assert executable_definition(snapshot)["complete"]


def test_projection_tampering_discarded_and_hash_remains_consistent(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row["snapshot"])
    value["domains"]["grading_definition"]["questions"][0]["rubric"]["criteria"][0]["levels"] = [
        {"score": 99, "condition": "Forged"}
    ]
    row = save(w, row, value)
    assert [
        x["score"] for x in executable_rubric(row["snapshot"], w.question)["criteria"][0]["levels"]
    ] == [0, 10]
    assert canonical_hash(row["snapshot"]) == row["snapshot_sha256"]


def test_score_levels_are_canonical_and_stale_points_are_ignored(workspace):
    w = workspace
    row = begin(w)
    snapshot = deepcopy(row["snapshot"])
    criterion = snapshot["domains"]["rubric"]["entries"][0]["criteria"][0]
    criterion["points"] = 20
    snapshot["rubrics"][w.question][0]["points"] = 20
    definition, issues = compile_definition(snapshot)
    assert not issues
    executable = definition["questions"][0]["rubric"]["criteria"][0]
    assert executable["max_score"] == 10
    assert [level["score"] for level in executable["levels"]] == [0, 10]


def test_save_derives_compatibility_points_from_levels_even_when_incomplete(workspace):
    w = workspace
    row = begin(w)
    snapshot = deepcopy(row["snapshot"])
    criterion = snapshot["domains"]["rubric"]["entries"][0]["criteria"][0]
    criterion["points"] = 99
    criterion["levels"] = [{"score": 0, "condition": "基準を満たしていない。"}]
    row = save(w, row, snapshot)
    criterion = row["snapshot"]["domains"]["rubric"]["entries"][0]["criteria"][0]
    assert criterion["points"] == 0
    assert row["snapshot"]["rubrics"][w.question][0]["points"] == 0
    review = w.client.get(base(w) + "/authoring/review").json()
    assert not review["can_confirm"]
    assert any(issue["code"] == "grading_levels_incomplete" for issue in review["issues"])
    assert not any(issue["code"] == "grading_criterion_points" for issue in review["issues"])


def test_content_context_compilation_preserves_schema_ancestors_and_math(workspace):
    snapshot = begin(workspace)["snapshot"]
    parent = snapshot["nodes"][0]
    parent["ordered_content"] = [{"type": "text", "text": "Context", "order": 0}]
    child = deepcopy(parent)
    child.update(
        stable_key="child",
        parent_key=parent["stable_key"],
        label={"raw": "(1)"},
        ordered_content=[{"type": "formula", "transcription": "x=1", "order": 0}],
    )
    snapshot["nodes"].append(child)
    snapshot["answers"]["child"] = deepcopy(snapshot["answers"][parent["stable_key"]])
    snapshot["rubrics"]["child"] = deepcopy(snapshot["rubrics"][parent["stable_key"]])
    definition, issues = compile_definition(snapshot)
    assert not issues
    result = definition["questions"][1]
    assert result["content"]["schema_version"] == "test-question-content.v1"
    assert result["context"]["ancestor_chain"] == [parent["stable_key"]]
    assert (
        "Context" in result["context"]["effective_text"]
        and "x=1" in result["context"]["effective_text"]
    )
    assert compile_definition(snapshot)[0] == definition


def test_new_web_revision_cannot_enter_mutable_or_legacy_job_paths(workspace):
    w = workspace
    row = begin(w)
    assert confirm(w, row).status_code == 200
    for body, code in [
        ({}, "LEGACY_ASSIGNMENT_NOT_ALLOWED_FOR_WEB_TEST"),
        ({"input_stage": "selected_reconstruction"}, "WEB_GRADING_REVISION_BINDING_REQUIRED"),
    ]:
        response = w.client.post(base(w) + "/grading-jobs", json=body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == code


def test_stable_criterion_identity_survives_executable_identifier_encoding(workspace):
    w = workspace
    value = deepcopy(begin(w)["snapshot"])
    value["rubrics"][w.question][0]["id"] = "teacher-criterion-q2.1"
    freeze_definition(value)
    policy = executable_rubric(value, w.question)
    assert policy["criteria"][0]["authoring_criterion_id"] == "teacher-criterion-q2.1"
    assert "." not in policy["criteria"][0]["criterion_id"]
    assert executable_rubric(value, w.question) == policy


def test_confirmed_definition_checks_stored_hash(workspace):
    from types import SimpleNamespace
    from scoring.grading_definition import confirmed_definition

    snapshot = begin(workspace)["snapshot"]
    revision = SimpleNamespace(snapshot=snapshot, snapshot_sha256=canonical_hash(snapshot))
    assert confirmed_definition(revision)["complete"]
    revision.snapshot["metadata"]["name"] = "Tampered"
    with pytest.raises(ValueError, match="GRADING_DEFINITION_SNAPSHOT_HASH_MISMATCH"):
        confirmed_definition(revision)


def test_legacy_confirmed_fork_copies_exactly_and_completes_without_rewriting_parent(workspace):
    from scoring.authoring_confirmation import project_confirmed_snapshot
    from scoring.db.models import Test, TestAuthoringRevision, ConfirmedAuthoringRevision
    from scoring.test_authoring import baseline_hash, projection

    w = workspace
    row = begin(w)
    old_snapshot = deepcopy(row["snapshot"])
    old_snapshot["domains"].pop("grading_definition")
    old_snapshot["rubrics"][w.question][0].pop("levels")
    old_snapshot["domains"]["rubric"]["entries"][0]["criteria"][0].pop("levels")
    with w.sf() as s:
        s.info["authoring_confirmation_projection"] = True
        test = s.get(Test, w.legacy)
        working = s.get(TestAuthoringRevision, row["id"])
        project_confirmed_snapshot(s, test, old_snapshot, None)
        working.snapshot = old_snapshot
        working.snapshot_sha256 = canonical_hash(old_snapshot)
        working.state = "confirmed"
        working.baseline_sha256 = baseline_hash(projection(s, test, refresh=True))
        legacy = ConfirmedAuthoringRevision(
            test_id=w.legacy,
            authoring_revision_id=working.id,
            revision=working.revision,
            edit_version=working.edit_version,
            snapshot=deepcopy(old_snapshot),
            snapshot_sha256=canonical_hash(old_snapshot),
        )
        s.add(legacy)
        s.flush()
        test.active_confirmed_revision_id = legacy.id
        legacy_id = legacy.id
        s.commit()
    history = w.client.get(base(w) + "/authoring/history").json()
    assert not history["revisions"][0]["grading_definition_complete"]
    draft = w.client.post(
        base(w) + "/authoring/revisions", json={"confirmed_revision_id": legacy_id}
    ).json()
    assert draft["snapshot"] == old_snapshot
    assert draft["snapshot_sha256"] == canonical_hash(old_snapshot)
    assert not w.client.get(base(w) + "/authoring/review").json()["can_confirm"]
    value = deepcopy(draft["snapshot"])
    value["domains"]["rubric"]["entries"][0]["criteria"][0]["levels"] = [
        {"score": 0, "condition": "No credit"},
        {"score": 10, "condition": "Teacher-approved full credit"},
    ]
    draft = save(w, draft, value)
    assert executable_definition(draft["snapshot"])["complete"]
    response = confirm(w, draft)
    assert response.status_code == 200, response.text
    history = w.client.get(base(w) + "/authoring/history").json()
    assert next(r["snapshot"] for r in history["revisions"] if r["id"] == legacy_id) == old_snapshot


def test_reference_asset_reader_never_uses_current_configuration_and_rejects_drift(tmp_path):
    from scoring.grading_definition import read_reference_asset
    from scoring.pdf_native import sha256_file

    path = tmp_path / "crop.png"
    path.write_bytes(b"immutable reference fixture")
    reference = {
        "immutable_artifact": {
            "namespace": "answer_import",
            "artifact_ref": "crop.png",
            "sha256": sha256_file(path),
        }
    }
    assert read_reference_asset(reference, {"answer_import": tmp_path}) == path
    path.write_bytes(b"different current reference")
    with pytest.raises(ValueError, match="GRADING_DEFINITION_ARTIFACT_CHANGED"):
        read_reference_asset(reference, {"answer_import": tmp_path})
    reference["immutable_artifact"]["artifact_ref"] = "../foreign.png"
    with pytest.raises(ValueError, match="GRADING_DEFINITION_ARTIFACT_INVALID"):
        read_reference_asset(reference, {"answer_import": tmp_path})


@pytest.mark.parametrize(
    "patch,code,field",
    [
        ({"description": ""}, "grading_criterion_description", "content"),
        ({"id": ""}, "grading_criterion_identity", "content"),
    ],
)
def test_criterion_problem_guidance_targets_the_actual_field(workspace, patch, code, field):
    w = workspace
    snapshot = deepcopy(begin(w)["snapshot"])
    snapshot["rubrics"][w.question][0].update(patch)
    definition, issues = compile_definition(snapshot)
    assert not definition["complete"]
    issue = next(i for i in issues if i["code"] == code)
    assert issue["field"] == field
    assert issue["action_label"] != "得点段階を設定"
    assert not any(i["code"] == "grading_levels_incomplete" for i in issues)
