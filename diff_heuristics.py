#! /usr/bin/env python3

import sys
import itertools
import functools
import re
import subprocess
import shlex


verbose = False

# The git command (possibly including options) to use when computing diffs:
git = ['git', '-c', 'diff.algorithm=myers']


class ParsingError(Exception):
    pass


def get_indent(line):
    line = line.rstrip()
    if not line:
        return None

    ret = 0
    for c in line:
        if c == ' ':
            ret += 1
        elif c == '\t':
            ret += 8 - ret % 8
        else:
            break

    return ret


class SplitMeasurements:
    def __init__(self):
        # Is the split at the end of the hunk (aside from any blank
        # lines)?
        self.end_of_hunk = False

        # How much is the line immediately following the split
        # indented (or None if the line is blank):
        self.indent = None

        # How many lines above the split are blank?
        self.pre_blank = 0

        # How much is the nearest non-blank line above the split
        # indented (or None if there is no such line)?
        self.pre_indent = None

        # How many lines after the line following the split are blank?
        self.post_blank = 0

        # How much is the nearest non-blank line after the line
        # following the split indented (or None if there is no such
        # line)?
        self.post_indent = None

    @staticmethod
    def measure(lines, index):
        """Measure various characteristics of a split before lines[index].

        Return a SplitMeasurements instance."""

        m = SplitMeasurements()

        try:
            line = lines[index]
        except IndexError:
            m.end_of_hunk = True
        else:
            m.indent = get_indent(line)

        i = index - 1
        while i >= 0:
            m.pre_indent = get_indent(lines[i])
            if m.pre_indent is not None:
                break
            m.pre_blank += 1
            i -= 1

        i = index + 1
        while i < len(lines):
            m.post_indent = get_indent(lines[i])
            if m.post_indent is not None:
                break
            m.post_blank += 1
            i += 1

        return m


class BaseSplitScorer:
    @classmethod
    def get_parameter_names(klass):
        return [name for (name, default) in klass.PARAMETERS]

    @classmethod
    def add_arguments(klass, parser):
        for (parameter, default) in klass.PARAMETERS:
            parser.add_argument(
                '--%s' % (parameter.replace('_', '-'),), type=int, default=default,
                )

    @classmethod
    def from_options(klass, options):
        kw = {}
        for (parameter, default) in klass.PARAMETERS:
            kw[parameter] = getattr(options, parameter, default)
        return klass(**kw)

    def __init__(self, **kw):
        for (parameter, default) in self.PARAMETERS:
            setattr(self, parameter, kw.pop(parameter, default))

        if kw:
            print(
                'The following %s parameter(s) are unknown '
                'and will be ignored:' % (self.__class__.__name__,),
                *['    %s' % (k,) for k in kw],
                file=sys.stderr, sep='\n'
                )

    def __call__(self, lines, index):
        """Return the badness of splitting lines before lines[index].

        The lower the score, the more preferable the split."""

        return self.evaluate(SplitMeasurements.measure(lines, index))

    def iter_perturbed(self, steps, vary_parameters=None, max_perturbations=1,):
        yield self

        if max_perturbations == 0 or not steps:
            return

        if vary_parameters is None:
            vary_parameters = self.get_parameter_names()

        args = dict(self.get_arguments())
        for name in vary_parameters:
            old_value = args[name]
            for step in steps:
                args[name] = old_value + step
                scorer = self.__class__(**args)
                yield from scorer.iter_perturbed(
                    steps, vary_parameters=vary_parameters,
                    max_perturbations=max_perturbations - 1,
                    )
            args[name] = old_value

    def get_arguments(self):
        return tuple(
            (name, getattr(self, name))
            for name in self.get_parameter_names()
            )

    def __hash__(self):
        return hash((self.__class__.__name__, self.get_arguments()))

    def __eq__(self, other):
        return (
            isinstance(other, self.__class__)
            and self.get_arguments() == other.get_arguments()
            )

    def __str__(self):
        return '_'.join(
            '%s=%d' % (name, value)
            for (name,value) in self.get_arguments()
            )

    def as_command_line_options(self):
        """Return the command-line options needed to select this scorer."""

        return [
            '--%s=%d' % (parameter.replace('_', '-'), value)
            for (parameter, value) in self.get_arguments()
            ]

    def as_filename_string(self):
        """Return a string representation that could be inserted in a filename."""

        return '_'.join(
            '%d' % (value,)
            for (parameter, value) in self.get_arguments()
            )

    def __repr__(self):
        return '%s(%s)' % (
            self.__class__.__name__,
            ', '.join(
                '%s=%d' % (name, value)
                for (name,value) in self.get_arguments()
                )
            )


class SplitScorer1(BaseSplitScorer):
    # A list [(parameter_name, default_value), ...]
    PARAMETERS = [
        ('start_of_hunk_bonus', 9),
        ('end_of_hunk_bonus', 20),
        ('follows_blank_bonus', 20),
        ('precedes_blank_bonus', 5),
        ('between_blanks_bonus', 19),
        ('relative_indent_bonus', -2),
        ('relative_outdent_bonus', -13),
        ('relative_dedent_bonus', -13),
        ('block_bonus', -1),
        ]

    def evaluate(self, m):
        """Evaluate the score for a split with the specified measurements."""

        # A place to accumulate bonus factors (positive makes this
        # index more favored):
        bonus = 0

        if m.pre_indent is None and m.pre_blank == 0:
            bonus += self.start_of_hunk_bonus

        if m.end_of_hunk:
            bonus += self.end_of_hunk_bonus

        # Bonuses based on the location of blank lines:
        if m.pre_blank and m.indent is not None:
            bonus += self.follows_blank_bonus
        elif m.indent is None and not m.pre_blank:
            bonus += self.precedes_blank_bonus
        elif m.indent is None and m.pre_blank:
            bonus += self.between_blanks_bonus

        if m.indent is not None:
            indent = m.indent
        else:
            indent = m.post_indent

        if indent is None:
            score = 0
        elif m.pre_indent is None:
            score = indent
        elif indent > m.pre_indent:
            # The line is indented more than its predecessor. It
            # is preferable to keep these lines together, so we
            # score it based on the larger indent:
            score = indent
            bonus += self.relative_indent_bonus

        elif indent < m.pre_indent:
            # The line is indented less than its predecessor. It
            # could be that this line is the start of a new block
            # (e.g., of an "else" block, or of a block without a
            # block terminator) or it could be the end of the
            # previous block.
            if m.post_indent is None or indent >= m.post_indent:
                # That was probably the end of a block. Score
                # based on the line's own indent:
                score = indent
                bonus += self.relative_dedent_bonus
            else:
                # The following line is indented more. So it is
                # likely that this line is the start of a block.
                # It's a pretty good place to split, so score it
                # based on its own indent:
                score = indent
                bonus += self.relative_outdent_bonus

        else:
            # The line has the same indentation level as its
            # predecessor. We score it based on its own indent:
            score = indent
            # If it's not blank, that's a little bit of evidence
            # that the split is within a block of sibling lines:
            if m.indent is not None:
                bonus += self.block_bonus

        return 10 * score - bonus


class SplitScorer2(BaseSplitScorer):
    # A list [(parameter_name, default_value), ...]
    PARAMETERS = [
        ('start_of_hunk_bonus', 9),
        ('end_of_hunk_bonus', 46),

        ('total_blank_weight', 4),
        ('pre_blank_weight', 16),

        ('relative_indent_bonus', -1),
        ('relative_indent_has_blank_bonus', 15),
        ('relative_outdent_bonus', -19),
        ('relative_outdent_has_blank_bonus', 2),
        ('relative_dedent_bonus', -63),
        ('relative_dedent_has_blank_bonus', 50),
        ]

    def evaluate(self, m):
        """Evaluate the score for a split with the specified measurements."""

        # A place to accumulate bonus factors (positive makes this
        # index more favored):
        bonus = 0

        if m.pre_indent is None and m.pre_blank == 0:
            bonus += self.start_of_hunk_bonus

        if m.end_of_hunk:
            bonus += self.end_of_hunk_bonus

        total_blank = m.pre_blank
        if m.indent is None:
            total_blank += 1 + m.post_blank

        # Bonuses based on the location of blank lines:
        bonus += (
            self.total_blank_weight * total_blank
            + self.pre_blank_weight * m.pre_blank
            )

        if m.indent is not None:
            indent = m.indent
        else:
            indent = m.post_indent

        is_blank = int(bool(total_blank))

        if indent is None:
            score = 0
        elif m.pre_indent is None:
            score = indent
        elif indent > m.pre_indent:
            # The line is indented more than its predecessor. It
            # is preferable to keep these lines together, so we
            # score it based on the larger indent:
            score = indent
            bonus += (
                self.relative_indent_bonus
                + self.relative_indent_has_blank_bonus * is_blank
                )

        elif indent < m.pre_indent:
            # The line is indented less than its predecessor. It
            # could be that this line is the start of a new block
            # (e.g., of an "else" block, or of a block without a
            # block terminator) or it could be the end of the
            # previous block.
            if m.post_indent is None or indent >= m.post_indent:
                # That was probably the end of a block. Score
                # based on the line's own indent:
                score = indent
                bonus += (
                    self.relative_dedent_bonus
                    + self.relative_dedent_has_blank_bonus * is_blank
                    )
            else:
                # The following line is indented more. So it is
                # likely that this line is the start of a block.
                # It's a pretty good place to split, so score it
                # based on its own indent:
                score = indent
                bonus += (
                    self.relative_outdent_bonus
                    + self.relative_outdent_has_blank_bonus * is_blank
                    )

        else:
            # The line has the same indentation level as its
            # predecessor. We score it based on its own indent:
            score = indent

        return 10 * score - bonus


class SplitScore3:
    def __init__(self, scorer, effective_indent, penalty):
        self.scorer = scorer
        self.effective_indent = effective_indent
        self.penalty = penalty

    def __add__(self, other):
        return SplitScore3(
            self.scorer,
            self.effective_indent + other.effective_indent,
            self.penalty + other.penalty
            )

    def __le__(self, other):
        cmp_indents = (
            (self.effective_indent > other.effective_indent)
            - (self.effective_indent < other.effective_indent)
            )
        return 60 * cmp_indents + (self.penalty - other.penalty) <= 0

    def __str__(self):
        return '(%d,%d)' % (self.effective_indent, self.penalty)


class SplitScorer3(BaseSplitScorer):
    # A list [(parameter_name, default_value), ...]
    PARAMETERS = [
        ('start_of_hunk_penalty', 1),
        ('end_of_hunk_penalty', 21),

        ('total_blank_weight', -30),
        ('post_blank_weight', 6),

        ('relative_indent_penalty', -4),
        ('relative_indent_with_blank_penalty', 10),
        ('relative_outdent_penalty', 24),
        ('relative_outdent_with_blank_penalty', 17),
        ('relative_dedent_penalty', 23),
        ('relative_dedent_with_blank_penalty', 17),
        ]

    def evaluate(self, m):
        """Evaluate the score for a split with the specified measurements."""

        # A place to accumulate penalty factors (positive makes this
        # index less favored):
        penalty = 0

        if m.pre_indent is None and m.pre_blank == 0:
            penalty += self.start_of_hunk_penalty

        if m.end_of_hunk:
            penalty += self.end_of_hunk_penalty

        # Set post_blank to the number of blank lines after the split,
        # including the line itself:
        if m.indent is None:
            post_blank = 1 + m.post_blank
        else:
            post_blank = 0

        total_blank = m.pre_blank + post_blank

        # Penalty based on the location of blank lines:
        penalty += (
            self.total_blank_weight * total_blank
            + self.post_blank_weight * post_blank
            )

        if m.indent is not None:
            indent = m.indent
        else:
            indent = m.post_indent

        is_blank = int(bool(m.pre_blank + post_blank))

        if indent is None:
            effective_indent = -1
        else:
            effective_indent = indent

        if indent is None:
            # No adjustments needed.
            pass
        elif m.pre_indent is None:
            # No adjustments needed.
            pass
        elif indent > m.pre_indent:
            # The line is indented more than its predecessor. It
            # is preferable to keep these lines together, so we
            # score it based on the larger indent:
            if is_blank:
                penalty += self.relative_indent_with_blank_penalty
            else:
                penalty += self.relative_indent_penalty

        elif indent == m.pre_indent:
            # No adjustments needed.
            pass
        else:
            # The line is indented less than its predecessor. It
            # could be that this line is the start of a new block
            # (e.g., of an "else" block, or of a block without a
            # block terminator) or it could be the end of the
            # previous block.
            if m.post_indent is None or indent >= m.post_indent:
                # That was probably the end of a block. Score
                # based on the line's own indent:
                if is_blank:
                    penalty += self.relative_dedent_with_blank_penalty
                else:
                    penalty += self.relative_dedent_penalty
            else:
                # The following line is indented more. So it is
                # likely that this line is the start of a block.
                # It's a pretty good place to split, so score it
                # based on its own indent:
                if is_blank:
                    penalty += self.relative_outdent_with_blank_penalty
                else:
                    penalty += self.relative_outdent_penalty

        return SplitScore3(self, effective_indent, penalty)


DefaultSplitScorer = SplitScorer3


class DiffLine:
    def __init__(self, prefix, line):
        self.prefix = prefix
        self.line = line

    def __bool__(self):
        return bool(self.line.rstrip())

    def __str__(self):
        return self.prefix + self.line


class Group:
    def __init__(self, difflines):
        self.difflines = list(difflines)

    def __len__(self):
        return len(self.difflines)

    def __iter__(self):
        return iter(self.difflines)

    def old_lines(self):
        return list(self.difflines)

    def new_lines(self):
        return list(self.difflines)


class Context(Group):
    def __getitem__(self, i):
        return self.difflines[i]


class Change(Group):
    def __init__(self, difflines):
        if not difflines:
            raise ParsingError('difflines is empty')

        self.difflines = list(difflines)

        self.deletes = Group([
            diffline
            for diffline in difflines
            if diffline.prefix == '-'
            ])
        self.adds = Group([
            diffline
            for diffline in difflines
            if diffline.prefix == '+'
            ])

        self.prefix = self._compute_prefix()

    def __len__(self):
        return len(self.difflines)

    def __iter__(self):
        return iter(self.difflines)

    def old_lines(self):
        return list(self.deletes)

    def new_lines(self):
        return list(self.adds)

    def _compute_prefix(self):
        if self.deletes and self.adds:
            return '?'
        elif self.deletes:
            return '-'
        elif self.adds:
            return '+'
        else:
            raise RuntimeError('Empty Change!')


class Slider:
    def __init__(self, pre_context, change, post_context, line_number):
        # Replacements cannot be slid:
        assert change.prefix in '+-'

        self.pre_context = pre_context
        self.change = change
        self.post_context = post_context
        self.difflines = list(itertools.chain(pre_context, change, post_context))

        # The line number of the first line of the change:
        self.line_number = line_number

        self.prefix = self.change.prefix

        self.shift_range = self._compute_shift_range()
        # Ensure we have no non-slidable sliders:
        assert len(self.shift_range) > 1

        self.lines = [diffline.line for diffline in self.difflines]

        # A cache of measure() results:
        self.measurements = dict()

        if verbose:
            sys.stderr.write(
                '    Slider: %d..%d at line %d\n'
                % (self.shift_range[0], self.shift_range[-1], self.line_number)
                )

    def __getitem__(self, i):
        """Return the line, counted from the first line of change."""

        if i < -len(self.pre_context):
            raise KeyError(i)

        return self.difflines[i + len(self.pre_context)]

    def shift_canonically(self):
        """Shift this slider as far down as possible.

        This is the shift used by Git as of release 2.9.0 by default.

        Return the shift that this Slider had before, measured
        relative to the canonical shift (i.e., the value will always
        be less than or equal to zero).

        """

        max_shift = self.shift_range[-1]
        self.slide(max_shift)
        return -max_shift

    def measure(self, split):
        """Return a SplitMeasurements for the specified split."""

        m = self.measurements.get(split)
        if m is None:
            m = SplitMeasurements.measure(self.lines, split + len(self.pre_context))
            self.measurements[split] = m

        return m

    def get_score_for_split(self, scorer, split):
        """Return the score for splitting above the specified line.

        The lower the score, the less bad the split."""

        return scorer.evaluate(self.measure(split))

    def get_score(self, scorer, shift):
        split1 = shift
        split2 = shift + len(self.change)

        assert -len(self.pre_context) <= split1
        assert split2 <= len(self.change) + len(self.post_context)
        return (
            self.get_score_for_split(scorer, split1)
            + self.get_score_for_split(scorer, split2)
            )

    def _compute_shift_range(self):
        """Return a range object describing the limits of the allowed shift."""

        shift_min = 0
        while (
                len(self.pre_context) + shift_min - 1 >= 0
                and len(self.change) + shift_min - 1 >= 0
                and (self[shift_min - 1].line
                     == self[len(self.change) + shift_min - 1].line)
                ):
            shift_min -= 1

        shift_limit = 1
        while (shift_limit <= len(self.change)
               and shift_limit <= len(self.post_context)
               and (self[shift_limit - 1].line
                    == self[len(self.change) + shift_limit - 1].line)
                ):
            shift_limit += 1

        return range(shift_min, shift_limit)

    def slide(self, shift):
        if shift == 0:
            return

        if shift < 0:
            if verbose:
                sys.stderr.write(
                    'Sliding hunk up by %d from %d to %d\n' % (
                        -shift, self.line_number, self.line_number + shift,
                        )
                    )

            # Move lines from end of change to post-context:
            difflines = [
                DiffLine(' ', diffline.line)
                for diffline in self.change.difflines[shift:]
                ]
            del self.change.difflines[shift:]
            self.post_context.difflines[0:0] = difflines

            # Move lines from end of pre-context to change:
            difflines = [
                DiffLine(self.change.prefix, diffline.line)
                for diffline in self.pre_context[shift:]
                ]
            del self.pre_context.difflines[shift:]
            self.change.difflines[0:0] = difflines
            if self.change.prefix == '-':
                self.change.deletes.difflines[0:0] = difflines
            else:
                self.change.adds.difflines[0:0] = difflines
        elif shift > 0:
            if verbose:
                sys.stderr.write(
                    'Sliding hunk down by %d from %d to %d\n' % (
                        shift, self.line_number, self.line_number + shift,
                        )
                    )

            # Move lines from beginning of change to pre-context:
            difflines = [
                DiffLine(' ', diffline.line)
                for diffline in self.change.difflines[:shift]
                ]
            del self.change.difflines[:shift]
            self.pre_context.difflines.extend(difflines)

            # Move lines from begining of post-context to change:
            difflines = [
                DiffLine(self.change.prefix, diffline.line)
                for diffline in self.post_context[:shift]
                ]
            del self.post_context.difflines[:shift]
            self.change.difflines.extend(difflines)
            if self.change.prefix == '-':
                self.change.deletes.difflines.extend(difflines)
            else:
                self.change.adds.difflines.extend(difflines)

        self.shift_range = range(self.shift_range.start - shift,
                                 self.shift_range.stop - shift)
        self.line_number += shift

        self.measurements = dict()

    def find_best_shift(self, scorer):
        if len(self.shift_range) == 1:
            return self.shift_range[0]

        best_shift = 0
        best_score = None

        for shift in self.shift_range:
            score = self.get_score(scorer, shift)
            if best_score is None or score <= best_score:
                best_shift = shift
                best_score = score

        return best_shift

    def prefix_for(self, shift, i, c='|'):
        """Return c if the specified line number is in the shifted change.

        Otherwise, return SP."""

        if shift <= i < shift + len(self.change):
            return c
        else:
            return ' '

    def enumerate(self):
        return enumerate(self.difflines, start=-len(self.pre_context))

    def show(self, scorer, slider_context=5):
        best_shift = self.find_best_shift(scorer)

        print('v' * 60)

        show_range = range(self.shift_range.start - slider_context,
                           self.shift_range.stop + len(self.change) + slider_context)

        for (i, diffline) in self.enumerate():
            if i not in show_range:
                continue

            if i in self.shift_range:
                score = str(self.get_score_for_split(scorer, i))
            elif i - len(self.change) in self.shift_range:
                score = str(self.get_score_for_split(scorer, i))
            else:
                score = ''

            print('         %s%s %8s %s >%s' % (
                self.prefix_for(self.shift_range[0], i),
                self.prefix_for(self.shift_range[-1], i),
                score,
                self.prefix_for(best_shift, i, self.change.prefix),
                diffline))

        i = self.shift_range[-1] + len(self.change)
        if (
                i == len(self.change) + len(self.post_context)
                and i - len(self.change) in self.shift_range
                ):
            score = str(self.get_score_for_split(scorer, i))
            print('         %s%s %8s %s >%s' % (
                ' ', ' ',
                score,
                ' ',
                '<EOF>'))

        print('^' * 60)

    def show_comparison(self, columns, line_prefix='', slider_context=5):
        show_range = range(self.shift_range.start - slider_context,
                           len(self.change) + self.shift_range.stop + slider_context)

        for (i, diffline) in self.enumerate():
            if not i in show_range:
                continue

            flags = ''
            for (column_name, shift) in columns:
                flags += self.prefix_for(shift, i, column_name)

            if i in self.shift_range:
                shift_string = '%d' % (i,)
            else:
                shift_string = ''

            annotation = '%s %s%s %s >' % (
                shift_string,
                self.prefix_for(self.shift_range[0], i),
                self.prefix_for(self.shift_range[-1], i),
                flags,
                )

            print('%s%*s%s' % (
                line_prefix,
                16 - len(line_prefix), annotation,
                diffline.line
                ))


class Hunk:
    HEADER_RE = re.compile(
        r'''
        ^
        \@\@
        \s
        \-(?P<old_line>\d+)(\,(?P<old_len>\d+))?
        \s
        \+(?P<new_line>\d+)(\,(?P<new_len>\d+))?
        \s
        \@\@
        ''',
        re.VERBOSE)

    @staticmethod
    def iter_groups(difflines):
        """Split difflines into context, change, context, change, ..., context.

        The first and last elements are always Context instances
        (however, they may be empty).

        """

        processing_change = False
        group = []

        for diffline in difflines:
            if diffline.prefix == '\\':
                continue
            is_change_line = (diffline.prefix != ' ')
            if is_change_line and not processing_change:
                g = Context(group)
                yield g
                processing_change = True
                group = []
            elif not is_change_line and processing_change:
                g = Change(group)
                yield g
                processing_change = False
                group = []
            group.append(diffline)

        if processing_change:
            g = Change(group)
            yield g
            group = []

        yield Context(group)

    def __init__(self, old_filename, new_filename, lines):
        self.old_filename = old_filename
        self.new_filename = new_filename
        m = self.HEADER_RE.match(lines[0])
        if not m:
            raise ParsingError('Error parsing %r\n' % (lines[0],))
        self.old_line = int(m.group('old_line'))
        if m.group('old_len') is None:
            self.old_len = None
        else:
            self.old_len = int(m.group('old_len'))
        self.new_line = int(m.group('new_line'))
        if m.group('new_len') is None:
            self.new_len = None
        else:
            self.new_len = int(m.group('new_len'))
        self.difflines = [DiffLine(line[0], line[1:]) for line in lines[1:]]
        self.groups = list(self.iter_groups(self.difflines))

    def iter_sliders(self):
        for i in range(1, len(self.groups) - 1, 2):
            pre_group, change, post_group = self.groups[i - 1:i + 2]
            if change.prefix == '-':
                selector = lambda group: group.old_lines()
                reference_line = self.old_line
            elif change.prefix == '+':
                selector = lambda group: group.new_lines()
                reference_line = self.new_line
            else:
                # Mixed deletion/additions cannot be sliders:
                continue

            if pre_group and pre_group[-1].line == change.difflines[-1].line:
                # This change can be slid up; proceed:
                pass
            elif post_group and post_group[0].line == change.difflines[0].line:
                # This change can be slid down; proceed:
                pass
            else:
                # This change cannot be slid:
                continue

            # Use all of the lines in the hunk as context:
            pre_lines = functools.reduce(
                list.__iadd__,
                [selector(group) for group in self.groups[:i]],
                []
                )
            post_lines = functools.reduce(
                list.__iadd__,
                [selector(group) for group in self.groups[i + 1:]],
                []
                )
            line_number = reference_line + len(pre_lines)

            yield Slider(
                Context(pre_lines),
                Change(change.difflines),
                Context(post_lines),
                line_number,
                )

    def old_lines(self):
        for group in self.groups:
            yield from group.old_lines()

    def new_lines(self):
        for group in self.groups:
            yield from group.new_lines()


class FileDiff:
    INDEX_RE = re.compile(r'^index (?P<old_sha1>[0-9a-f]+)\.\.(?P<new_sha1>[0-9a-f]+) [0-7]+$')

    OLD_FILE_RE = re.compile(r'^\-\-\- (/dev/null|a/(?P<filename>.*))$')
    NEW_FILE_RE = re.compile(r'^\+\+\+ (/dev/null|b/(?P<filename>.*))$')

    @staticmethod
    def get_filename(file_re, line):
        m = file_re.match(line)
        if not m:
            raise ParsingError('could not parse filename from %r' % (line,))
        return m.group('filename')

    def __init__(self, lines):
        if not lines:
            raise ParsingError('no lines in FileDiff')

        i = 0
        while not lines[i].startswith('diff '):
            i += 1
            if i >= len(lines):
                raise ParsingError('diff line not found in FileDiff')

        if verbose:
            sys.stderr.write('File start: %s\n' % (lines[i],))

        i += 1

        if lines[i].startswith('similarity '):
            i += 1
            while i < len(lines) and lines[i].startswith('rename '):
                i += 1

        if i < len(lines) and (
                lines[i].startswith('new ')
                or lines[i].startswith('deleted ')
                ):
            i += 1

        self.hunks = []

        if i >= len(lines):
            return

        m = FileDiff.INDEX_RE.match(lines[i])
        i += 1
        if not m:
            return

        self.old_sha1 = m.group('old_sha1')
        self.new_sha1 = m.group('new_sha1')

        if i < len(lines) and lines[i].startswith('Binary files '):
            i += 1
        else:
            self.old_filename = self.get_filename(FileDiff.OLD_FILE_RE, lines[i])
            if shlex.quote(self.old_filename) != self.old_filename:
                raise ParsingError(
                    'filename %r is not safe for shell commands' % (self.old_filename,)
                    )
            i += 1

            self.new_filename = self.get_filename(FileDiff.NEW_FILE_RE, lines[i])
            if shlex.quote(self.new_filename) != self.new_filename:
                raise ParsingError(
                    'filename %r is not safe for shell commands' % (self.new_filename,)
                    )
            i += 1

            while i < len(lines):
                assert lines[i].startswith('@@ ')
                start = i
                i += 1
                while i < len(lines) and not lines[i].startswith('@@ '):
                    i += 1
                end = i

                try:
                    self.hunks.append(
                        Hunk(self.old_filename, self.new_filename, lines[start:end])
                        )
                except ParsingError as e:
                    sys.stderr.write('%s\n' % (e,))


def iter_file_diffs(lines):
    i = 0

    while i < len(lines):
        assert lines[i].startswith('diff ')
        start = i
        i += 1
        while i < len(lines) and not lines[i].startswith('diff '):
            i += 1
        end = i

        try:
            yield FileDiff(lines[start:end])
        except ParsingError as e:
            sys.stderr.write('%s\n' % (e,))


last_diff_args = None
last_diff = None

def compute_diff(repo, old, new):
    """Compute a git diff between old and new in the specified repo.

    Set some options to try to get consistent output.

    """

    global last_diff_args, last_diff

    args = (repo, old, new)
    if last_diff_args == args:
        return last_diff

    cmd = git + [
        '-C', repo,
        'diff', '-U10',
        old, new,
        '--',
        ]
    out = subprocess.check_output(cmd)
    last_diff_args = args
    last_diff = out.decode('utf-8', errors='replace').split('\n')[:-1]
    return last_diff


def find_slider(lines, old_filename, new_filename, prefix, line_number):
    """Find the specified slider in the lines provided.

    The line number must be canonical, but the returned slider will
    not necessarily be shifted canonically.

    """

    for file_diff in iter_file_diffs(lines):
        for hunk in file_diff.hunks:
            for slider in hunk.iter_sliders():
                if (
                        slider.prefix == prefix
                        and slider.line_number + slider.shift_range[-1] == line_number
                    ):
                    return slider

    raise ParsingError('requested Slider was not found')


COMMENT_RE = re.compile(r'^\s*(\#.*)?$')


def iter_shifts(lines):
    """Iterate over (old, new, prefix, line_number, [shift,...]) read from lines.

    lines can be any iterable over lines. Ignore blank lines or lines
    that start with '#'.

    """

    for line in lines:
        if COMMENT_RE.match(line):
            continue

        words = line.rstrip().split()

        if len(words) < 4:
            raise ParsingError('could not read %r' % (line,))

        (old, new, prefix, line_number, *shifts) = words
        try:
            line_number = int(line_number)
        except ValueError:
            raise ParsingError(
                'line number (%r) is not an integer in line %r'
                % (line_number, line,)
                )

        shifts = [int(shift) for shift in shifts]

        yield (old, new, prefix, line_number, shifts)


class SliderName:
    def __init__(self, old, new, prefix, line_number):
        self.old = old
        self.new = new
        self.prefix = prefix
        self.line_number = line_number

    def __hash__(self):
        return hash((self.old, self.new, self.prefix, self.line_number))

    def __eq__(self, other):
        return (
            (self.old, self.new, self.prefix, self.line_number)
            == (other.old, other.new, other.prefix, other.line_number)
            )

    def __str__(self):
        s = '%s %s %s %d' % (
            self.old, self.new, self.prefix, self.line_number,
            )

        return s

    def compute_slider(self, repo):
        (old_sha1, old_filename) = self.old.split(':', 1)
        (new_sha1, new_filename) = self.new.split(':', 1)

        lines = compute_diff(
            repo,
            '%s:%s' % (old_sha1, old_filename),
            '%s:%s' % (new_sha1, new_filename),
            )

        slider = find_slider(
            lines, old_filename, new_filename, self.prefix, self.line_number,
            )
        slider.shift_canonically()
        return slider

    def write(self, f, shifts=[]):
        """Write this SliderName to f, followed by a newline.

        If shifts is specified, include those at the end of the line.

        """

        s = str(self)
        if shifts:
            s += ' ' + ' '.join(map(str, shifts))
        s += '\n'
        f.write(s)

    @staticmethod
    def read(lines):
        """Iterate over (SliderName, shifts) found in lines.

        `lines` can be any iterable over lines. See `iter_shifts` for more
        information.

        """

        for (old, new, prefix, line_number, shifts) in iter_shifts(lines):
            yield (SliderName(old, new, prefix, line_number), shifts,)


def load_scores(filename):
    """Load previously-computed scores from a file.

    Return a dict {scorer : score}."""

    scores = dict()
    with open(filename) as f:
        for line in f:
            (score, scorer) = line.strip().split(maxsplit=1)
            score = int(score)
            scorer = eval(scorer)
            scores[scorer] = score

    return scores


