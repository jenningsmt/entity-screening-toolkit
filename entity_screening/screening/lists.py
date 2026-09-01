"""Entity-of-concern list registry.

Built generic from day one: only OpenSanctions ships in V1, but DoD's
Section 1260H list and the Seven Sons seed list (both sequenced into V3 by
docs/requirements.md's roadmap, though Epic D's acceptance criteria names
all three) plug in later as new EntityOfConcernList implementations without
any change to screen.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from entity_screening.common.schema import SourceRecord
from entity_screening.resolution.normalize import normalize_for_matching

BLOCK_SIZE = 3


@dataclass(frozen=True)
class ConcernListEntry:
    list_name: str
    entry_id: str
    name_variants: tuple[str, ...]
    entity_type: str
    source_fields: dict[str, Any]


class EntityOfConcernList(ABC):
    """One entity-of-concern list a resolved entity can be screened against."""

    list_name: str

    @abstractmethod
    def entries(self) -> Iterator[ConcernListEntry]:
        """Yields entries one at a time — lists like OpenSanctions are large."""
        raise NotImplementedError

    def candidates_for(self, name: str, block_size: int = BLOCK_SIZE) -> Iterable[ConcernListEntry]:
        """Blocking step: entries sharing a normalized name-prefix with `name`.

        Exhaustively comparing every resolved entity against every entry in a
        list the size of OpenSanctions' full target file (hundreds of
        thousands of rows) isn't tractable; this prefix block keeps screening
        proportional to entries that could plausibly match.
        """
        index = self._block_index(block_size)
        key = normalize_for_matching(name)[:block_size]
        return index.get(key, [])

    def _block_index(self, block_size: int) -> dict[str, list[ConcernListEntry]]:
        cache_attr = f"_block_index_cache_{block_size}"
        cached = getattr(self, cache_attr, None)
        if cached is None:
            index: dict[str, list[ConcernListEntry]] = defaultdict(list)
            for entry in self.entries():
                seen_keys: set[str] = set()
                for variant in entry.name_variants:
                    key = normalize_for_matching(variant)[:block_size]
                    if key and key not in seen_keys:
                        seen_keys.add(key)
                        index[key].append(entry)
            cached = dict(index)
            setattr(self, cache_attr, cached)
        return cached


class OpenSanctionsList(EntityOfConcernList):
    list_name = "opensanctions_consolidated"

    def __init__(self, source_records: Iterable[SourceRecord]):
        self._source_records = list(source_records)

    def entries(self) -> Iterator[ConcernListEntry]:
        for record in self._source_records:
            fields = record.fields
            name = fields.get("name")
            if not name:
                continue
            aliases = fields.get("aliases") or ""
            variants = tuple(
                v.strip() for v in [name, *str(aliases).split(";")] if v and v.strip()
            )
            yield ConcernListEntry(
                list_name=self.list_name,
                entry_id=record.source_record_id,
                name_variants=variants,
                entity_type=fields.get("schema", "unknown"),
                source_fields=fields,
            )


class DoD1260HList(EntityOfConcernList):
    """DoD's Section 1260H list of Chinese military companies — Epic D names
    this alongside OpenSanctions and Seven Sons, and unlike Seven Sons
    (deliberately sequenced into V3, docs/requirements.md Section 12) it's
    never assigned to a phase, so it ships now rather than waiting."""

    list_name = "dod_section_1260h"

    def __init__(self, source_records: Iterable[SourceRecord]):
        self._source_records = list(source_records)

    def entries(self) -> Iterator[ConcernListEntry]:
        for record in self._source_records:
            fields = record.fields
            clean_name = fields.get("clean_name")
            if not clean_name:
                continue
            aliases = fields.get("aliases") or []
            variants = tuple(
                v.strip() for v in [clean_name, *aliases] if v and str(v).strip()
            )
            yield ConcernListEntry(
                list_name=self.list_name,
                entry_id=record.source_record_id,
                name_variants=variants,
                entity_type="chinese_military_company",
                source_fields=fields,
            )


_REGISTRY: dict[str, type[EntityOfConcernList]] = {
    OpenSanctionsList.list_name: OpenSanctionsList,
    DoD1260HList.list_name: DoD1260HList,
}


def registered_lists() -> dict[str, type[EntityOfConcernList]]:
    return dict(_REGISTRY)
