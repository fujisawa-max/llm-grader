"""Read-only source-warning coverage; historical IDs and decisions are evidence."""
from copy import deepcopy

SPATIAL_WARNING = 'ambiguous_geometric_order'
SPATIAL_LABEL = '設問の図表や数値・文字・文章の位置関係を確認してください'
SPATIAL_EXPLANATION = '本来意図されている位置関係の認識に失敗した可能性があります。元資料と照合してください。'
COVERAGE_SCHEMA = 'source-warning-coverage.v1'


def parser_coverage(draft):
    """Attest this parser's node-union operation, not a same-code heuristic.

    v1.2.1 collects this document flag exclusively at its final node union.
    Preamble layout flags are not added to that union. Unknown producers fail
    closed. Explicit coverage supports independent/mixed document evidence.
    """
    explicit = draft.get('warning_provenance', {})
    if SPATIAL_WARNING in explicit:
        return {SPATIAL_WARNING: deepcopy(explicit[SPATIAL_WARNING])}
    parser = draft.get('parser', {})
    if (parser.get('name'), parser.get('version')) != (
            'native-question-structure', 'question-structure-v1.2.1'):
        return {}
    covered = [f"node:{n['stable_key']}:{SPATIAL_WARNING}"
               for n in draft.get('nodes', []) if SPATIAL_WARNING in n.get('review_flags', [])]
    if not covered:
        return {}
    return {SPATIAL_WARNING: {'schema_version': COVERAGE_SCHEMA,
                             'producer': 'native-question-structure-v1.2.1-node-union',
                             'covered_warning_ids': covered, 'independent_evidence_ids': []}}


def warning_requirements(warnings, question=None, nodes=None):
    """Decorate detached catalog records; no acknowledgment is manufactured."""
    result = deepcopy(warnings)
    by_id = {w['id']: w for w in result}
    for warning in result:
        warning['actionable'] = True
        coverage = warning.get('coverage', {})
        covered = coverage.get('covered_warning_ids')
        independent = coverage.get('independent_evidence_ids')
        if not isinstance(coverage, dict):
            continue
        if (warning.get('scope') != 'draft' or warning.get('source_id') != 'document'
                or warning.get('owner') is not None or coverage.get('schema_version') != COVERAGE_SCHEMA
                or not isinstance(covered, list) or not covered or not all(isinstance(wid, str) for wid in covered)
                or len(set(covered)) != len(covered) or independent != []):
            continue
        valid = True
        for wid in covered:
            child = by_id.get(wid, {})
            if (child.get('scope') != 'node' or not child.get('owner')
                    or child.get('source_id') != child.get('owner')
                    or child.get('code') != warning.get('code') or not child.get('blocking')):
                valid = False
                break
            if nodes is not None:
                from .authoring_question_issues import warning_question_key
                if warning_question_key(nodes, child, question) is None:
                    valid = False
                    break
        if valid:
            warning['actionable'] = False
            warning['requirement_kind'] = 'covered_aggregate'
    return result


def authoring_warning_catalog(session, root, snapshot):
    """Attest old pinned catalogs using their immutable server source Draft.

    Never write new coverage into a saved/confirmed snapshot. If evidence is
    unavailable or differs, keep the original warning independently actionable.
    """
    question = snapshot.get('domains', {}).get('question')
    if not question:
        return []
    warnings = deepcopy(question['document'].get('warnings', []))
    if root:
        try:
            from .question_reviews import QuestionReviewService
            from .review_document import ReviewError
            from .review_document import warning_catalog
            service = QuestionReviewService(session, root)
            review = service._review(question['document']['id'])
            draft, _, value, ir = service._draft(review.draft_id)
            if (review.draft_id == question['document'].get('draft_id')
                    and draft.draft_sha256 == review.source_draft_sha256
                    and ir['source']['sha256'] == question['document'].get('source_pdf_sha256')
                    and question['document'].get('automatic_nodes') == value['nodes']):
                attested = {w['id']: w for w in warning_catalog(
                    value, question['snapshot'].get('vision_pin', {}))}
                for warning in warnings:
                    proof = attested.get(warning['id'], {})
                    fields = ('id', 'code', 'scope', 'source_id', 'owner', 'blocking')
                    if all(warning.get(k) == proof.get(k) for k in fields) and 'coverage' in proof:
                        warning['coverage'] = deepcopy(proof['coverage'])
        except (ValueError, KeyError, TypeError, OSError, ReviewError):
            pass  # Lack of proof never hides an existing requirement.
    return warning_requirements(warnings, question, snapshot['nodes'])
