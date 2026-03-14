from riskope.models import ExtractedRisk, ExtractionResult
from riskope.pipeline.chunker import TextChunker


def test_no_chunk_needed():
    chunker = TextChunker(max_chars=100, overlap_chars=10)
    text = "Short text"
    result = chunker.chunk(text)
    assert result == [text]


def test_chunk_on_paragraph():
    chunker = TextChunker(max_chars=50, overlap_chars=10)
    part_a = "A" * 30
    part_b = "B" * 30
    text = part_a + "\n\n" + part_b

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert chunks[0].endswith("\n\n") or chunks[0] == part_a + "\n\n"
    for c in chunks:
        assert len(c) <= 50 + 10


def test_chunk_overlap():
    chunker = TextChunker(max_chars=50, overlap_chars=10)
    parts = [f"Part{i} " + "x" * 20 for i in range(5)]
    text = "\n\n".join(parts)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    for i in range(1, len(chunks)):
        prev_end = chunks[i - 1][-10:]
        assert prev_end in chunks[i], (
            f"Chunk {i} should overlap with chunk {i-1}"
        )


def test_chunk_fallback_sentence():
    chunker = TextChunker(max_chars=50, overlap_chars=5)
    text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence."

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 50 + 5


def test_chunk_no_boundary():
    chunker = TextChunker(max_chars=50, overlap_chars=5)
    text = "A" * 200

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    reconstructed = chunks[0]
    for c in chunks[1:]:
        reconstructed += c[5:]
    assert len(reconstructed) >= 200


def test_chunk_korean_period():
    chunker = TextChunker(max_chars=50, overlap_chars=5)
    text = "가나다라마바사아자차카타파하" * 2 + "。" + "가나다라마바사아자차카타파하" * 2

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2


def test_merge_results():
    chunker = TextChunker()
    results = [
        ExtractionResult(
            risks=[
                ExtractedRisk(tag="환율 리스크", supporting_quote="환율 변동"),
                ExtractedRisk(tag="금리 리스크", supporting_quote="금리 상승"),
            ],
            model="gpt-4o",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        ),
        ExtractionResult(
            risks=[
                ExtractedRisk(tag="환율 리스크", supporting_quote="환율 급변"),
                ExtractedRisk(tag="경쟁 리스크", supporting_quote="시장 경쟁 심화"),
            ],
            model="gpt-4o",
            usage={"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120},
        ),
    ]

    merged = chunker.merge_extraction_results(results)

    assert len(merged.risks) == 3
    tags = [r.tag for r in merged.risks]
    assert tags == ["환율 리스크", "금리 리스크", "경쟁 리스크"]
    assert merged.risks[0].supporting_quote == "환율 변동"


def test_merge_usage_summed():
    chunker = TextChunker()
    results = [
        ExtractionResult(
            risks=[ExtractedRisk(tag="a", supporting_quote="q1")],
            model="gpt-4o",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        ),
        ExtractionResult(
            risks=[ExtractedRisk(tag="b", supporting_quote="q2")],
            model="gpt-4o",
            usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
        ),
    ]

    merged = chunker.merge_extraction_results(results)

    assert merged.usage["prompt_tokens"] == 300
    assert merged.usage["completion_tokens"] == 150
    assert merged.usage["total_tokens"] == 450
    assert merged.model == "gpt-4o"


def test_merge_empty_results():
    chunker = TextChunker()
    merged = chunker.merge_extraction_results([])
    assert merged.risks == []
    assert merged.model == ""
