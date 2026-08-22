"""quiet_hours/prompts/diagnose.txt is intentionally empty (the user writes
it by hand) -- diagnose() must refuse to call the model with nothing rather
than silently sending an empty system prompt. No network access needed:
the check happens before the OpenAI client or LLM_MODEL are even touched.
"""

from datetime import UTC, datetime

import pytest

from quiet_hours.contracts import IncidentWindow
from quiet_hours.diagnose import diagnose


def test_diagnose_raises_when_prompt_file_is_empty():
    window = IncidentWindow(
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        events=[],
        trigger="unused",
        stats={},
    )
    with pytest.raises(RuntimeError, match="prompt has not been written yet"):
        diagnose(window)
