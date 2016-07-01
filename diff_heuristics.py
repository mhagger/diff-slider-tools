#! /usr/bin/env python3

import sys
import itertools
import functools
import re
import subprocess


verbose = False


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


def score_split(lines, index):
    """Return the badness of splitting lines before lines[index].

    The lower the score, the more preferable the split."""

    # A place to accumulate bonus factors (positive makes this
    # index more favored):
    bonus = 0

    try:
        line = lines[index]
    except IndexError:
        indent = None
    else:
        indent = get_indent(line)

    blank = (indent is None)

    pre_blank = False
    i = index - 1
    while i >= 0:
        pre_indent = get_indent(lines[i])
        if pre_indent is not None:
            break
        pre_blank = True
        i -= 1
    else:
        pre_indent = 0

    post_blank = None
    i = index + 1
    while i < len(lines):
        post_indent = get_indent(lines[i])
        if post_indent is not None:
            break
        post_blank = True
        i += 1
    else:
        post_indent = 0

    if blank:
        # Blank lines are treated as if they were indented like the
        # following non-blank line:
        indent = post_indent

    # Bonuses based on the location of blank lines:
    if pre_blank and not blank:
        bonus += 3
    elif blank and not pre_blank:
        bonus += 2
    elif blank and pre_blank:
        bonus += 1

    if indent > pre_indent:
        # The line is indented more than its predecessor. It is
        # preferable to keep these lines together, so we score it
        # based on the larger indent:
        score = indent
        bonus -= 4

    elif indent < pre_indent:
        # The line is indented less than its predecessor. It could
        # be that this line is the start of a new block (e.g., of
        # an "else" block, or of a block without a block
        # terminator) or it could be the end of the previous
        # block.
        if indent < post_indent:
            # The following line is indented more. So it is likely
            # that this line is the start of a block. It's a
            # pretty good place to split, so score it based on the
            # smaller indent:
            score = indent
            bonus += 2
        else:
            # This was probably the end of a block. We score based
            # on the line's own indent:
            score = indent

    else:
        # The line has the same indentation level as its
        # predecessor. We score it based on its own indent:
        score = indent
        # ...but if it's not blank, give it a small bonus because
        # this is more likely to span a balanced block:
        #if not blank:
        #    bonus += 1

    return 10 * score - bonus


class DiffLine:
    def __init__(self, line):
        if not line:
            raise ParsingError('empty line passed to DiffLine')
        self.prefix = line[0]
        self.line = line[1:]

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
    pass


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
        self.pre_context = pre_context
        self.change = change
        self.post_context = post_context
        self.difflines = list(itertools.chain(pre_context, change, post_context))

        # The line number of the first line of the change:
        self.line_number = line_number

        self.prefix = self.change.prefix

        self.shift_range = self._compute_shift_range()
        self.lines = [diffline.line for diffline in self.difflines]
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

    def get_score_for_line(self, shift):
        """Return the score for using the specified shift.

        The lower the score, the more preferable the shift."""

        return score_split(self.lines, shift + len(self.pre_context))

    def get_score(self, shift):
        score = self.get_score_for_line(shift)
        if shift + len(self.change) < len(self.change) + len(self.post_context):
            return score + self.get_score_for_line(shift + len(self.change))
        else:
            # The shift probably bumps up against the end of the file:
            return score + (score - 1)

    def _compute_shift_range(self):
        """Return a range object describing the limits of the allowed shift."""

        if self.change.prefix == '?':
            # Replacements cannot be slid:
            return range(0, 1)

        shift_min = 0
        while (
                shift_min - 1 >= -len(self.pre_context)
                and shift_min - 1 >= -len(self.change)
                and (self[shift_min - 1].line
                     == self[len(self.change) + shift_min - 1].line)
                ):
            shift_min -= 1

        shift_limit = 1
        while (shift_limit < len(self.change)
               and shift_limit < len(self.post_context)
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
                sys.stderr.write('Sliding hunk up by %d\n' % (-shift,))

            # Move lines from end of change to post-context:
            difflines = self.change.difflines[shift:]
            del self.change.difflines[shift:]
            for diffline in difflines:
                diffline.prefix = ' '
            self.post_context.difflines[0:0] = difflines

            # Move lines from end of pre-context to change:
            difflines = self.pre_context.difflines[shift:]
            del self.pre_context.difflines[shift:]
            for diffline in difflines:
                diffline.prefix = self.change.prefix
            self.change.difflines[0:0] = difflines
            if self.change.prefix == '-':
                self.change.deletes.difflines[0:0] = difflines
            else:
                self.change.adds.difflines[0:0] = difflines
        elif shift > 0:
            if verbose:
                sys.stderr.write('Sliding hunk down by %d\n' % (shift,))

            # Move lines from beginning of change to pre-context:
            difflines = self.change.difflines[:shift]
            del self.change.difflines[:shift]
            for diffline in difflines:
                diffline.prefix = ' '
            self.pre_context.difflines.extend(difflines)

            # Move lines from begining of post-context to change:
            difflines = self.post_context.difflines[:shift]
            del self.post_context.difflines[:shift]
            for diffline in difflines:
                diffline.prefix = self.change.prefix
            self.change.difflines.extend(difflines)
            if self.change.prefix == '-':
                self.change.deletes.difflines.extend(difflines)
            else:
                self.change.adds.difflines.extend(difflines)

        self.shift_range = range(self.shift_range.start - shift,
                                 self.shift_range.stop - shift)
        self.line_number += shift

    def find_best_shift(self):
        if len(self.shift_range) == 1:
            return self.shift_range[0]

        best_shift = 0
        best_score = None

        for shift in self.shift_range:
            score = self.get_score(shift)
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

    def show(self, slider_context=5):
        best_shift = self.find_best_shift()

        print('v' * 60)

        show_range = range(self.shift_range.start - slider_context,
                           len(self.change) + self.shift_range.stop + slider_context)

        for (i, diffline) in self.enumerate():
            if not i in show_range:
                continue

            if i in self.shift_range:
                score = '%5d' % (self.get_score(i),)
            else:
                score = '     '

            print('    %s%s %s %s >%s' % (
                self.prefix_for(self.shift_range[0], i),
                self.prefix_for(self.shift_range[-1], i),
                score,
                self.prefix_for(best_shift, i, self.change.prefix),
                diffline))

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
        """Split difflines into context, change, context, change, ..., context."""

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
        self.difflines = [DiffLine(line) for line in lines[1:]]
        self.groups = list(self.iter_groups(self.difflines))

    def iter_sliders(self):
        for i in range(1, len(self.groups) - 1, 2):
            change = self.groups[i]
            if change.prefix == '-':
                selector = lambda group: group.old_lines()
                reference_line = self.old_line
            elif change.prefix == '+':
                selector = lambda group: group.new_lines()
                reference_line = self.new_line
            else:
                # Mixed deletion/additions cannot be sliders:
                continue

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

            pre_context = Context(pre_lines)
            post_context = Context(post_lines)
            yield Slider(pre_context, change, post_context, line_number)

    def old_lines(self):
        for group in self.groups:
            for line in group.old_lines():
                yield line

    def new_lines(self):
        for group in self.groups:
            for line in group.new_lines():
                yield line


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
            i += 1

            self.new_filename = self.get_filename(FileDiff.NEW_FILE_RE, lines[i])
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


def compute_diff(repo, old, new):
    """Compute a git diff between old and new in the specified repo.

    Set some options to try to get consistent output.

    """

    cmd = [
        'git',
        '-C', repo,
        '-c', 'diff.algorithm=myers',
        'diff', '-U10',
        old, new,
        '--',
        ]
    out = subprocess.check_output(cmd)
    return out.decode('utf-8', errors='replace').split('\n')[:-1]


def find_slider(lines, old_filename, new_filename, prefix, line_number):
    """Find the specified slider in the lines provided."""

    for file_diff in iter_file_diffs(lines):
        for hunk in file_diff.hunks:
            for slider in hunk.iter_sliders():
                if (
                        slider.prefix == prefix
                        and slider.line_number + slider.shift_range[-1] == line_number
                    ):
                    return slider

    raise ParsingError('requested Slider was not found')


def compute_slider(repo,
                old_sha1, old_filename,
                new_sha1, new_filename,
                prefix, line_number):
    """Read the specified Slider."""

    lines = compute_diff(
        repo,
        '%s:%s' % (old_sha1, old_filename),
        '%s:%s' % (new_sha1, new_filename),
        )

    slider = find_slider(lines, old_filename, new_filename, prefix, line_number)
    slider.shift_canonically()
    return slider


def iter_shifts(lines):
    """Iterate over (old, new, prefix, line_number, [shift,...]) read from lines.

    lines can be any iterable over lines."""

    for line in lines:
        words = line.rstrip().split()

        if len(words) < 4:
            raise ParsingError('could not read %r' % (line,))

        (old, new, prefix, line_number, *shifts) = words
        line_number = int(line_number)
        shifts = [int(shift) for shift in shifts]

        yield (old, new, prefix, line_number, shifts)


