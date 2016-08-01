# Infrastructure for testing the handling of diff "sliders"

## Background

If a block of lines is added or deleted from a file, there can be ambiguity about exactly which lines were added/deleted if

* the first line that was added/deleted is identical to the line following the block, or

* the last line that was added/deleted is identical to the line preceding the block.

Sometimes `diff` chooses unwisely, resulting in unintuitive diffs like

```
@@ -2188,12 +1996,6 @@
                return dir->nr;
 
        /*
-        * Stay on the safe side. if read_directory() has run once on
-        * "dir", some sticky flag may have been left. Clear them all.
-        */
-       clear_sticky(dir);
-
-       /*
         * exclude patterns are treated like positive ones in
         * create_simplify. Usually exclude patterns should be a
         * subset of positive ones, which has no impacts on
```

when the following diff makes more sense:

```
@@ -2188,12 +1996,6 @@
                return dir->nr;
 
-       /*
-        * Stay on the safe side. if read_directory() has run once on
-        * "dir", some sticky flag may have been left. Clear them all.
-        */
-       clear_sticky(dir);
-
        /*
         * exclude patterns are treated like positive ones in
         * create_simplify. Usually exclude patterns should be a
         * subset of positive ones, which has no impacts on
```

I call ambiguous add/delete blocks like this "sliders", because there is some freedom to slide them up or down.


## Tools in this repository

This repository contains a bunch of tools for

* Finding sliders in arbitrary `git diff` output

* Determining the range of "shifts" that are legal

* Testing new prototypes of other heuristics for choosing how to shift sliders

* Recording the output of all of the above in text files

* Displaying tricky cases in an easy-to-read format

It also contains an implementation of an alternative heuristic that seems to work pretty well.

When these tools are used to analyze the slider mentioned above, the output looks like

```
8ad3cb08690bdf9a340e47ed4fdb67cbacd1edf2:dir.c 5cee349370bd2dce48d0d653ab4ce99bb79a3415:dir.c - 2191
vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
               >			       PATHSPEC_ICASE |
               >			       PATHSPEC_EXCLUDE);
               >
               >	if (has_symlink_leading_path(path, len))
               >		return dir->nr;
     -2 |      >
     -1 |   ci >	/*
      0 || gci >	 * Stay on the safe side. if read_directory() has run once on
        || gci >	 * "dir", some sticky flag may have been left. Clear them all.
        || gci >	 */
        || gci >	clear_sticky(dir);
         | gci >
         | g   >	/*
               >	 * exclude patterns are treated like positive ones in
               >	 * create_simplify. Usually exclude patterns should be a
               >	 * subset of positive ones, which has no impacts on
               >	 * create_simplify().
               >	 */
               >	simplify = create_simplify(pathspec ? pathspec->_raw : NULL);
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

The first line shows the two blobs being diffed, whether lines were added (`+`) or subtracted (`-`), and the line number of the start of the slider. The diff itself shows multiple columns:

* A number, which is the relative shift that would move the add/delete block to that line

* Two columns of `|` characters, showing the highest and lowest that the slider can be shifted

* One or more columns of letters (here, `g`, `c`, and `i`), showing where various algorithms that are under comparison would choose to shift the slider

* A column of `>` characters, showing the left margin of the actual lines

* The lines themselves.


The prototype heuristic can be analyzed by piping a `*.slider` file to `show-slider-scores`, or as follows to analyze a single slider:

```
$ echo '8ad3cb08690bdf9a340e47ed4fdb67cbacd1edf2:dir.c 5cee349370bd2dce48d0d653ab4ce99bb79a3415:dir.c - 2191' | ./show-slider-scores --repo=corpus/$repo
8ad3cb08690bdf9a340e47ed4fdb67cbacd1edf2:dir.c 5cee349370bd2dce48d0d653ab4ce99bb79a3415:dir.c - 2191
vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
               > 			       PATHSPEC_ICASE |
               > 			       PATHSPEC_EXCLUDE);
               > 
               > 	if (has_symlink_leading_path(path, len))
               > 		return dir->nr;
    |    156   > 
    |    152 - > 	/*
    ||   188 - >-	 * Stay on the safe side. if read_directory() has run once on
    ||       - >-	 * "dir", some sticky flag may have been left. Clear them all.
    ||       - >-	 */
    ||       - >-	clear_sticky(dir);
     |       - >-
     |         >-	/*
               > 	 * exclude patterns are treated like positive ones in
               > 	 * create_simplify. Usually exclude patterns should be a
               > 	 * subset of positive ones, which has no impacts on
               > 	 * create_simplify().
               > 	 */
               > 	simplify = create_simplify(pathspec ? pathspec->_raw : NULL);
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

This output includes the heuristic's scores for each possible shift of the slider. The lowest score (e.g., 152 in this example) wins. The `+` or `-` symbols to the left of the `>` show the heuristic's preferred shift; those to the right of the `>` show the shift chosen by standard `git diff`.


## Use

:warning: This software is very experimental! Note especially that it is not careful to quote filenames. Running it against a repository with strange filenames could probably lead to arbitrary code execution! :warning:

Basic use:

1. In the `analyze` script, adjust `GIT_EXPERIMENTAL` and `GIT_EXPERIMENTAL_OPTS` to invoke some Git version that you want to test.

2. Clone a Git repository that you would like to use as a source of diffs to a directory `corpus/$repo`. This can be a bare clone if you like.

3. Run

        ./analyze $repo

4. View the output in `corpus/$repo-compare-shifts.out`.

5. If there are any other algorithms you want to test against the existing ones, invoke it the way `$GIT_EXPERIMENTAL` is invoked in `analyze`, and writing the output to a file like `corpus/$repo-your-algo.sliders`. Then run `compare-shifts`, adding your results as an additional column in the output by adding an argument like `y=corpus/$repo-your-algo.sliders`.


## Prototype heuristic

The heuristic that is prototyped here chooses its shifts based only on the indentation of lines around the slider plus the presence/absence of blank lines nearby. It computes a score for the split that would have to be introduced at the top of the slider, and one for the split at the bottom of the slider, then adds the scores together to get an overall score for a slider shift. The shift with the lowest score wins.

The implementation of the scoring algorithm is in `diff_heuristics.py`, class `SplitScorer` or `SplitScorer2`. Feel free to play with it and tweak it. Remember, whatever heuristic we build into Git has to work acceptably well across a wide variety of programming languages and other textual input!


## To Do

There is still no tool to allow a human to state which shift looks best for a particular slider. This would be relatively easy to add. It should write its output to a `*.slider` file in the same format as the others. Then it would be nice to have a tool that rates algorithms numerically by comparing them to the human-generated results.


