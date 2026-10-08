"""Source adapters for the central schema."""
from dart_remote.sources import revenue_source
from dart_remote.sources import source_excerpt as resolve
from .pipeline import load_report
def source_excerpt(ref,sector_id=None):return resolve(ref,sector_id,load_report)
