"""Census of the FAQs the index holds for one Artemis instance.

Artemis calls this to reconcile the FAQs it has accepted with the ones Iris can retrieve: it pushes
FAQs that are missing, changed or
duplicated, and deletes rows of FAQs it no longer has. The census reads the whole FAQ collection,
because FAQ rows are few and small, and
confirms every row against the object store, so ghost rows (still returned by a scan, gone from the
store) are not reported. A read error
fails the request instead of returning a partial list.
"""

from fastapi import APIRouter, Depends
from fastapi.params import Query

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.dependencies import TokenValidator
from iris.domain.ingestion.faq_census_dto import FaqCensusDTO, FaqCensusEntryDTO

from ...vector_database.batch_verify import confirmed_rows
from ...vector_database.database import VectorDatabase
from ...vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["faq_census"])

_PROPERTIES = [
    FaqSchema.COURSE_ID.value,
    FaqSchema.FAQ_ID.value,
    FaqSchema.BASE_URL.value,
    FaqSchema.CONTENT_FINGERPRINT.value,
]


@router.get(
    "/faq-census",
    response_model=FaqCensusDTO,
    dependencies=[Depends(TokenValidator())],
)
def get_faq_census(base_url: str = Query(...)) -> FaqCensusDTO:
    """Report every FAQ row of the asking instance, grouped by course and FAQ.

    FastAPI has already decoded the query value, so ``base_url`` is compared as it is: decoding it
    again would change a base URL that
    contains a percent sequence and no longer match the rows written for it.
    """
    database = VectorDatabase()
    if not database.client.collections.exists(FaqSchema.COLLECTION_NAME.value):
        # Lost while Pyris kept running: nothing is stored, and the pushes Artemis sends next
        # create the collection again
        return FaqCensusDTO(faqs=[])
    collection = database.faqs
    rows = [
        row
        for row in collection.iterator(return_properties=_PROPERTIES)
        if _belongs_to(row, base_url)
    ]
    rows = confirmed_rows(
        collection,
        rows,
        concurrency=settings.lecture_ingestion.census_confirm_concurrency,
    )
    return FaqCensusDTO(faqs=group_rows(rows, base_url))


def _belongs_to(row, base_url: str) -> bool:
    row_base_url = row.properties.get(FaqSchema.BASE_URL.value)
    return not row_base_url or row_base_url == base_url


def group_rows(rows: list, base_url: str) -> list[FaqCensusEntryDTO]:
    """Group confirmed rows by course and FAQ, counting owned and legacy rows apart.

    The owned fingerprint is reported only when every owned row carries the same one; rows that
    disagree report none, and their count above
    one already makes Artemis push the FAQ again.
    """
    entries: dict[tuple[int, int], FaqCensusEntryDTO] = {}
    owned_fingerprints: dict[tuple[int, int], set] = {}
    for row in rows:
        key = (
            int(row.properties[FaqSchema.COURSE_ID.value]),
            int(row.properties[FaqSchema.FAQ_ID.value]),
        )
        entry = entries.setdefault(
            key, FaqCensusEntryDTO(courseId=key[0], faqId=key[1])
        )
        if row.properties.get(FaqSchema.BASE_URL.value) == base_url:
            entry.owned_row_count += 1
            owned_fingerprints.setdefault(key, set()).add(
                row.properties.get(FaqSchema.CONTENT_FINGERPRINT.value)
            )
        else:
            entry.legacy_row_count += 1
    for key, fingerprints in owned_fingerprints.items():
        if len(fingerprints) == 1:
            entries[key].owned_fingerprint = next(iter(fingerprints))
    return [entries[key] for key in sorted(entries)]
