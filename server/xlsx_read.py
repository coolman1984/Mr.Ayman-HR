"""Dependency-free .xlsx reader (taken over from the sibling project Trip Orders, same owner) (Office Open XML): zip + XML from the standard library.

Reads shared strings (also rich text), inline strings, numbers, booleans, errors, formulas (with their cached value),
dates and times (1900 and 1904 systems, the 1900 leap-year bug), Excel Tables, merged cells and hidden sheets.
Made to fail with clear messages (XlsxError) and to refuse zip bombs. Cell values are plain Python: str, int/float,
bool, datetime.date/time/datetime, None.
"""
import datetime as dt
import io
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_UNCOMPRESSED = 60 * 1024 * 1024
MAX_CELLS = 400_000
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
_M = '{%s}' % NS['m']
_R = '{%s}' % NS['r']

# built-in number formats that mean a date and/or a time
_DATE_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}
_TIME_ONLY_IDS = {18, 19, 20, 21}


class XlsxError(Exception):
    """The file is not a readable Excel workbook. The message is written for the person who chose the file."""


class Cell:
    __slots__ = ('v', 'f', 'fmt')

    def __init__(self, v=None, f=None, fmt=None):
        self.v, self.f, self.fmt = v, f, fmt

    def __repr__(self):
        return f'Cell({self.v!r}{", f=" + self.f if self.f else ""})'


class Sheet:
    def __init__(self, name, hidden=False):
        self.name, self.hidden = name, hidden
        self.cells = {}      # (row, col) 1-based -> Cell
        self.tables = []     # [{'name','ref','columns':[...]}]
        self.merged = []     # ['A1:B2']
        self.max_row = self.max_col = 0

    def value(self, row, col):
        c = self.cells.get((row, col))
        return c.v if c else None

    def rows(self, first=1, last=None):
        """Yield (row number, [values by column 1..max_col]) for the non-empty rows."""
        for r in range(first, (last or self.max_row) + 1):
            vals = [self.value(r, c) for c in range(1, self.max_col + 1)]
            if any(v not in (None, '') for v in vals):
                yield r, vals


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def split_ref(ref):
    m = re.fullmatch(r'\$?([A-Z]{1,3})\$?(\d+)', ref)
    if not m:
        raise XlsxError(f'Unreadable cell address "{ref}"')
    return int(m.group(2)), col_index(m.group(1))


def excel_date(serial, date1904=False):
    """Serial number -> datetime. 1900 system has the fake 29 Feb 1900, so serials from 61 up are one day too high."""
    if date1904:
        return dt.datetime(1904, 1, 1) + dt.timedelta(days=serial)
    if serial < 61:   # 0 = 00/01/1900 (time only), 1..59 = Jan/Feb 1900
        return dt.datetime(1899, 12, 31) + dt.timedelta(days=serial)
    return dt.datetime(1899, 12, 30) + dt.timedelta(days=serial)


def _is_date_format(code):
    code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.', '', code or '')
    return bool(re.search(r'[dmyhs]', code, re.I)) and not re.fullmatch(r'[#0,.%\s?/]*', code)


def _is_time_only(code):
    code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', code or '').lower()
    return bool(re.search(r'[hs]', code)) and not re.search(r'[dy]', code)


def _text(el):
    """All text inside an element (handles rich-text runs, skips phonetic runs)."""
    parts = []
    for node in el.iter():
        if node.tag == _M + 't':
            parts.append(node.text or '')
    return ''.join(parts)


class Workbook:
    def __init__(self, sheets, date1904):
        self.sheets, self.date1904 = sheets, date1904

    def sheet(self, name):
        for s in self.sheets:
            if s.name == name:
                return s
        raise KeyError(name)


def read(data):
    """bytes -> Workbook. Raises XlsxError with a clear message."""
    if not data or len(data) < 100:
        raise XlsxError('The file is empty.')
    if data[:2] != b'PK':
        raise XlsxError('This is not an Excel (.xlsx) file. Old .xls files must be saved again as .xlsx.')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise XlsxError('The file is damaged and cannot be opened.')
    if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
        raise XlsxError('The workbook is too large to import safely.')
    names = set(z.namelist())
    if 'xl/workbook.xml' not in names:
        raise XlsxError('This does not look like an Excel workbook (no sheets found).')

    def xml(name):
        try:
            return ET.fromstring(z.read(name))
        except (KeyError, ET.ParseError):
            raise XlsxError(f'The workbook is damaged (cannot read {name}).')

    wb = xml('xl/workbook.xml')
    pr = wb.find('m:workbookPr', NS)
    date1904 = bool(pr is not None and pr.get('date1904') in ('1', 'true'))
    rels = {}
    if 'xl/_rels/workbook.xml.rels' in names:
        for r in xml('xl/_rels/workbook.xml.rels').findall('rel:Relationship', NS):
            rels[r.get('Id')] = r.get('Target')
    strings = []
    if 'xl/sharedStrings.xml' in names:
        for si in xml('xl/sharedStrings.xml').findall('m:si', NS):
            strings.append(_text(si))
    formats = _read_styles(xml('xl/styles.xml')) if 'xl/styles.xml' in names else {}

    sheets, count = [], 0
    for s in wb.find('m:sheets', NS).findall('m:sheet', NS):
        target = rels.get(s.get(_R + 'id'), '')
        path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        if path not in names:
            continue
        sh = Sheet(s.get('name'), s.get('state') in ('hidden', 'veryHidden'))
        root = xml(path)
        for row in root.iter(_M + 'row'):
            for c in row.findall('m:c', NS):
                count += 1
                if count > MAX_CELLS:
                    raise XlsxError('The workbook has too many cells to import safely.')
                r, col = split_ref(c.get('r'))
                cell = _cell(c, strings, formats, date1904)
                if cell.v is not None or cell.f:
                    sh.cells[(r, col)] = cell
                    sh.max_row, sh.max_col = max(sh.max_row, r), max(sh.max_col, col)
        for mc in root.iter(_M + 'mergeCell'):
            sh.merged.append(mc.get('ref'))
        # Excel tables of this sheet
        rel_path = path.replace('worksheets/', 'worksheets/_rels/') + '.rels'
        if rel_path in names:
            for r in xml(rel_path).findall('rel:Relationship', NS):
                if r.get('Type', '').endswith('/table'):
                    tp = 'xl/tables/' + r.get('Target').split('/')[-1]
                    if tp in names:
                        t = xml(tp)
                        sh.tables.append({'name': t.get('displayName') or t.get('name'), 'ref': t.get('ref'),
                                          'columns': [tc.get('name') for tc in t.iter(_M + 'tableColumn')]})
        sheets.append(sh)
    if not sheets:
        raise XlsxError('The workbook has no sheets.')
    return Workbook(sheets, date1904)


def _read_styles(root):
    """cell style index -> number format code / id."""
    codes = {}
    nf = root.find('m:numFmts', NS)
    if nf is not None:
        for f in nf.findall('m:numFmt', NS):
            codes[int(f.get('numFmtId'))] = f.get('formatCode')
    out = {}
    xfs = root.find('m:cellXfs', NS)
    if xfs is not None:
        for i, xf in enumerate(xfs.findall('m:xf', NS)):
            fid = int(xf.get('numFmtId', 0))
            out[i] = (fid, codes.get(fid))
    return out


def _cell(c, strings, formats, date1904):
    t = c.get('t')
    f_el = c.find('m:f', NS)
    v_el = c.find('m:v', NS)
    raw = v_el.text if v_el is not None else None
    style = int(c.get('s', 0))
    fid, code = formats.get(style, (0, None))
    formula = (f_el.text or '') if f_el is not None else None
    if t == 'inlineStr':
        is_el = c.find('m:is', NS)
        return Cell(_text(is_el) if is_el is not None else '', formula)
    if raw is None:
        return Cell(None, formula)
    if t == 's':
        try:
            return Cell(strings[int(raw)], formula)
        except (ValueError, IndexError):
            raise XlsxError('The workbook is damaged (a text is missing).')
    if t in ('str', 'e'):
        return Cell(raw, formula)
    if t == 'b':
        return Cell(raw in ('1', 'true'), formula)
    try:
        num = float(raw)
    except ValueError:
        return Cell(raw, formula)
    if fid >= 164 and re.search(r'\[(h+|m+|s+)\]', code or '', re.I):   # [h]:mm = a duration, not a time of day
        return Cell(dt.timedelta(days=num), formula, code)
    is_date = fid in _DATE_IDS or (fid >= 164 and _is_date_format(code))
    if is_date:
        if fid in _TIME_ONLY_IDS or (fid >= 164 and _is_time_only(code)):
            secs = int(round((num % 1) * 86400))
            return Cell(dt.time(secs // 3600 % 24, secs % 3600 // 60, secs % 60), formula, code or str(fid))
        try:
            d = excel_date(num, date1904)
        except (OverflowError, ValueError):
            return Cell(num, formula)
        if d.hour == d.minute == d.second == 0 and d.microsecond == 0:
            return Cell(d.date(), formula, code or str(fid))
        return Cell(d.replace(microsecond=0), formula, code or str(fid))
    return Cell(int(num) if num.is_integer() and abs(num) < 1e15 else num, formula)
