from app.composition.text_constraints import TextLayoutContract


def test_text_layout_contract_rejects_boundary_excess() -> None:
    contract = TextLayoutContract()
    assert contract.accepts(visual_overlap=contract.max_visual_overlap, text_overlap=0.0)
    assert not contract.accepts(visual_overlap=contract.max_visual_overlap + 0.001, text_overlap=0.0)
