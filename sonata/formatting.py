
"""This module implements the format strings used to display song info.

Example usage:
import formatting
colnames = formatting.parse_colnames(self.config.currentformat)
...
newtitle = formatting.parse(self.config.titleformat, self.songinfo,
                            False, True)
...
formatcodes = formatting.formatcodes


TODO:
    * FormatCode doesn't use %code
    * TitleFormatCode .default changes every .format() call
    * _return_substrings creates empty items
"""

import re
import os
import weakref

from sonata import misc


class FormatCode:
    """Implements deafult format code behavior.

    Replaces all instances of %code with the value of key or default if the
    key doesn't exist.
    """

    def __init__(self, code, description, column, key, default=_("Unknown")):
        self.code = code
        self.description = description
        self.column = column
        self.key = key
        self.default = default

    def format(self, item):
        """Returns the value used in place of the format code"""
        try:
            value = item[self.key]
        except KeyError:
            value = None

        if value is None:
            value = self.default

        return str(value)


class NumFormatCode(FormatCode):
    """Implements format code behavior for numeric values.

    Used for numbers which need special padding.
    """

    def __init__(self, code, description, column, key, default, padding):
        super().__init__(code, description, column, key, default)
        self.padding = padding

    def format(self, item):
        value = super().format(item)
        return value.zfill(self.padding)


class PathFormatCode(FormatCode):
    """Implements format code behavior for path values."""

    def __init__(self, code, description, column, key, path_func):
        """

        path_func: os.path function to apply
        """
        super().__init__(code, description, column, key)
        self.func = getattr(os.path, path_func)

    def format(self, item):
        return self.func(super().format(item))


class TitleFormatCode(FormatCode):
    """Implements format code behavior for track titles."""

    def format(self, item):
        path = item['file']
        full_path = re.match(r"^(http://|ftp://)", path)
        # TODO: do we really have to mutate self.default here?
        self.default = path if full_path else os.path.basename(path)
        self.default = misc.escape_html(self.default)
        return super().format(item)


class LenFormatCode(FormatCode):
    """Implements format code behavior for song length."""

    def format(self, item):
        time = super().format(item)
        if time.isdigit():
            time = misc.convert_time(int(time))
        return time


class ElapsedFormatCode(FormatCode):
    """Implements format code behavior for elapsed time."""

    def format(self, item):
        if 'status:time' not in item:
            return "%E"

        time = item['status:time']
        elapsed_time = time.split(':')[0] if time else self.default
        if elapsed_time.isdigit():
            elapsed_time = misc.convert_time(int(elapsed_time))
        return elapsed_time

formatcodes = [
    FormatCode('A', _('Artist name'), _("Artist"), 'artist'),
    FormatCode('B', _('Album name'), _("Album"), 'album'),
    TitleFormatCode('T', _('Track name'), _("Track"), 'title'),
    NumFormatCode('N', _('Track number'), _("#"), 'track', '00', 2),
    NumFormatCode('D', _('Disc number'), _("#"), 'disc', '0', 0),
    FormatCode('Y', _('Year'), _("Year"), 'date', '?'),
    FormatCode('G', _('Genre'), _("Genre"), 'genre'),
    PathFormatCode('P', _('File path'), _("Path"), 'file', 'dirname'),
    PathFormatCode('F', _('File name'), _("File"), 'file', 'basename'),
    FormatCode('S', _('Stream name'), _("Stream"), 'name'),
    LenFormatCode('L', _('Song length'), _("Len"), 'time', '?'),
    ElapsedFormatCode('E', _('Elapsed time (title only)'), None, 'songpos', '?')
]

replace_map = dict((code.code, code) for code in formatcodes)
replace_expr = re.compile(r"%%[%s]" % "".join(k for k in replace_map.keys()))


def _return_substrings(format):
    """Split format along the { and } characters.

    For example:

    >>> from sonata.formatting import _return_substrings
    >>> _return_substrings("%A{-%T} {%L}")
    ['%A', '{-%T}', ' ', '{%L}']

    """

    substrings = []
    end = format
    while len(end) > 0:
        begin, sep1, end = end.partition('{')
        substrings.append(begin)
        if len(end) == 0:
            substrings.append(sep1)
            break
        begin, sep2, end = end.partition('}')
        substrings.append(sep1 + begin + sep2)
    return substrings


class ColumnFormatting:
    def __init__(self, multi_columns_format):
        self._format = multi_columns_format
        self.sub_formatters = [CachingFormatter(f, True)
                               for f in multi_columns_format.split('|')]
        self.columns_names = self._parse_column_names()

    def __len__(self):
        return len(self.columns_names)

    def __iter__(self):
        return zip(self.columns_names, self.sub_formatters)

    def _parse_column_names(self):
        def replace_format(m):
            format_code = replace_map.get(m.group(0)[1:])
            return format_code.column

        cols = [replace_expr.sub(replace_format, s).
                replace("{", "").
                replace("}", "").
                # If the user wants the format of, e.g., "#%N", we'll
                # ensure the # doesn't show up twice in a row.
                replace("##", "#")
                for s in self._format.split('|')]
        return cols


class CachingFormatter:
    def __init__(self, format, escape=False):
        self._format = _return_substrings(format)
        self._escape = escape
        self._cache = weakref.WeakKeyDictionary()
        self._format_func = _format_one

    def format(self, item):
        cache_key = item
        try:
            return self._cache[cache_key]
        except KeyError:
            pass

        result = self._format_func(self._format, item, self._escape)
        self._cache[cache_key] = result
        return result


class EmptyBrackets(Exception):
    pass


def _format_substrings(text, item):
    has_brackets = text.startswith("{") and text.endswith("}")

    def formatter(m):
        format_code = replace_map[m.group(0)[1:]]
        if has_brackets and format_code.key not in item:
            raise EmptyBrackets
        return format_code.format(item)

    try:
        text = replace_expr.sub(formatter, text)
    except EmptyBrackets:
        return ""

    return text[1:-1] if has_brackets else text


def parse(format, item, use_escape_html):
    substrings = _return_substrings(format)
    return _format_one(substrings, item, use_escape_html)


def _format_one(substrings, item, use_escape_html):
    text = "".join(_format_substrings(sub, item)
                   for sub in substrings)
    return misc.escape_html(text) if use_escape_html else text
