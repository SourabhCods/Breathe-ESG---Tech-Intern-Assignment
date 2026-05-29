from .base import BaseIngestionProcessor
from .sap import SAPFuelProcessor
from .utility import UtilityElectricityProcessor
from .travel import CorporateTravelProcessor

# Global Registry mapping source keys to Strategy classes
_PROCESSORS = {
    "sap": SAPFuelProcessor(),
    "utility": UtilityElectricityProcessor(),
    "travel": CorporateTravelProcessor()
}


class IngestionProcessorFactory:
    """
    Factory class to fetch processing strategies dynamically.
    Enables zero-touch registration of new data layout processors in the future.
    """

    @classmethod
    def get_processor(cls, source_type: str) -> BaseIngestionProcessor:
        normalized_type = str(source_type).strip().lower()
        processor = _PROCESSORS.get(normalized_type)
        if not processor:
            raise ValueError(f"Ingestion strategy for source type '{source_type}' is not registered.")
        return processor
