from app.router import offline_example_overlap


def test_offline_overlap_refunds_paraphrase() -> None:
    hit = offline_example_overlap("What's the total of all refunded invoice amounts?")
    assert hit is not None
    name, score = hit
    assert name == "refunds"
    assert score >= 0.18


def test_offline_overlap_rejects_noise() -> None:
    assert offline_example_overlap("hello world xyz") is None
