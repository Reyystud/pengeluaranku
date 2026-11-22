"""Import Evidently on pandas 3.

Evidently 0.7.23 (the latest release) imports ``infer_dtype_from_object`` from
``pandas.core.dtypes.common``, which pandas 3.1 no longer has, so ``import evidently`` fails. The
function only maps a dtype-like object to its scalar type; this shim restores it, and only when it
is missing. ``tests`` run a real drift report through it. Remove the shim when Evidently supports
pandas 3 (docs/DECISIONS.md, T-35).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas.core.dtypes.common as pandas_common


def ensure() -> None:
    if not hasattr(pandas_common, "infer_dtype_from_object"):

        def infer_dtype_from_object(dtype: Any) -> Any:
            return pd.api.types.pandas_dtype(dtype).type

        pandas_common.infer_dtype_from_object = infer_dtype_from_object  # type: ignore[attr-defined]
