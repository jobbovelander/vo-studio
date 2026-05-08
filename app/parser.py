#!/usr/bin/env python3
"""
VO Studio – parser.py v4.1
Dual-format script parser (genummerd / inline).
"""

import re

TC_RE = r'\d{2}:\d{2}:\d{2}[:.]\d{2}'
RE_NUMBERED   = re.compile(rf'^(\d+)\s+({TC_RE})\s*$')
RE_INLINE_OUT = re.compile(rf'^({TC_RE})\s+OUT:({TC_RE})\s*[-\u2013]\s*(.+)$', re.IGNORECASE)
RE_INLINE_2TC = re.compile(rf'^({TC_RE})\s*[-\u2013]\s*({TC_RE})\s*[-\u2013]\s*(.+)$')
RE_INLINE_1TC = re.compile(rf'^({TC_RE})\s*[-\u2013]\s*(.+)$')

def tc_to_seconds(tc, fps=25):
    tc = tc.replace('.', ':')
    h, m, s, f = map(int, tc.split(':'))
    return h * 3600 + m * 60 + s + f / fps

def seconds_to_tc(secs, fps=25):
    secs = max(0.0, secs)
    total_frames = int(round(secs * fps))
    f  = total_frames % fps
    ts = total_frames // fps
    return f'{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}:{f:02d}'

def extract_annotations(text):
    return re.findall(r'\[([^\]]+)\]', text or '')

def _apply_auto_out(takes, fps):
    for i, t in enumerate(takes):
        if t['seconds_out'] is None:
            if i + 1 < len(takes):
                auto_out = takes[i + 1]['seconds_in'] - 0.5
                t['seconds_out'] = max(t['seconds_in'] + 0.5, auto_out)
                t['timecode_out'] = seconds_to_tc(t['seconds_out'], fps)
                t['auto_out'] = True
            else:
                t['auto_out'] = True
        else:
            t['auto_out'] = False
        t['duration'] = (
            round(t['seconds_out'] - t['seconds_in'], 3)
            if t['seconds_out'] else None
        )
    return takes

def _parse_numbered(lines, fps):
    takes = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = RE_NUMBERED.match(line)
        if m:
            num   = int(m.group(1))
            tc_in = m.group(2).replace('.', ':')
            text_lines = []
            i += 1
            while i < len(lines):
                nl = lines[i].strip()
                if not nl:
                    i += 1
                    break
                if RE_NUMBERED.match(nl):
                    break
                text_lines.append(nl)
                i += 1
            # FIX #1 (was): skip_next variabele verwijderd — num==1 skip na i-ophogen
            if num == 1:
                continue
            text = ' '.join(text_lines).strip()
            takes.append({
                'original_index': num,
                'timecode_in':    tc_in,
                'timecode_out':   None,
                'seconds_in':     tc_to_seconds(tc_in, fps),
                'seconds_out':    None,
                'text':           text or '(geen tekst)',
                'annotations':    extract_annotations(text),
            })
        else:
            i += 1
    for j, t in enumerate(takes):
        t['index'] = j + 1
    return _apply_auto_out(takes, fps)

def _parse_inline(lines, fps):
    takes = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = RE_INLINE_OUT.match(line) or RE_INLINE_2TC.match(line)
        if m:
            tc_in, tc_out, txt = m.group(1), m.group(2), m.group(3).strip()
            takes.append({
                'original_index': len(takes) + 1,
                'timecode_in':    tc_in,
                'timecode_out':   tc_out,
                'seconds_in':     tc_to_seconds(tc_in, fps),
                'seconds_out':    tc_to_seconds(tc_out, fps),
                'text':           txt,
                'annotations':    extract_annotations(txt),
            })
            continue
        m = RE_INLINE_1TC.match(line)
        if m:
            tc_in, txt = m.group(1), m.group(2).strip()
            takes.append({
                'original_index': len(takes) + 1,
                'timecode_in':    tc_in,
                'timecode_out':   None,
                'seconds_in':     tc_to_seconds(tc_in, fps),
                'seconds_out':    None,
                'text':           txt,
                'annotations':    extract_annotations(txt),
            })
    for j, t in enumerate(takes):
        t['index'] = j + 1
    return _apply_auto_out(takes, fps)

def parse_script(text, fps=25):
    lines = text.splitlines()
    if sum(1 for l in lines if RE_NUMBERED.match(l.strip())) >= 2:
        return _parse_numbered(lines, fps)
    return _parse_inline(lines, fps)

def insert_take_into_text(script_text, take, fps=25):
    """
    Voeg een take in op de juiste tijdcode-positie in een scriptbestand.
    take['annotations'] mag een list of JSON-string zijn.
    """
    import json as _json
    lines = script_text.splitlines()
    is_numbered = sum(1 for l in lines if RE_NUMBERED.match(l.strip())) >= 2

    # FIX #3: annotations altijd als lijst behandelen voor tekstopmaak
    anns = take.get('annotations', [])
    if isinstance(anns, str):
        try:
            anns = _json.loads(anns)
        except Exception:
            anns = []
    ann_prefix = ''.join(f'[{a}] ' for a in anns) if anns else ''

    if is_numbered:
        new_block = f"{take['original_index']}   {take['timecode_in']}\n{ann_prefix}{take['text']}\n"
        insert_after = -1
        for i, line in enumerate(lines):
            m = RE_NUMBERED.match(line.strip())
            if m:
                tc = m.group(2).replace('.', ':')
                if tc_to_seconds(tc, fps) <= take['seconds_in']:
                    insert_after = i
        pos = insert_after + 1
        while pos < len(lines) and lines[pos].strip() and not RE_NUMBERED.match(lines[pos].strip()):
            pos += 1
        lines.insert(pos, '')
        lines.insert(pos, new_block.rstrip())
    else:
        tc_str = take['timecode_in']
        text_with_ann = f"{ann_prefix}{take['text']}"
        if take.get('timecode_out'):
            new_line = f"{tc_str} OUT:{take['timecode_out']} - {text_with_ann}"
        else:
            new_line = f"{tc_str} - {text_with_ann}"
        insert_after = 0
        for i, line in enumerate(lines):
            m = RE_INLINE_1TC.match(line.strip()) or RE_INLINE_2TC.match(line.strip())
            if m:
                tc = m.group(1).replace('.', ':')
                if tc_to_seconds(tc, fps) <= take['seconds_in']:
                    insert_after = i
        lines.insert(insert_after + 1, new_line)

    return '\n'.join(lines)

def remove_take_from_text(script_text, original_index, timecode_in):
    """
    Verwijder een take uit een scriptbestand op basis van originele index of tijdcode.
    """
    # FIX #1: dead code 'skip_next' verwijderd
    lines = script_text.splitlines()
    is_numbered = sum(1 for l in lines if RE_NUMBERED.match(l.strip())) >= 2
    result = []

    if is_numbered:
        i = 0
        while i < len(lines):
            line = lines[i]
            m = RE_NUMBERED.match(line.strip())
            if m and (int(m.group(1)) == original_index or
                      m.group(2).replace('.', ':') == timecode_in):
                i += 1
                while i < len(lines) and lines[i].strip() and not RE_NUMBERED.match(lines[i].strip()):
                    i += 1
                if i < len(lines) and not lines[i].strip():
                    i += 1
            else:
                result.append(line)
                i += 1
    else:
        for line in lines:
            m = RE_INLINE_1TC.match(line.strip()) or RE_INLINE_2TC.match(line.strip())
            if m and m.group(1).replace('.', ':') == timecode_in:
                continue
            result.append(line)

    return '\n'.join(result)
