This directory is meant to hold a test corpus

This directory can be used to hold Git repositories whose commits will be used for testing `diff` heuristics. The `analyze` tool assumes that its input is located as a direct subdirectory of this directory, and derives the name of output files from the name of the subdirectory.

The Git repositories here can be bare.

The tools are quite general; they can analyze diffs between arbitrary commits or blobs. But currently `analyze` only uses the non-merge, non-orphan commits on the HEAD branch of a repo. (It might be interesting to analyze bigger diffs, like `git diff HEAD~1000..HEAD`, to see if they behave differently.)

