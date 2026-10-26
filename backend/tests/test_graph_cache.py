"""Graph responses are reused within one loaded generation and never across generations."""

from src.repositories.graph_cache import GenerationCache


class _Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def fetchall(self):
        return [(self.value,)]


class GenerationSession:
    """Answers the generation lookup with the current value of ``oids`` (one per call, the last one repeats)."""

    def __init__(self, *oids):
        self.oids = list(oids)

    async def execute(self, statement, params=None):
        assert "to_regnamespace" in str(statement)
        return _Scalar(self.oids.pop(0) if len(self.oids) > 1 else self.oids[0])


def _counter():
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    return compute, calls


async def test_a_second_request_of_the_same_generation_is_served_from_the_cache():
    cache, (compute, calls) = GenerationCache(), _counter()
    session = GenerationSession(101)
    first = await cache.get(session, "ds_x", ("summary",), compute)
    second = await cache.get(session, "ds_x", ("summary",), compute)
    assert first is second and len(calls) == 1


async def test_a_new_generation_is_computed_again():
    cache, (compute, calls) = GenerationCache(), _counter()
    await cache.get(GenerationSession(101), "ds_x", ("summary",), compute)
    fresh = await cache.get(GenerationSession(202), "ds_x", ("summary",), compute)
    assert fresh == {"n": 2} and len(calls) == 2


async def test_a_dataset_that_is_not_loaded_is_never_cached():
    cache, (compute, calls) = GenerationCache(), _counter()
    for _ in range(2):
        await cache.get(GenerationSession(None), "ds_x", ("summary",), compute)
    assert len(calls) == 2


async def test_a_value_computed_while_a_load_swapped_the_data_is_not_kept():
    cache, (compute, calls) = GenerationCache(), _counter()
    await cache.get(GenerationSession(101, 202), "ds_x", ("summary",), compute)  # swapped mid-request
    await cache.get(GenerationSession(101), "ds_x", ("summary",), compute)
    assert len(calls) == 2


async def test_requests_and_datasets_are_kept_apart_and_the_oldest_entry_goes_first():
    cache, (compute, calls) = GenerationCache(max_entries=2), _counter()
    session = GenerationSession(101)
    await cache.get(session, "ds_x", ("entities", "A", 5), compute)
    await cache.get(session, "ds_y", ("entities", "A", 5), compute)
    await cache.get(session, "ds_x", ("entities", "A", 6), compute)  # evicts the first entry
    assert len(calls) == 3
    await cache.get(session, "ds_x", ("entities", "A", 5), compute)
    assert len(calls) == 4
