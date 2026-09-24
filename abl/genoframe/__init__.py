"""GenoFrame data contract (DESIGN.md §3.2): key = (animal_id, selection_date)."""
from .frame import GenoFrame, Markers  # noqa: F401
from .snapshot import Snapshot, pit_snapshot  # noqa: F401
from .splitter import Split, forward_splits  # noqa: F401
