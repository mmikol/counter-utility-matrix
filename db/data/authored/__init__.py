"""The one input a user writes: the playbook in inference/strategies/.

Every other table is pulled from a source. This package declares the
`sources` row the strategies mirror carries; `load_authored` reloads the
mirror from the files (inference.catalog.mirror).
"""

from db import Source

# The sources row of the strategies table. Nothing is downloaded: the "url"
# is the playbook's folder. No other table may carry this source.
AUTHORED = Source("user", "The playbook", "inference/strategies/")
