"""The inputs we write rather than fetch: data/authored/.

There is nothing to download - the "url" is the directory - but every row
they become still names its source, like every other row in the database.
The code stays `user` for continuity with databases built before the rename.
"""

AUTHORED = ("user", "Hand-authored inputs", "data/authored/")
