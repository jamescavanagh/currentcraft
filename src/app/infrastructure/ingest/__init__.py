"""Ingestion infrastructure: blob store, source adapters, tensorizer. The only place raw bytes and ingest arrays exist."""

from .adapters import (DataContractAdapter, DocxAdapter, EmailAdapter, JsonAdapter, PdfAdapter, TextAdapter,  # noqa: F401
                       default_adapters, pseudonym)
from .blobs import InMemoryBlobStore  # noqa: F401
from .tensorizer import TOKENIZER, NumpyTensorizer, hash_features  # noqa: F401
from .wiring import build_ingest, put_raw  # noqa: F401
from .xlsx import XlsxWorkbookAdapter  # noqa: F401
from .ooxml import read_workbook, shift_formula  # noqa: F401
