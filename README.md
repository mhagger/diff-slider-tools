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


## Adding a new repository to the corpus

More and more diverse training data means that the heuristic can be trained better. If you would like to add some training data, here is the procedure:

1.  Choose a publicly-readable Git repository with content that is representative of one or more types of file.

2.  Store the name of the repository in an environment variable (this makes later steps easier):

        repo=foo

3.  Create a `corpus/*.info` file containing the URL that can be used to clone the repository:

        echo 'https://github.com/foo/foo' >corpus/$repo.info

4.  Clone the repo:

        get-corpus $repo

5.  Create a list of all of the "sliders" in the main branch of the repository. (You can choose some other range of commits if you prefer.)

        git -C corpus/$repo.git log --min-parents=1 --max-parents=1 --format='%P..%H' HEAD |
            ./enumerate-sliders --repo=$repo >corpus/$repo.sliders

6.  Create a file that displays all of the sliders in a human-readable form. This file can get big, so if you want you can trim down the input that is given to it, or simply interrupt the command when it has generated as much input as you want.

        ./compare-shifts --repo=$repo --all g=corpus/$repo.sliders >corpus/$repo-human-input.sliders

7.  Hand-rate some sliders. (This is the part that is labor-intensive!) Open `corpus/$repo-human-input.sliders` in your editor. It will have lots of entries that look like the following:

        327535b4be335df93a353032f7d3c01aae0942d7:Objects/bytearrayobject.c 83c63e9c025810342dd7f1f2107a2eee9525bc56:Objects/bytearrayobject.c + 1999
        # vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
        #              >PyDoc_STRVAR(hex__doc__,
        #              >"B.hex() -> string\n\
        #              >\n\
        #              >Create a string of hexadecimal numbers from a bytearray object.\n\
        #              >Example: bytearray([0xb9, 0x01, 0xef]).hex() -> 'b901ef'.");
        #      -2 |    >
        #      -1 |    >static PyObject *
        #       0 || g >bytearray_hex(PyBytesObject *self)
        #         || g >{
        #         || g >    char* argbuf = PyByteArray_AS_STRING(self);
        #         || g >    Py_ssize_t arglen = PyByteArray_GET_SIZE(self);
        #         || g >    return _Py_strhex(argbuf, arglen);
        #         || g >}
        #          | g >
        #          | g >static PyObject *
        #              >_common_reduce(PyByteArrayObject *self, int proto)
        #              >{
        #              >    PyObject *dict;
        #              >    _Py_IDENTIFIER(__dict__);
        #              >    char *buf;
        #              >
        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    The first line identifies the source of this slider: it comes from diffing the file Objects/bytearrayobject.c in the two specified commits. The diff adds (`+`) lines, and 1999 is the line number of the added lines in the version of the file that contains them, when the slider is shifted to its lowest possible position.

    The following lines show the slider itself:

    * A number, which is the relative shift that would move the add/delete block to that line

    * Two columns of `|` characters, showing the highest and lowest that the slider can be shifted

    * One or more columns of letters, showing where various algorithms that are under comparison would choose to shift the slider. In this case, there is only one algorithm being displayed, namely `g`, which is the default Git positioning of the slider.

    * A column of `>` characters, showing the left margin of the actual lines

    * The lines themselves.

    Your job is to decide what would be the most intuitive position for this slider. In this case, the best position would be `-1`, because then the diff would show a single entire function being added. Record your selection at the end of the first line, changing it to:

        327535b4be335df93a353032f7d3c01aae0942d7:Objects/bytearrayobject.c 83c63e9c025810342dd7f1f2107a2eee9525bc56:Objects/bytearrayobject.c + 1999 -1

	If there are multiple positions that are equally good, you can record them all; e.g., `-2 -5`.

    Rate as many sliders as you like, then save the file.

8.  Create a file containing only the sliders that you have rated:

        ./filter-sliders --rated <corpus/$repo-human-input.sliders >corpus/$repo-human.sliders

9.  Commit the `$repo.info` file and the `$repo-human.sliders` file into Git:

        git add corpus/$repo.info corpus/$repo-human.sliders
        git commit -m "Add sliders from repo $repo to the corpus"

10. Push your changes to GitHub and create a pull request.


## Adding more human ratings for a repository that is already in the corpus

1.  (If you haven't already done so:) Download and/or update the repository:

        repo=foo
        get-corpus $repo

2.  (If you haven't already done so:) Create a list of the sliders in the repository:

        git -C corpus/$repo.git log --min-parents=1 --max-parents=1 --format='%P..%H' HEAD |
            ./enumerate-sliders --repo=$repo >corpus/$repo.sliders

3.  Create a file that displays the unrated repositories in human-readable form.

        ./filter-sliders --omit-rated=corpus/$repo-human.sliders <corpus/$repo.sliders |
            shuf -n 1000 |
            ./compare-shifts --repo=$repo --all g=- >corpus/$repo-human-input.sliders

    This command uses `shuf` to choose 1000 of the sliders at random. Feel free to adjust that part of the pipeline.

4.  Hand-rate some sliders as described in step 7 above.

5.  Add the newly-rated sliders to the end of the existing `$repo-human.sliders` file:

        ./filter-sliders --rated <corpus/$repo-human-input.sliders >>corpus/$repo-human.sliders

9.  Commit the new `$repo-human.sliders` file into Git, push your changes, and create a pull request.


## Testing a different prototype heuristic

*To be written.*


## Testing a different Git version

1.  Make sure that you have created the `corpus/$repo.sliders` file as described in one of the earlier sections.

2.  Have your own experimental version of Git compute the same diffs that appear in the sliders, and read the shift that it chose using `read-shift`:

        cat corpus/$repo.sliders |
            while read old new prefix line_number shifts
            do
			    $EXPERIMENTAL_GIT -C corpus/$repo.git diff $EXPERIMENTAL_GIT_OPTS -U20 "$old" "$new" -- |
                   ./read-shift "$old" "$new" "$prefix" "$line_number"
            done >corpus/$repo-experimental.sliders

3.  View the sliders where your version's output differed from the standard version, the human version, or any other version that you have an output slider file for:

        ./compare-shifts --repo=$repo --any-wrong --controversial \
                h=corpus/$repo-human.sliders \
                g=corpus/$repo.sliders \
                x=corpus/$repo-experimental.sliders \
                >corpus/$repo-experimental-disagreements.out

4.  Perhaps add more human ratings for sliders that are still unrated but one or more versions disagreed with each other:

        ./compare-shifts --repo=$repo --controversial --no-diff \
                h=corpus/$repo-human.sliders \
                g=corpus/$repo.sliders \
                x=corpus/$repo-experimental.sliders |
            shuf -n 1000 |
            ./compare-shifts --repo=$repo \
                    h=corpus/$repo-human.sliders \
                    g=corpus/$repo.sliders \
                    x=corpus/$repo-experimental.sliders \
                    >corpus/$repo-human-input.out

    See *Adding more human ratings for a repository that is already in the corpus* for how to continue.


## Tabulate results

Decide which algorithms you want to compare, and complete *Testing a different Git version* for them. Then:

1.  Compute the number of errors that each algorithm, and default git, made:

        for repo in $(./repos)
        do
            echo "Processing $repo..."
            for algo in diff-compaction-heuristic diff-indent-heuristic
            do
                ./compare-shifts --repo=$repo --correct=h --any-wrong h=corpus/$repo-human.sliders x=corpus/$repo.sliders |
                    ./filter-sliders --omit-shifts >corpus/$repo-default-incorrect.out
                ./compare-shifts --repo=$repo --correct=h --any-wrong h=corpus/$repo-human.sliders x=corpus/$repo-$algo.sliders |
                    ./filter-sliders --omit-shifts >corpus/$repo-$algo-incorrect.out
            done
        done

2.  Summarize the results:

        ./summarize default diff-compaction-heuristic diff-indent-heuristic


## Prototype heuristic

The heuristic that is prototyped here chooses its shifts based only on the indentation of lines around the slider plus the presence/absence of blank lines nearby. It computes a score for the split that would have to be introduced at the top of the slider, and one for the split at the bottom of the slider, then adds the scores together to get an overall score for a slider shift. The shift with the lowest score wins.

The implementation of the scoring algorithm is in `diff_heuristics.py`, class `SplitScorer` or `SplitScorer2`. Feel free to play with it and tweak it. Remember, whatever heuristic we build into Git has to work acceptably well across a wide variety of programming languages and other textual input!

The prototype heuristic can be analyzed by piping a `*.slider` file to `show-slider-scores`, or as follows to analyze a single slider:

```
$ echo '8ad3cb08690bdf9a340e47ed4fdb67cbacd1edf2:dir.c 5cee349370bd2dce48d0d653ab4ce99bb79a3415:dir.c - 2191' | ./show-slider-scores --repo=$repo
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


