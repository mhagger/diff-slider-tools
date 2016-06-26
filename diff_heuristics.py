#! /usr/bin/env python3

import sys
import itertools
import functools
import re


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

    try:
        line = lines[index]
        indent = get_indent(line)
    except IndexError:
        indent = None

    blank = (indent is None)

    pre_indent = None
    pre_blank = False
    i = index - 1
    while i >= 0:
        pre_indent = get_indent(lines[i])
        if pre_indent is not None:
            break
        pre_blank = True
        i -= 1

    post_indent = None
    post_blank = None
    i = index + 1
    while i < len(lines):
        post_indent = get_indent(lines[i])
        if post_indent is not None:
            break
        post_blank = True
        i += 1

    # A place to accumulate bonus factors (positive makes this
    # index more favored):
    bonus = 0

    # Bonuses based on the location of blank lines:
    if pre_blank and not blank:
        bonus += 3
    elif blank and not pre_blank:
        bonus += 2
    elif blank and pre_blank:
        bonus += 1

    # Now fill in missing indent values:
    if pre_indent is None:
        pre_indent = 0

    if post_indent is None:
        post_indent = 0

    if blank:
        indent = post_indent

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
        assert difflines
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
    def __init__(self, pre_context, change, post_context):
        self.pre_context = pre_context
        self.change = change
        self.post_context = post_context
        self.difflines = list(itertools.chain(pre_context, change, post_context))

        (self.shift_min, self.shift_limit) = self._compute_slide_range()
        self.lines = [diffline.line for diffline in self.difflines]

    def __getitem__(self, i):
        """Return the line, counted from the first line of change."""

        if i < -len(self.pre_context):
            raise KeyError(i)

        return self.difflines[i + len(self.pre_context)]

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

    def _compute_slide_range(self):
        """Return (shift_min, shift_limit), the limits of the allowed shift.

        I.e., the permitted shifts are range(shift_min, shift_limit)."""

        if self.change.prefix == '?':
            # Replacements cannot be slid:
            return (0, 1)

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

        return (shift_min, shift_limit)

    def slide(self, shift):
        if shift < 0:
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

        self.shift_min -= shift
        self.shift_max -= shift

    def find_best_shift(self):
        best_shift = 0
        best_score = None

        for shift in range(self.shift_min, self.shift_limit):
            score = self.get_score(shift)
            if best_score is None or score <= best_score:
                best_shift = shift
                best_score = score

        return best_shift

    def optimize(self):
        best_shift = self.find_best_shift()
        if best_shift:
            self.slide(best_shift)

    def prefix_for(self, shift, i, c='|'):
        """Return c if the specified line number is in the shifted change.

        Otherwise, return SP."""

        if shift <= i < shift + len(self.change):
            return c
        else:
            return ' '

    def enumerate(self):
        return enumerate(self.difflines, start=-len(self.pre_context))

    def show_sliders(self, slider_context=5):
        if self.shift_limit == self.shift_min + 1:
            return

        best_shift = self.find_best_shift()

        if best_shift == 0:
            return

        print('v' * 60)

        for (i, diffline) in self.enumerate():
            if not (self.shift_min - slider_context
                    <= i
                    < len(self.change) + self.shift_limit + slider_context
                    ):
                continue

            if self.shift_min <= i < self.shift_limit:
                score = '%5d' % (self.get_score(i),)
            else:
                score = '     '

            print('    %s%s %s %s  %s' % (
                self.prefix_for(self.shift_min, i),
                self.prefix_for(self.shift_limit - 1, i),
                score,
                self.prefix_for(best_shift, i, self.change.prefix),
                diffline))

        print('^' * 60)


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
            sys.stderr.write('Error parsing %r\n' % (lines[0],))
        assert m
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
                pre_lines = functools.reduce(
                    list.__add__,
                    [group.old_lines() for group in self.groups[:i]],
                    []
                    )
                post_lines = functools.reduce(
                    list.__add__,
                    [group.old_lines() for group in self.groups[i + 1:]],
                    []
                    )
            elif change.prefix == '+':
                pre_lines = functools.reduce(
                    list.__add__,
                    [group.new_lines() for group in self.groups[:i]],
                    []
                    )
                post_lines = functools.reduce(
                    list.__add__,
                    [group.new_lines() for group in self.groups[i + 1:]],
                    []
                    )
            else:
                # Mixed deletion/additions cannot be sliders:
                continue

            pre_context = Context(pre_lines)
            post_context = Context(post_lines)
            yield Slider(pre_context, change, post_context)

    def show_sliders(self):
        for slider in self.iter_sliders():
            slider.show_sliders()

    def optimize(self):
        for slider in self.iter_sliders():
            slider.optimize()

    def old_lines(self):
        for group in self.groups:
            for line in group.old_lines():
                yield line

    def new_lines(self):
        for group in self.groups:
            for line in group.new_lines():
                yield line


class FileDiff:
    OLD_FILE_RE = re.compile(r'^\-\-\- (/dev/null|a/(?P<filename>.*))$')
    NEW_FILE_RE = re.compile(r'^\+\+\+ (/dev/null|b/(?P<filename>.*))$')

    @staticmethod
    def get_filename(file_re, line):
        m = file_re.match(line)
        assert m
        return m.group('filename')

    def __init__(self, lines):
        i = 0
        assert lines[i].startswith('diff ')
        print('File start: %s' % (lines[i],))
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

        if i < len(lines) and lines[i].startswith('index '):
            i += 1
            if i < len(lines) and lines[i].startswith('Binary files '):
                i += 1
            else:
                old_filename = self.get_filename(FileDiff.OLD_FILE_RE, lines[i])
                i += 1

                new_filename = self.get_filename(FileDiff.NEW_FILE_RE, lines[i])
                i += 1

                while i < len(lines):
                    assert lines[i].startswith('@@ ')
                    start = i
                    i += 1
                    while i < len(lines) and not lines[i].startswith('@@ '):
                        i += 1
                    end = i

                    self.hunks.append(
                        Hunk(old_filename, new_filename, lines[start:end])
                        )

    def show_sliders(self):
        for hunk in self.hunks:
            hunk.show_sliders()


def iter_file_diffs(lines):
    i = 0

    while i < len(lines):
        assert lines[i].startswith('diff ')
        start = i
        i += 1
        while i < len(lines) and not lines[i].startswith('diff '):
            i += 1
        end = i

        yield FileDiff(lines[start:end])


