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
* Determining the range of "shifts" that are legal for a particular slider
* Testing prototypes of heuristics for choosing how to shift sliders
* Optimizing the heuristics by training them against a corpus of human-rated sliders
* Recording the output of all of the above in text files
* Displaying tricky cases in an easy-to-read format

It also contains

* A corpus of (at this writing) 6668 human-rated sliders from 29 open-source software projects
* An implementation of an alternative slider positioning heuristic that significantly outperforms both `git diff` and `git diff --compaction-heuristic` as of Git 2.9.0.


## Getting started

Suppose you have one or more versions of `git diff` that you would like to test against each other. The easiest way to start is by adapting and running `./run-comparison` in the top-level directory of this repository:

1.  Write one function for each version of Git that you want to test at the top of `run-comparison`. You can use the existing functions `git_290`, `git_290_compaction`, etc. as examples. The function should take a repository name and the names of two git objects as arguments, and should output the diff between those two objects as output. The function name should start with `git_`. (The old and new objects will be supplied in the format `$SHA1:$PATH`.)

2.  Adjust the initialization of the `algos` variable in `run-comparison` to list the algorithms that you want to compare. Note that these should be the short algorithm names; e.g., if your function is called `git_my_test_2`, then the short name would be `my-test-2`.

3.  If you don't want to download the entire corpus (which is about 4 GB), adjust the script `repos` to output only the repositories that you want to download.

4.  Run `./run-comparison`. The first time you run it, it takes quite a while because it fetches all 29 projects' history (about 4 GB). If you re-run it, it will only fetch any changes, so it should be much faster.

The output of `./run-comparison` is a table like the following:

| repository            | count |            290 |     compaction |     indent-new |
| --------------------- | ----: | -------------: | -------------: | -------------: |
| afnetworking          |   109 |    89  (81.7%) |    37  (33.9%) |     2   (1.8%) |
| alamofire             |    30 |    18  (60.0%) |    14  (46.7%) |     0   (0.0%) |
| angular               |   184 |   127  (69.0%) |    39  (21.2%) |     5   (2.7%) |
| animate               |   313 |     2   (0.6%) |     2   (0.6%) |     2   (0.6%) |
| ant                   |   380 |   356  (93.7%) |   152  (40.0%) |    15   (3.9%) |
| bugzilla              |   306 |   263  (85.9%) |   109  (35.6%) |    15   (4.9%) |
| corefx                |   126 |    91  (72.2%) |    22  (17.5%) |     6   (4.8%) |
| couchdb               |    78 |    44  (56.4%) |    26  (33.3%) |     6   (7.7%) |
| cpython               |   937 |   158  (16.9%) |    50   (5.3%) |     5   (0.5%) |
| discourse             |   160 |    95  (59.4%) |    42  (26.2%) |    13   (8.1%) |
| docker                |   307 |   194  (63.2%) |   198  (64.5%) |     8   (2.6%) |
| electron              |   163 |   132  (81.0%) |    38  (23.3%) |     6   (3.7%) |
| git                   |   536 |   470  (87.7%) |    73  (13.6%) |    16   (3.0%) |
| gitflow               |   127 |     0   (0.0%) |     0   (0.0%) |     0   (0.0%) |
| ionic                 |   133 |    89  (66.9%) |    29  (21.8%) |     1   (0.8%) |
| ipython               |   482 |   362  (75.1%) |   167  (34.6%) |    11   (2.3%) |
| junit                 |   161 |   147  (91.3%) |    67  (41.6%) |     1   (0.6%) |
| lighttable            |    15 |     5  (33.3%) |     0   (0.0%) |     0   (0.0%) |
| magit                 |    88 |    75  (85.2%) |    11  (12.5%) |     0   (0.0%) |
| neural-style          |    28 |     0   (0.0%) |     0   (0.0%) |     0   (0.0%) |
| nodejs                |   781 |   649  (83.1%) |   118  (15.1%) |     5   (0.6%) |
| phpmyadmin            |   491 |   481  (98.0%) |    75  (15.3%) |     2   (0.4%) |
| react-native          |   168 |   130  (77.4%) |    79  (47.0%) |     0   (0.0%) |
| rust                  |   171 |   128  (74.9%) |    30  (17.5%) |    14   (8.2%) |
| spark                 |   186 |   149  (80.1%) |    52  (28.0%) |     2   (1.1%) |
| tensorflow            |   115 |    66  (57.4%) |    48  (41.7%) |     5   (4.3%) |
| test-more             |    19 |    15  (78.9%) |     2  (10.5%) |     1   (5.3%) |
| test-unit             |    51 |    34  (66.7%) |    14  (27.5%) |     2   (3.9%) |
| xmonad                |    23 |    22  (95.7%) |     2   (8.7%) |     1   (4.3%) |
| --------------------- | ----- | -------------- | -------------- | -------------- |
| totals                |  6668 |  4391  (65.9%) |  1496  (22.4%) |   144   (2.2%) |

`count` is the number of human-rated sliders in each repository. The columns are the different algorithms being tested; here, `290` is standard `git diff` using Git 2.9.0, `compaction` is `git diff --compaction-heuristic` using the same version of Git, and `indent-new` is the heuristic being proposed. The numbers show the number and percentage of human-rated sliders that the corresponding algorithm got *wrong*.


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

    Note that this uses the installed version of `git` to compute the diffs, then detects sliders in its output and records them for later use. (The sliders are recorded in a generic format, so it doesn't really matter which version of Git is used for this step as long as it is not buggy.)

6.  Create a file that displays all of the sliders along with their diffs in a human-readable format. This file can get big, so if you want you can trim down the input that is given to it, or simply interrupt the command when it has generated as much input as you want.

        ./compare-shifts --repo=$repo --all g=corpus/$repo.sliders \
            >corpus/$repo-human-input.sliders

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

    The first line identifies the source of this slider: it comes from diffing the file Objects/bytearrayobject.c in the two specified commits. The diff adds (`+`) lines, and 1999 is the line number of the first added line in the version of the file that contains them, when the slider is shifted to its lowest possible position.

    The following lines show the slider itself:

    * A number, which is the relative shift that would move the first line of the add/delete block to that line

    * Two columns of `|` characters, showing the highest and lowest that the slider can be shifted

    * One or more columns of letters, showing where various algorithms that are under comparison would choose to shift the slider. In this case, there is only one algorithm being displayed, namely `g`, which in this case is the default Git positioning of the slider.

    * A column of `>` characters, showing the left margin of the actual lines

    * The lines themselves.

    Your job is to decide what would be the most intuitive position for this slider. The guidelines that I have been using when rating sliders by hand:

    * Best is if the diff inserts/deletes a single logical construct, for example a complete function definition, or an `else` with its associated block, or a paragraph within a comment.

    * If the diff adds/deletes an item in a list of items, then it should always show the item being added/deleted as late in the list as possible.

    * When possible, blank lines should appear at the bottom of the block of added/deleted lines rather than at the top.

    In the example above, the best position would be `-1`, because then the diff would show a single entire function being added. Record your selection at the end of the first line, changing it to:

        327535b4be335df93a353032f7d3c01aae0942d7:Objects/bytearrayobject.c 83c63e9c025810342dd7f1f2107a2eee9525bc56:Objects/bytearrayobject.c + 1999 -1

	If there are multiple positions that are equally good, you can record them all; e.g., `-2 0`.

    Rate as many sliders as you like, then save the file.

8.  Create a file containing only the sliders that you have rated without any diffs:

        ./filter-sliders --rated <corpus/$repo-human-input.sliders >>corpus/$repo-human.sliders

    This file is the permanent record of your work.

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

3.  Create a file that displays a bunch of unrated sliders in human-readable form:

        ./filter-sliders --omit-rated=corpus/$repo-human.sliders <corpus/$repo.sliders |
            shuf -n 1000 |
            ./compare-shifts --repo=$repo --all g=- >corpus/$repo-human-input.sliders

    This command uses `shuf` to choose 1000 of the sliders at random. Feel free to adjust that part of the pipeline, or use other commands to select the sliders that you would like to work on. Just remember: please try to pick a characteristic sample of sliders! If we end up with 100 times more samples of FORTRAN 66 code than C, it's going to bias any automated training that uses the corpus in a bad way!

4.  Hand-rate some sliders as described in step 7 of the previous section.

5.  Append the newly-rated sliders to the end of the existing `$repo-human.sliders` file:

        ./filter-sliders --rated <corpus/$repo-human-input.sliders >>corpus/$repo-human.sliders

6.  Commit the new `$repo-human.sliders` file into Git, push your changes, and create a pull request.


## Testing a different prototype heuristic

*To be written.*


## Testing a different Git version

If you've got an experimental version of Git that you would like to test, you probably want to see not only the numerical results, but also examples of diff sliders that it bungles:

1.  Make sure that you have created the `corpus/$repo.sliders` file as described in one of the earlier sections.

2.  Have your own experimental version of Git compute the same diffs that appear in the sliders, and read the shift that it chose using `read-shift`:

        cat corpus/$repo.sliders |
            while read old new prefix line_number shifts
            do
			    $EXPERIMENTAL_GIT -C corpus/$repo.git diff $EXPERIMENTAL_GIT_OPTS -U20 "$old" "$new" -- |
                   ./read-shift "$old" "$new" "$prefix" "$line_number"
            done >corpus/$repo-experimental.sliders

3.  View the sliders for which your version's output differed from the standard version, the human version, or any other version that you have an output slider file for:

        ./compare-shifts --repo=$repo --any-wrong --controversial \
                h=corpus/$repo-human.sliders \
                g=corpus/$repo.sliders \
                x=corpus/$repo-experimental.sliders \
                >corpus/$repo-experimental-disagreements.out

4.  Perhaps add more human ratings for sliders that are still unrated but for which one or more of the algorithms disagreed with each other:

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

    `compare-shifts` has a few other options that you might find useful. Another program, `filter-sliders`, can also be used to help select the sliders that you want. Run either program with its `--help` option to get more information.

    See *Adding more human ratings for a repository that is already in the corpus* for how to continue.


## Tabulate results

If you have already followed the steps above, then the data for your algorithm should be in files called `corpus/$repo-$algo.sliders`. The results can be summarized by running

    ./summarize $algo

You can specify as many algorithm names as you like on the command line.


## Prototype heuristic

The heuristic that is prototyped here chooses its shifts based only on the indentation of lines around the slider plus the presence/absence of blank lines nearby. It computes a score for the split that would have to be introduced at the top of the slider, and one for the split at the bottom of the slider, then adds the scores together to get an overall score for a slider shift. The shift with the lowest score wins.

The implementation of the scoring algorithm is in `diff_heuristics.py`, in the `SplitScorer` classes. Feel free to play with it and tweak it. Remember, whatever heuristic we build into Git has to work acceptably well across a wide variety of programming languages and other textual input!

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

This output includes the heuristic's scores for each possible shift of the slider. The lowest score (e.g., 152 in this example) wins. The `+` or `-` symbols to the left of the `>` show the heuristic's preferred shift; those to the right of the `>` show the shift chosen by the installed `git diff`.


