import pytest

from jarvis.amaura import completion_contract as cc

CRITERIA = [
    'Source register complete',
    'Amaura relevance explained',
    'No competitor copying',
]


def evidence(n=3):
    return [
        {
            'type': 'tool_result',
            'tool': 'web_search',
            'success': True,
            'reference': f'evidence://r{i}',
            'excerpt': f'source {i}',
        }
        for i in range(1, n + 1)
    ]


def good_contract(n=3):
    return {
        'version': 1,
        'summary': 'A structured, evidence-grounded Amaura research deliverable.',
        'criteria': [
            {
                'criterion_index': 1,
                'criterion': CRITERIA[0],
                'satisfied': True,
                'deliverable': 'Every successful public-research result is registered and mapped.',
                'evidence_refs': [f'evidence://r{i}' for i in range(1, n + 1)],
                'fact_inference_boundary': 'Source identities/findings are factual; criterion mapping is synthesis.',
            },
            {
                'criterion_index': 2,
                'criterion': CRITERIA[1],
                'satisfied': True,
                'deliverable': 'Research is converted into a concrete Amaura product implication.',
                'evidence_refs': ['evidence://r1'],
                'fact_inference_boundary': 'Observed market behavior is sourced; product implication is inference.',
                'amaura_relevance': 'Amaura should use evidence-bound completion gates as a product differentiator.',
            },
            {
                'criterion_index': 3,
                'criterion': CRITERIA[2],
                'satisfied': True,
                'deliverable': 'Category lessons are separated from competitor-specific expression.',
                'evidence_refs': ['evidence://r2'],
                'fact_inference_boundary': 'Observed patterns are sourced; differentiation is Amaura inference.',
                'originality_rationale': {
                    'observed_patterns': ['Competitors use structured research workflows.'],
                    'category_level_ideas': ['Evidence registers and verification are generic patterns.'],
                    'amaura_differentiation': ['Criterion-bound synthesis before independent review.'],
                    'copying_avoidance': ['Do not reuse competitor wording, branding, or proprietary flows.'],
                },
            },
        ],
        'source_register': [
            {
                'evidence_ref': f'evidence://r{i}',
                'source': f'Source {i}',
                'locator': f'https://example.com/{i}',
                'finding': f'Finding {i}',
                'supports_criteria': [1, 2, 3],
            }
            for i in range(1, n + 1)
        ],
    }


def test_accepts_complete_research_delivery():
    result = cc.validate_completion_contract(good_contract(), acceptance_criteria=CRITERIA, evidence=evidence())
    assert result['version'] == 1
    assert len(result['source_register']) == 3


def test_rejects_incomplete_source_register():
    contract = good_contract()
    contract['source_register'].pop()
    with pytest.raises(cc.CompletionContractError, match='source register is incomplete'):
        cc.validate_completion_contract(contract, acceptance_criteria=CRITERIA, evidence=evidence())


def test_rejects_missing_amaura_relevance():
    contract = good_contract()
    contract['criteria'][1].pop('amaura_relevance')
    with pytest.raises(cc.CompletionContractError, match='Amaura relevance'):
        cc.validate_completion_contract(contract, acceptance_criteria=CRITERIA, evidence=evidence())


def test_rejects_missing_noncopying_rationale():
    contract = good_contract()
    contract['criteria'][2].pop('originality_rationale')
    with pytest.raises(cc.CompletionContractError, match='originality/non-copying'):
        cc.validate_completion_contract(contract, acceptance_criteria=CRITERIA, evidence=evidence())


def test_rejects_unknown_evidence_reference():
    contract = good_contract()
    contract['criteria'][0]['evidence_refs'] = ['evidence://not-submitted']
    with pytest.raises(cc.CompletionContractError, match='not submitted'):
        cc.validate_completion_contract(contract, acceptance_criteria=CRITERIA, evidence=evidence())


def test_rejects_unsatisfied_criterion_instead_of_bluffing():
    contract = good_contract()
    contract['criteria'][0]['satisfied'] = False
    with pytest.raises(cc.CompletionContractError, match='not yet satisfied'):
        cc.validate_completion_contract(contract, acceptance_criteria=CRITERIA, evidence=evidence())


def test_synthesis_packet_loads_immutable_payload_not_only_excerpt():
    class Reader:
        def get_text(self, reference):
            return 'FULL SOURCE PAYLOAD with https://example.com and decisive finding'

    packet = cc.build_completion_packet(
        task_packet={'objective': 'research', 'acceptance_criteria': CRITERIA, 'action_type': 'research'},
        draft_summary='raw searches collected',
        evidence=evidence(1),
        evidence_reader=Reader(),
    )
    assert 'FULL SOURCE PAYLOAD' in packet['evidence'][0]['payload']
    assert packet['criterion_requirements'][0]['source_register'] is True
    assert packet['criterion_requirements'][1]['amaura_relevance'] is True
    assert packet['criterion_requirements'][2]['originality'] is True
