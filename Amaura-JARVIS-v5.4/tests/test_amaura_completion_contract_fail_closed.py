import pytest

from jarvis.amaura import completion_contract as cc


def test_unreadable_successful_evidence_is_never_accepted():
    items = [
        {
            "type": "tool_result",
            "tool": "web_search",
            "success": True,
            "reference": "evidence://missing",
            "excerpt": "cached excerpt must not substitute for immutable evidence",
        }
    ]

    class BrokenReader:
        def get_text(self, reference):
            raise ValueError("evidence object is missing")

    packet = cc.build_completion_packet(
        task_packet={
            "objective": "research",
            "acceptance_criteria": ["Evidence is verified"],
            "action_type": "research",
        },
        draft_summary="draft",
        evidence=items,
        evidence_reader=BrokenReader(),
    )

    assert packet["evidence"][0]["payload"] == ""
    assert packet["evidence"][0]["read_error"]
    assert items[0]["completion_evidence_read_error"]

    contract = {
        "version": 1,
        "summary": "Pretend completion",
        "criteria": [
            {
                "criterion_index": 1,
                "criterion": "Evidence is verified",
                "satisfied": True,
                "deliverable": "Claimed result",
                "evidence_refs": ["evidence://missing"],
                "fact_inference_boundary": "Claimed boundary",
            }
        ],
        "source_register": [],
    }

    with pytest.raises(cc.CompletionContractError, match="could not be read from the immutable vault"):
        cc.validate_completion_contract(
            contract,
            acceptance_criteria=["Evidence is verified"],
            evidence=items,
        )
